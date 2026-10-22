"""The HTTP API's guards and the outline → build flow, as the browser meets them, plus a hosted server's shared caps.

No live model: a FakeProvider answers through the same request path a keyed provider would.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import socket
import threading
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import hosting  # noqa: F401  a temporary LEMMA_HOME and the Jev stand-in
from test_lemma import SOURCE, TESTER, FakeConversation, FakeProvider, reset_server, session_cookie, sign_in
from lemma import chatgpt, generate, ingest, jev, metrics, search, server, store
from lemma.llm import ProviderError


class LocalServer:
    def __enter__(self):
        self.httpd = server.make_server(0, exact=True)
        self.port = self.httpd.server_address[1]
        self.cookie = session_cookie()
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def req(self, method, path, body=None, headers=None):
        """(status, decoded JSON or raw bytes, response). A dict or list body is sent as JSON, bytes as they are."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"localhost:{self.port}", "Cookie": self.cookie}
        h.update(headers or {})
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        c.request(method, path, data, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw), r
        except ValueError:
            return r.status, raw, r


def upload(site, text=SOURCE, name="galton.txt"):
    s, body, _ = site.req("POST", "/api/papers", {"filename": name, "content_type": "text/plain", "data": base64.b64encode(text.encode()).decode()})
    assert s == 200, body
    return body["paper_id"]


class RequestBodies(unittest.TestCase):
    def test_malformed_or_oversized_bodies_are_refused_with_a_plain_message(self):
        with LocalServer() as site:
            for raw, message in ((b"{not json", "The request wasn't valid JSON."), (b"[1, 2]", "The request must be a JSON object."), (b'"text"', "The request must be a JSON object.")):
                s, body, _ = site.req("POST", "/api/lessons", raw)
                self.assertEqual((s, body["error"]), (400, message))
            s, body, _ = site.req("POST", "/api/requests/0123456789ab/outline", b"{oops")  # routes with an id read the body too
            self.assertEqual((s, body["error"]), (400, "The request wasn't valid JSON."))
            with patch.object(server, "MAX_BODY", 64):
                s, body, _ = site.req("POST", "/api/lessons", json.dumps({"lesson": {"id": "x" * 100}}).encode())
            self.assertEqual((s, body["error"]), (413, "That upload is too large."))

    def test_an_empty_post_is_an_empty_request(self):
        with LocalServer() as site:
            s, body, _ = site.req("POST", "/api/papers")
            self.assertEqual((s, body["error"]), (400, "Paste a link or choose a file."))

    def test_unknown_pages_and_files_are_not_found_and_head_sends_no_body(self):
        with LocalServer() as site:
            for path in ("/nope", "/static/no-such-file.js", "/api/nothing-here"):
                self.assertEqual(site.req("GET", path)[0], 404, path)
            s, body, r = site.req("HEAD", "/")
            self.assertEqual((s, body), (200, b""))
            self.assertGreater(int(r.getheader("Content-Length")), 100)


