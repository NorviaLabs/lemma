"""OpenLemma behaves the same on your own computer as hosted for others, except for the ChatGPT subscription.

Only a server bound to this computer offers the ChatGPT subscription. Nothing else may differ, sign-in included
(Google OAuth both ways). Two checks hold that in place:

* the structure: the switch for it, ``server.ON_THIS_COMPUTER``, is read only where that offer is made and where
  the server binds, and the old mode switches are gone;
* the behaviour: the same requests to a server on this computer and to one on a public address get the same
  answers, apart from the ChatGPT endpoints.
"""

from __future__ import annotations

import ast
import http.client
import json
import os
import re
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from test_lemma import SOURCE, reset_server, session_cookie
from lemma import server

ROOT = Path(__file__).resolve().parent.parent / "lemma"
SWITCHES = {"ON_THIS_COMPUTER"}
# Where the switch may be read: the ChatGPT offer itself, and binding (address, port, browser, live reload).
ALLOWED = {("server.py", "providers"), ("server.py", "_chatgpt_only"), ("server.py", "make_server"), ("__main__.py", "main")}


class Structure(unittest.TestCase):
    def reads(self):
        """(file, enclosing function, line) for every use of the switch that isn't its own definition."""
        found = []
        for path in ROOT.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in [None, *[n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]]:
                body = tree.body if fn is None else fn.body
                for stmt in body:
                    if fn is None and isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        continue
                    for node in ast.walk(stmt):
                        name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
                        if name in SWITCHES and not (fn is None and isinstance(getattr(node, "ctx", None), ast.Store)):
                            found.append((path.name, fn.name if fn else "<module>", node.lineno))
        return found

    def test_the_switch_is_read_only_where_this_computer_offers_differ(self):
        stray = [r for r in self.reads() if (r[0], r[1]) not in ALLOWED]
        self.assertEqual(stray, [], "only the offers that need a shared machine may depend on where OpenLemma runs")

    def test_the_old_mode_switches_are_gone(self):
        python = "\n".join(p.read_text(encoding="utf-8") for p in ROOT.glob("*.py"))
        browser = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "static").glob("*.js"))
        self.assertIsNone(re.search(r"\bHOSTED\b", python))
        self.assertIsNone(re.search(r"(?<!ON_)THIS_COMPUTER|\"computer\"", python), "sign-in is the same everywhere")
        self.assertIsNone(re.search(r"\bENABLED\b", (ROOT / "metrics.py").read_text(encoding="utf-8")))
        self.assertIsNone(re.search(r"\.hosted\b", browser), "the browser must not behave differently when hosted")


class Behaviour(unittest.TestCase):
    """The same requests, signed out and signed in, to a server on this computer and to one on a public address."""

    SITE = "tools.example.com"

    def start(self, public):
        env = {"LEMMA_PUBLIC_URL": f"http://{self.SITE}" if public else ""}
        with patch.dict(os.environ, env):
            httpd = server.make_server(0, host="0.0.0.0" if public else "127.0.0.1", allowed_hosts=(self.SITE,) if public else ())
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        return httpd.server_address[1], self.SITE if public else f"localhost:{httpd.server_address[1]}", env

    def script(self, public, cookie):
        port, host, env = self.start(public)
        upload = {"filename": "notes.txt", "data": __import__("base64").b64encode(SOURCE.encode()).decode()}
        calls = [
            ("GET", "/api/status", None), ("GET", "/api/example", None), ("GET", "/api/gallery", None),
            ("GET", "/api/lessons", None), ("GET", "/api/requests", None), ("GET", "/api/stats", None),
            ("POST", "/api/event", {"name": "lesson_open"}), ("POST", "/api/papers", upload),
            ("POST", "/api/requests", {"sources": []}), ("GET", "/api/lessons/nope", None),
            ("GET", "/api/chatgpt", None), ("GET", "/api/claude-code", None), ("GET", "/", None), ("GET", "/privacy", None),
        ]
        out = {}
        with patch.dict(os.environ, env):
            for method, path, body in calls:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                headers = {"Host": host, "Origin": f"http://{host}", "Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})}
                c.request(method, path, json.dumps(body) if body is not None else None, headers)
                r = c.getresponse()
                raw = r.read()
                c.close()
                try:
                    data = json.loads(raw)
                except ValueError:
                    data = None
                shape = sorted(data) if isinstance(data, dict) else type(data).__name__
                if path == "/api/status":
                    shape = {k: v for k, v in data.items() if k not in ("providers", "sign_in", "provider")}
                    shape["user"] = bool(shape["user"])
                kept = ("Content-Security-Policy", "Strict-Transport-Security", "X-Frame-Options", "Referrer-Policy", "Cache-Control")
                out[(method, path)] = (r.status, shape, {k: r.getheader(k) for k in kept})
        return out

    def test_the_same_requests_get_the_same_answers_apart_from_chatgpt(self):
        try:
            for who in ("signed out", "signed in"):
                with self.subTest(who=who):
                    cookie = session_cookie() if who == "signed in" else ""
                    here, public = self.script(False, cookie), self.script(True, cookie)
                    offers = {("GET", "/api/chatgpt")}
                    differ = sorted(k for k in here if here[k] != public[k])
                    self.assertTrue(set(differ) <= offers, [(k, here[k], public[k]) for k in differ if k not in offers])
                    self.assertEqual(public[("GET", "/api/chatgpt")][0], 404)  # the ChatGPT subscription needs this computer
        finally:
            reset_server()


if __name__ == "__main__":
    unittest.main()
