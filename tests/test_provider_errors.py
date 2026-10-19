"""What a learner is told when a keyed model API or Jev misbehaves: unreachable, slow, garbled or failing mid-stream.

Both run against a loopback server whose answers each test scripts; nothing reaches a real service.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import fakejev
from lemma import jev, llm


class Scripted(BaseHTTPRequestHandler):
    """Answers each request with the next (status, content type, body, delay) in `script`, and records it."""

    script: list = []
    calls: list = []

    def log_message(self, *a):
        pass

    def answer(self):
        length = int(self.headers.get("Content-Length") or 0)
        Scripted.calls.append({"path": self.path, "body": self.rfile.read(length) if length else b""})
        status, ctype, body, delay = Scripted.script.pop(0)
        time.sleep(delay)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = do_POST = answer


def stream(*events):
    return ("".join(f"data: {e if isinstance(e, str) else json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n").encode()


class Loopback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Scripted)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        Scripted.script, Scripted.calls = [], []

    def then(self, status=200, body=b"", ctype="application/json", delay=0.0):
        Scripted.script.append((status, ctype, body if isinstance(body, bytes) else json.dumps(body).encode(), delay))


class KeyedProviders(Loopback):
    def provider(self, key="k", base=None):
        return llm.HTTPProvider(llm.ProviderInfo("openai", "OpenAI", base or self.base + "/v1", "gpt-6.1-sol", ""), key)

    def send(self, p=None, **kw):
        return (p or self.provider()).conversation("S", "<paper>x</paper>").send("task", **kw)

    def assert_error(self, message, call):
        with self.assertRaises(llm.ProviderError) as e:
            call()
        self.assertEqual(str(e.exception), message)

    def test_no_request_is_sent_without_a_key(self):
        self.assert_error("Add your OpenAI key in Settings to build lessons.", lambda: self.provider(key=" ").models())
        self.assertEqual(Scripted.calls, [])

    def test_unreachable_slow_and_garbled_apis(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            closed = f"http://127.0.0.1:{s.getsockname()[1]}/v1"
        with self.assertRaises(llm.ProviderError) as e:
            self.provider(base=closed).models()
        self.assertTrue(str(e.exception).startswith("Couldn't reach OpenAI ("), e.exception)
        self.then(body=b"<html>gateway</html>")
        self.assert_error("OpenAI sent a reply OpenLemma couldn't read.", lambda: self.provider().models())
        self.then(body={"data": []}, delay=1.0)
        self.assert_error("OpenAI took too long to reply.", lambda: self.provider().request("GET", "/models", timeout=0.2))

    def test_error_bodies_that_are_not_json_still_explain_themselves(self):
        self.then(502, b"Bad gateway, try later", "text/plain")
        self.assert_error("OpenAI returned an error (502): Bad gateway, try later", lambda: self.send())
        self.then(429, {"error": "slow down"})
        self.assert_error("OpenAI says you've hit a rate or usage limit: slow down", lambda: self.send())
        self.then(500, {"error": {}})
        self.assert_error("OpenAI returned an error (500): no details", lambda: self.send())

    def test_an_error_inside_the_stream_is_reported(self):
        self.then(body=stream({"choices": [{"delta": {"content": "{\"a\""}}]}, "not json", {"error": {"message": "overloaded"}}), ctype="text/event-stream")
        self.assert_error("OpenAI returned an error: overloaded", lambda: self.send())
        self.then(body=stream({"error": "plain words"}), ctype="text/event-stream")
        self.assert_error("OpenAI returned an error: plain words", lambda: self.send())

    def test_thinking_reported_under_either_name(self):
        self.then(body=stream({"choices": [{"delta": {"reasoning": "hmm"}}]}, {"choices": [{"delta": {"content": "{}"}, "finish_reason": "stop"}]}),
                  ctype="text/event-stream")
        seen = []
        reply = self.send(on_progress=lambda phase, chars: seen.append(phase))
        self.assertEqual((reply.text, seen), ("{}", ["thinking", "writing"]))

    def test_cancelling_while_waiting_returns_at_once(self):
        self.then(body={"choices": [{"message": {"content": "{}"}}]}, delay=3.0)
        cancelled = threading.Event()
        threading.Timer(0.1, cancelled.set).start()
        start = time.monotonic()
        self.assert_error("Cancelled.", lambda: self.send(cancelled=cancelled))
        self.assertLess(time.monotonic() - start, 2.0)

    def test_the_base_interface_needs_a_real_provider(self):
        base = llm.Provider()
        for call in (base.available, lambda: base.conversation("S", "D"), lambda: llm.Conversation().send("t")):
            with self.assertRaises(NotImplementedError):
                call()
        self.assertIsNone(base.warm("S", "D"))  # most providers cache without being asked
        self.assertIsNone(llm.Conversation().close())


class Jev(Loopback):
    def setUp(self):
        super().setUp()
        for p in (patch.object(jev, "ask", fakejev.REAL_ASK), patch.object(jev, "RETRY_WAIT", 0),
                  patch.dict(os.environ, {"TYPESAFE_URL": self.base + "/v1/systemone", "TYPESAFE_API_KEY": "ts-test"})):
            p.start()
            self.addCleanup(p.stop)

    def ask(self):
        return jev.ask({"s": 1}, {"q": {"type": "score"}}, 0.5)

    def assert_error(self, message):
        with self.assertRaises(jev.JevError) as e:
            self.ask()
        self.assertEqual(str(e.exception), message)

    def test_a_slow_jev_is_retried_then_given_up_on(self):
        for _ in range(jev.ATTEMPTS):
            self.then(body={"answers": {}}, delay=1.0)
        self.assert_error("Couldn't use Jev (TimeoutError)")
        self.assertEqual(len(Scripted.calls), jev.ATTEMPTS)

    def test_one_slow_answer_then_a_good_one(self):
        self.then(body={"answers": {}}, delay=1.0)
        self.then(body={"answers": {"q": {"type": "score", "score": 3}}, "model": "jev-x"})
        self.assertEqual(self.ask(), {"q": {"type": "score", "score": 3}, "_model": "jev-x"})

    def test_garbled_replies_are_not_retried(self):
        self.then(body=b"<html>")
        self.assert_error("Jev sent a reply OpenLemma couldn't read")
        self.assertEqual(len(Scripted.calls), 1)
        self.then(body={"answers": ["not", "a", "dict"]})
        self.assert_error("Jev sent a reply OpenLemma couldn't read")


if __name__ == "__main__":
    unittest.main()