class Uploads(unittest.TestCase):
    def post(self, site, **fields):
        s, body, _ = site.req("POST", "/api/papers", fields)
        return s, body

    def test_an_undecodable_upload_is_refused(self):
        with LocalServer() as site:
            s, body = self.post(site, data="abc", filename="paper.pdf")
            self.assertEqual((s, body["error"]), (400, "The uploaded file couldn't be decoded."))

    def test_size_limits_depend_on_the_kind_of_file(self):
        with LocalServer() as site, patch.object(ingest, "MAX_BYTES", 4000), patch.object(ingest, "MAX_PAGE_BYTES", 1000):
            pdf = base64.b64encode(b"%PDF-1.4\n" + b"0" * 5000).decode()
            s, body = self.post(site, data=pdf, filename="huge.pdf")
            self.assertEqual((s, body["error"]), (413, "That file is larger than 40 MB."))
            # A PDF between the two limits is read (and this one, being junk, is unreadable); a web page that big is not.
            junk_pdf = base64.b64encode(b"%PDF-1.4\n" + b"0" * 2000).decode()
            s, body = self.post(site, data=junk_pdf, filename="paper.pdf", content_type="application/pdf")
            self.assertEqual(s, 422, body)
            page = base64.b64encode(b"<html>" + b"x" * 2000).decode()
            s, body = self.post(site, data=page, filename="page.html")
            self.assertEqual((s, body["error"]), (413, "That file is larger than 10 MB. Only PDFs can be up to 40 MB."))

    def test_a_link_lemma_will_not_fetch_reads_as_unprocessable(self):
        with LocalServer() as site:
            s, body = self.post(site, url="http://127.0.0.1:9/private")
            self.assertEqual((s, body["error"]), (422, ingest.NOT_PUBLIC))

    def test_a_list_of_links_tries_at_most_five(self):
        tried = []

        def first(urls):
            tried.extend(urls)
            return ingest.Paper(text="t" * 5000, title="Mirror", kind="html", url=urls[-1])

        with LocalServer() as site, patch.object(server, "_first_readable", first):
            s, body = self.post(site, urls=[f"https://example.org/{i}" for i in range(8)])
        self.assertEqual((s, body["title"], body["url"]), (200, "Mirror", "https://example.org/4"))
        self.assertEqual(len(tried), 5)

    def test_only_the_latest_papers_are_kept_in_memory(self):
        with LocalServer() as site, patch.object(server, "make_provider", return_value=FakeProvider()):
            ids = [upload(site, SOURCE + f"\nCopy {i}.") for i in range(server.KEEP_PAPERS + 1)]
            s, body, _ = site.req("POST", "/api/requests", {"sources": [{"paper_id": ids[0]}]})
            self.assertEqual((s, body["error"]), (404, "OpenLemma no longer has that source in memory. Please bring it again."))
            self.assertIn(ids[-1], server.PAPERS)


class ProviderNotReady(unittest.TestCase):
    def test_a_provider_that_is_not_ready_starts_nothing(self):
        provider = FakeProvider()
        provider.available = lambda: (False, "Add your API key on your account page.")
        with LocalServer() as site, patch.object(server, "make_provider", return_value=provider):
            pid = upload(site)
            before = set(generate.JOBS)
            s, body, _ = site.req("POST", "/api/requests", {"sources": [{"paper_id": pid}]})
            self.assertEqual((s, body["error"]), (400, "Add your API key on your account page."))
            self.assertEqual(set(generate.JOBS), before)
            self.assertEqual(provider.calls, 0)


class LocalOnlyEndpoints(unittest.TestCase):
    def test_a_rejected_key_reads_as_a_bad_gateway(self):
        class Rejected(FakeProvider):
            def models(self):
                raise ProviderError("The key was rejected.")

        with LocalServer() as site, patch.object(server, "make_provider", return_value=Rejected()):
            s, body, _ = site.req("GET", "/api/models")
        self.assertEqual((s, body["error"]), (502, "The key was rejected."))

    def test_chatgpt_sign_in_reports_a_busy_port_and_sign_out_forgets_the_account(self):
        chatgpt._stop_listening()  # a listener left by an earlier sign-in would be closed and its port reused
        self.addCleanup(chatgpt._stop_listening)
        with LocalServer() as site:
            with socket.socket() as busy:
                busy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # an earlier test's closed callback may linger in TIME_WAIT
                try:
                    busy.bind(("127.0.0.1", chatgpt.CALLBACK_PORT))
                    busy.listen()
                except OSError:
                    pass  # another program is listening there, which makes it just as busy
                s, body, _ = site.req("POST", "/api/chatgpt/login", {})
            self.assertEqual(s, 409)
            self.assertIn(f"Port {chatgpt.CALLBACK_PORT} is busy", body["error"])

            store.write_private(chatgpt._auth_file(), json.dumps({"access": "a", "refresh": "r", "expires": time.time() + 3600, "account_id": "", "email": "me@example.com"}))
            self.assertEqual(site.req("GET", "/api/chatgpt")[1]["email"], "me@example.com")
            s, body, _ = site.req("POST", "/api/chatgpt/logout", {})
            self.assertEqual((s, body["signed_in"], body["email"]), (200, False, ""))
            self.assertFalse(chatgpt._auth_file().exists())


class Searches(unittest.TestCase):
    def setUp(self):
        search._cache.clear()
        sign_in()

    def tearDown(self):
        reset_server()

    def wait_done(self, sid):
        for _ in range(500):
            record = server.api_search_status(sid)
            if record["done"]:
                return record
            time.sleep(0.01)
        self.fail("search did not finish")

    def test_a_failed_search_reports_why_without_crashing_the_server(self):
        with patch.object(search, "search", side_effect=search.SearchError("Every library was unreachable.")):
            failed = self.wait_done(server.api_search({"query": "photosynthesis"})["id"])
        self.assertEqual((failed["error"], failed["result"]), ("Every library was unreachable.", None))
        with patch.object(search, "search", side_effect=RuntimeError("boom")), patch("sys.stderr"):
            broken = self.wait_done(server.api_search({"query": "photosynthesis"})["id"])
        self.assertRegex(broken["error"], r"^The search failed unexpectedly \(RuntimeError, error [0-9a-f]{8}\)\.$")

    def test_without_jev_search_is_refused(self):
        with patch.object(jev, "available", return_value=False):
            with self.assertRaises(server.ApiError) as e:
                server.api_search({"query": "photosynthesis"})
        self.assertEqual((e.exception.status, e.exception.message), (422, jev.MISSING))

    def test_a_cached_search_answers_at_once(self):
        hit = {"query": "entropy", "results": []}
        with patch.object(search, "cached", return_value=hit), patch.object(search, "search") as live:
            self.assertEqual(server.api_search({"query": "entropy"}), {"done": True, "result": hit})
        live.assert_not_called()


class HostedCaps(unittest.TestCase):
    """Limits shared by everyone on a hosted server, and each account's own."""

    def setUp(self):
        search._cache.clear()

    def tearDown(self):
        reset_server()
        server.REQUEST.user = None
        generate.JOBS.clear()

    @staticmethod
    def as_user(uid):
        server.REQUEST.user = {"id": uid, "email": f"{uid}@example.com"}

    def status_of(self, call, *args):
        try:
            call(*args)
        except server.ApiError as e:
            return e.status, e.message
        return 200, ""

    def test_reading_sources_has_a_daily_allowance_per_account(self):
        # Each link or file read fetches or parses on the server, so it is capped like searches and builds.
        text = "Regression to the mean, in plain words. " * 40
        body = {"filename": "notes.txt", "data": base64.b64encode(text.encode()).decode()}
        with patch.dict(os.environ, {"LEMMA_DAILY_READS": "2"}):
            self.as_user("quota-a")
            got = [self.status_of(server.api_papers, body) for _ in range(3)]
            self.assertEqual([s for s, _ in got], [200, 200, 429], got)
            self.assertIn("today's 2", self.status_of(server.api_papers, body)[1])
            self.as_user("quota-b")
            self.assertEqual(self.status_of(server.api_papers, body)[0], 200)  # another account has its own

    def test_the_server_wide_build_cap_turns_away_a_new_account(self):
        with patch.object(server, "MAX_RUNNING", 2):
            for uid in ("cap-a", "cap-b"):
                self.as_user(uid)
                server._new_job("build")
            self.as_user("cap-c")
            status, message = self.status_of(server._new_job, "build")
        self.assertEqual(status, 503)
        self.assertIn("busy building other people's lessons", message)

    def test_the_daily_allowance_of_outlines_and_builds(self):
        with patch.dict("os.environ", {"LEMMA_DAILY_BUILDS": "1"}):
            self.as_user("quota-1")
            job = server._new_job("outline")
            job.status = "done"
            status, message = self.status_of(server._new_job, "build")
        self.assertEqual((status, message), (429, "You've used today's 1 outlines and builds. They reset at midnight UTC."))

    def test_reading_slots_are_shared_by_everyone(self):
        release, started, results = threading.Event(), threading.Semaphore(0), []

        def slow(url, **kw):
            started.release()
            release.wait(5)
            return ingest.Paper(text="x" * 2000, title="T", kind="html", url=url)

        def read(uid):
            self.as_user(uid)
            results.append(self.status_of(server.api_papers, {"url": "https://example.org/a"})[0])

        with patch.object(ingest, "from_url", slow), patch.object(server, "READING", 1):
            first = threading.Thread(target=read, args=("reader-a",))
            first.start()
            started.acquire(timeout=5)
            self.as_user("reader-b")
            status, message = self.status_of(server.api_papers, {"url": "https://example.org/b"})
            release.set()
            first.join()
        self.assertEqual((status, results), (503, [200]))
        self.assertIn("busy reading other people's sources", message)
        self.assertEqual(server._reading, {})  # every slot is given back

    def test_each_account_has_a_few_searches_running_at_once(self):
        release = threading.Event()

        def slow(query, on_progress=None):
            release.wait(5)
            return {"query": query, "results": []}

        with patch.object(search, "search", side_effect=slow):
            self.as_user("searcher")
            running = [server.api_search({"query": f"topic number {i}"})["id"] for i in range(server.SEARCHES_EACH)]
            status, message = self.status_of(server.api_search, {"query": "one more topic"})
            self.as_user("someone-else")
            self.assertEqual(self.status_of(server.api_search_status, running[0])[0], 404)  # not theirs to see
            self.assertEqual(self.status_of(server.api_search, {"query": "their own topic"})[0], 200)
            release.set()
        self.assertEqual((status, message), (429, "Several searches are still running. Wait a moment and try again."))

    def test_finished_searches_are_forgotten_after_ten_minutes(self):
        self.as_user("forgetful")
        with patch.object(search, "search", return_value={"query": "q", "results": []}):
            sid = server.api_search({"query": "old topic"})["id"]
            for _ in range(500):
                if server.api_search_status(sid)["done"]:
                    break
                time.sleep(0.01)
            later = SimpleNamespace(time=lambda: time.time() + 601)
            with patch.object(server, "time", later):
                server.api_search({"query": "new topic"})
        self.assertEqual(self.status_of(server.api_search_status, sid)[0], 404)


class Requests(unittest.TestCase):
    """Durable builds: the requests a stopped, running or finished build refuses."""

    def setUp(self):
        self.provider = patch.object(server, "_provider", return_value=FakeProvider())
        self.provider.start()
        sign_in()

    def tearDown(self):
        self.provider.stop()
        generate.JOBS.clear()
        reset_server()

    def refused(self, call, *args):
        with self.assertRaises(server.ApiError) as e:
            call(*args)
        return e.exception.status, e.exception.message

    def saved(self, status, **extra):
        record = {"id": uuid.uuid4().hex[:12], "title": "T", "status": status,
                  "request": {"audience": ""}, "paper": {"text": SOURCE, "title": "Galton", "url": ""}, **extra}
        store.save_request(record, TESTER)
        return record["id"]

    def test_sources_must_be_objects(self):
        self.assertEqual(self.refused(server.api_request_create, {"sources": ["https://example.org"]}), (400, "Invalid source."))

    def test_an_unknown_build_is_not_found(self):
        self.assertEqual(self.refused(server.api_request, "0000000000ff"), (404, "That lesson build wasn't found."))

    def test_only_a_stopped_build_can_be_retried_and_only_a_waiting_one_reviewed(self):
        rid = self.saved("done")
        self.assertEqual(self.refused(server.api_request_retry, rid), (409, "Only a stopped build can be retried."))
        server.REQUEST.body = {"outline": {}}
        self.assertEqual(self.refused(server.api_request_outline, rid), (409, "This build is not waiting for outline review."))
        store.request_path(rid, TESTER).unlink()

    def test_a_reviewed_outline_must_still_be_valid(self):
        rid = self.saved("awaiting_outline")
        server.REQUEST.body = {"outline": {"title": "Only a title"}}
        status, message = self.refused(server.api_request_outline, rid)
        self.assertEqual(status, 400)
        self.assertTrue(message.startswith("The outline isn't valid: "))
        self.assertEqual(store.load_request(rid, TESTER)["status"], "awaiting_outline")
        store.request_path(rid, TESTER).unlink()

    def test_a_running_build_must_be_cancelled_before_it_is_deleted(self):
        rid = self.saved("running")
        job = generate.Job("request")
        job.id, job.owner = rid, TESTER
        generate.JOBS[rid] = job
        self.assertEqual(self.refused(server.api_request_delete, rid), (409, "Cancel the build before deleting it."))
        self.assertTrue(store.request_path(rid, TESTER).exists())
        job.status = "awaiting_outline"
        server.api_request_cancel(rid)
        self.assertTrue(job.cancelled.is_set())
        self.assertEqual(job.status, "cancelled")
        store.request_path(rid, TESTER).unlink()


if __name__ == "__main__":
    unittest.main()
