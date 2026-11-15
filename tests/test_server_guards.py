"""The HTTP API's guards and the outline → build flow, as the browser meets them, plus a hosted server's shared caps.

No live model: a FakeProvider answers through the same request path a keyed provider would.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from support import SOURCE, Site, TESTER, act_as, call, reset_server, session_cookie, sign_in
from test_lemma import FakeConversation, FakeProvider
from lemma import auth, categorize, chatgpt, checks, generate, ingest, jev, metrics, search, server, store
from lemma.llm import DEFAULT_PROVIDER, ProviderError


def LocalServer():
    """A server on this computer, every request signed in as the tester."""
    return Site(cookie=session_cookie())


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
            with patch.object(server.http, "MAX_BODY", 64):
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

        with LocalServer() as site, patch.object(server.builds, "_first_readable", first):
            s, body = self.post(site, urls=[f"https://example.org/{i}" for i in range(8)])
        self.assertEqual((s, body["title"], body["url"]), (200, "Mirror", "https://example.org/4"))
        self.assertEqual(len(tried), 5)

    def test_only_the_latest_papers_are_kept_in_memory(self):
        with LocalServer() as site, patch.object(server.core, "make_provider", return_value=FakeProvider()):
            ids = [upload(site, SOURCE + f"\nCopy {i}.") for i in range(server.builds.KEEP_PAPERS + 1)]
            s, body, _ = site.req("POST", "/api/requests", {"sources": [{"paper_id": ids[0]}]})
            self.assertEqual((s, body["error"]), (404, "OpenLemma no longer has that source in memory. Please bring it again."))
            self.assertIn(ids[-1], server.builds.PAPERS)


class ProviderNotReady(unittest.TestCase):
    def test_a_provider_that_is_not_ready_starts_nothing(self):
        provider = FakeProvider()
        provider.available = lambda: (False, "Add your API key on your account page.")
        with LocalServer() as site, patch.object(server.core, "make_provider", return_value=provider):
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

        with LocalServer() as site, patch.object(server.core, "make_provider", return_value=Rejected()):
            s, body, _ = site.req("GET", "/api/models")
        self.assertEqual((s, body["error"]), (502, "The key was rejected."))

    def test_gallery_lessons_are_checked_once_and_may_be_cached_but_other_answers_are_not(self):
        checks.forget()  # nothing checked yet, in memory or on disk
        checked = []
        real = server.core.require_valid
        with LocalServer() as site, patch.object(server.core, "require_valid", side_effect=lambda l, s: checked.append(l["id"]) or real(l, s)):
            for _ in range(3):
                s, body, r = site.req("GET", "/api/gallery/wuhan-2020")
                self.assertEqual((s, r.getheader("Cache-Control")), (200, "public, max-age=300"))
            self.assertEqual(checked, ["gallery-wuhan-2020"])
            s, _, r = site.req("GET", "/api/gallery")
            self.assertEqual((s, r.getheader("Cache-Control")), (200, "public, max-age=300"))
            for path in ("/api/status", "/api/gallery/no-such-lesson"):
                self.assertEqual(site.req("GET", path)[2].getheader("Cache-Control"), "no-store")

    def test_chatgpt_sign_in_reports_when_openai_wont_start_it_and_sign_out_forgets_the_account(self):
        with LocalServer() as site:
            with patch.object(chatgpt, "_device_request", return_value=(503, {})):
                s, body, _ = site.req("POST", "/api/signin/chatgpt/login", {})
            self.assertEqual(s, 409)
            self.assertIn("OpenAI didn't start a sign-in (503)", body["error"])

            me = auth.upsert_user("google", "tester", "tester", "tester@example.com", "")["id"]  # the account behind site.cookie
            store.write_private(chatgpt._auth_file(me), json.dumps({"access": "a", "refresh": "r", "expires": time.time() + 3600, "account_id": "", "email": "me@example.com"}))
            self.assertEqual(site.req("GET", "/api/signin/chatgpt")[1]["email"], "me@example.com")
            other = session_cookie("someone-else")  # another account doesn't see this sign-in
            self.assertEqual(site.req("GET", "/api/signin/chatgpt", headers={"Cookie": other})[1]["signed_in"], False)
            self.assertEqual(site.req("GET", "/api/signin/chatgpt", headers={"Cookie": ""})[0], 401)  # nor does a visitor
            s, body, _ = site.req("POST", "/api/signin/chatgpt/logout", {})
            self.assertEqual((s, body["signed_in"], body["email"]), (200, False, ""))
            self.assertFalse(chatgpt._auth_file(me).exists())


class Searches(unittest.TestCase):
    def setUp(self):
        search._cache.clear()
        sign_in()
        self.provider = patch.object(server.core, "_provider", return_value=FakeProvider())
        self.provider.start()

    def tearDown(self):
        self.provider.stop()
        reset_server()

    def test_search_needs_a_connected_provider(self):
        with patch.object(server.core, "_provider", side_effect=server.ApiError(400, "Add your Claude key on your account page to build lessons.")), \
                patch.object(search, "search") as live:
            with self.assertRaises(server.ApiError) as e:
                call(server.api_search, body={"query": "photosynthesis"})
        self.assertEqual((e.exception.status, e.exception.message), (400, server.searches.SEARCH_NEEDS_PROVIDER))
        live.assert_not_called()

    def test_the_level_and_provider_reach_the_search(self):
        with patch.object(search, "search", return_value={"query": "q", "results": []}) as live:
            self.wait_done(call(server.api_search, body={"query": "photosynthesis", "level": "advanced"})["id"])
        query, level, provider, _, field = live.call_args.args
        self.assertEqual((query, level, provider.id, field), ("photosynthesis", "advanced", "fake", None))
        with self.assertRaises(server.ApiError) as e:
            call(server.api_search, body={"query": "photosynthesis", "level": "expert"})
        self.assertEqual(e.exception.status, 400)

    def test_a_field_the_learner_chose_reaches_the_search(self):
        with patch.object(search, "search", return_value={"query": "q", "results": []}) as live:
            self.wait_done(call(server.api_search, body={"query": "Mercury", "level": "beginner", "field": ["religion"]})["id"])
        self.assertEqual(live.call_args.args[4], categorize.chosen_field(["religion"]))
        for bad in (["astrology"], ["other"], [], ["chemistry", "chemistry"], ["chemistry", "religion", "law"], "chemistry"):
            with self.assertRaises(server.ApiError) as e:
                call(server.api_search, body={"query": "Mercury", "field": bad})
            self.assertEqual((e.exception.status, e.exception.message), (400, "Choose a field from the list."))

    def test_each_field_remembers_its_own_level(self):
        def found(field):
            return lambda query, level, provider, on_progress=None, chosen=None: {"query": query, "results": [], "field": chosen or field}
        ai, physics = categorize.chosen_field(["ai_ml"]), categorize.chosen_field(["physics_astronomy"])
        # A level the learner sets is saved for the field the search lands in.
        with patch.object(search, "search", side_effect=found(ai)):
            self.wait_done(call(server.api_search, body={"query": "attention in transformers", "level": "advanced"})["id"])
        self.assertEqual(store.settings(TESTER)["levels"], {"ai_ml": "advanced"})
        # Without one, a search uses the level saved for the field Jev places it in, else the last level used.
        with patch.object(search, "field_of", return_value=ai), patch.object(search, "search", side_effect=found(ai)) as live:
            self.wait_done(call(server.api_search, body={"query": "what is a token"})["id"])
        self.assertEqual(live.call_args.args[1], "advanced")
        with patch.object(search, "search", side_effect=found(physics)):
            self.wait_done(call(server.api_search, body={"query": "why is the sky blue", "level": "beginner"})["id"])
        with patch.object(search, "field_of", return_value=categorize.chosen_field(["chemistry"])), \
                patch.object(search, "search", side_effect=found(None)) as live:
            self.wait_done(call(server.api_search, body={"query": "what is an acid"})["id"])
        self.assertEqual(live.call_args.args[1], "beginner")
        self.assertEqual(store.settings(TESTER)["levels"], {"ai_ml": "advanced", "physics_astronomy": "beginner"})

    def wait_done(self, sid):
        for _ in range(500):
            record = call(server.api_search_status, sid)
            if record["done"]:
                return record
            time.sleep(0.01)
        self.fail("search did not finish")

    def test_a_failed_search_reports_why_without_crashing_the_server(self):
        with patch.object(search, "search", side_effect=search.SearchError("Every library was unreachable.")):
            failed = self.wait_done(call(server.api_search, body={"query": "photosynthesis"})["id"])
        self.assertEqual((failed["error"], failed["result"]), ("Every library was unreachable.", None))
        with patch.object(search, "search", side_effect=RuntimeError("boom")), patch("sys.stderr"):
            broken = self.wait_done(call(server.api_search, body={"query": "photosynthesis"})["id"])
        self.assertRegex(broken["error"], r"^The search failed unexpectedly \(RuntimeError, error [0-9a-f]{8}\)\.$")

    def test_without_jev_search_is_refused(self):
        with patch.object(jev, "available", return_value=False):
            with self.assertRaises(server.ApiError) as e:
                call(server.api_search, body={"query": "photosynthesis"})
        self.assertEqual((e.exception.status, e.exception.message), (422, jev.MISSING))

    def test_a_cached_search_answers_at_once(self):
        hit = {"query": "entropy", "results": []}
        with patch.object(search, "cached", return_value=hit), patch.object(search, "search") as live:
            self.assertEqual(call(server.api_search, body={"query": "entropy", "level": "beginner"}), {"done": True, "result": hit})
        live.assert_not_called()

    def test_a_site_out_of_builds_for_the_day_says_so_and_the_gallery_still_opens(self):
        with LocalServer() as site, patch.object(server.core, "make_provider", return_value=FakeProvider()), \
                patch.dict(os.environ, {"LEMMA_SITE_DAILY_BUILDS": "0"}):
            pid = upload(site, SOURCE)
            s, body, _ = site.req("POST", "/api/requests", {"sources": [{"paper_id": pid}]})
            self.assertEqual(s, 429, body)
            self.assertIn("for everyone", body["error"])
            self.assertEqual(site.req("GET", "/api/gallery")[0], 200)


class HostedCaps(unittest.TestCase):
    """Limits shared by everyone on a hosted server, and each account's own."""

    def setUp(self):
        search._cache.clear()
        self.provider = patch.object(server.core, "_provider", return_value=FakeProvider())
        self.provider.start()

    def tearDown(self):
        self.provider.stop()
        reset_server()
        generate.JOBS.clear()

    @staticmethod
    def as_user(uid):
        act_as({"id": uid, "email": f"{uid}@example.com"})

    def status_of(self, fn, *args, **kw):
        """How calling API handler `fn` (as call() does) ends: (status, message), 200 when it's answered."""
        try:
            call(fn, *args, **kw)
        except server.ApiError as e:
            return e.status, e.message
        return 200, ""

    def test_reading_sources_has_a_daily_allowance_per_account(self):
        # Each link or file read fetches or parses on the server, so it is capped like searches and builds.
        text = "Regression to the mean, in plain words. " * 40
        body = {"filename": "notes.txt", "data": base64.b64encode(text.encode()).decode()}
        with patch.dict(os.environ, {"LEMMA_DAILY_READS": "2"}):
            self.as_user("quota-a")
            got = [self.status_of(server.api_papers, body=body) for _ in range(3)]
            self.assertEqual([s for s, _ in got], [200, 200, 429], got)
            self.assertIn("today's 2", self.status_of(server.api_papers, body=body)[1])
            self.as_user("quota-b")
            self.assertEqual(self.status_of(server.api_papers, body=body)[0], 200)  # another account has its own

    def test_the_server_wide_build_cap_turns_away_a_new_account(self):
        with patch.object(server.builds, "MAX_RUNNING", 2):
            for uid in ("cap-a", "cap-b"):
                server.builds._new_job(uid, "build")
            with self.assertRaises(server.ApiError) as e:
                server.builds._new_job("cap-c", "build")
            status, message = e.exception.status, e.exception.message
        self.assertEqual(status, 503)
        self.assertIn("busy building other people's lessons", message)

    def test_the_daily_allowance_of_outlines_and_builds(self):
        with patch.dict("os.environ", {"LEMMA_DAILY_BUILDS": "1"}):
            job = server.builds._new_job("quota-1", "outline")
            job.status = "done"
            with self.assertRaises(server.ApiError) as e:
                server.builds._new_job("quota-1", "build")
            status, message = e.exception.status, e.exception.message
        self.assertEqual((status, message), (429, "You've used today's 1 outlines and builds. They reset at midnight UTC."))

    def test_reading_slots_are_shared_by_everyone(self):
        release, started, results = threading.Event(), threading.Semaphore(0), []

        def slow(url, **kw):
            started.release()
            release.wait(5)
            return ingest.Paper(text="x" * 2000, title="T", kind="html", url=url)

        def read(uid):  # in its own thread, so the account is named for this call only
            results.append(self.status_of(server.api_papers, user={"id": uid, "email": f"{uid}@example.com"}, body={"url": "https://example.org/a"})[0])

        with patch.object(ingest, "from_url", slow), patch.object(server.builds, "READING", 1):
            first = threading.Thread(target=read, args=("reader-a",))
            first.start()
            started.acquire(timeout=5)
            self.as_user("reader-b")
            status, message = self.status_of(server.api_papers, body={"url": "https://example.org/b"})
            release.set()
            first.join()
        self.assertEqual((status, results), (503, [200]))
        self.assertIn("busy reading other people's sources", message)
        self.assertEqual(server.builds._reading, {})  # every slot is given back

    def test_each_account_has_a_few_searches_running_at_once(self):
        release = threading.Event()

        def slow(query, level, provider, on_progress=None, field=None):
            release.wait(5)
            return {"query": query, "results": []}

        with patch.object(search, "search", side_effect=slow):
            self.as_user("searcher")
            running = [call(server.api_search, body={"query": f"topic number {i}"})["id"] for i in range(server.searches.SEARCHES_EACH)]
            status, message = self.status_of(server.api_search, body={"query": "one more topic"})
            self.as_user("someone-else")
            self.assertEqual(self.status_of(server.api_search_status, running[0])[0], 404)  # not theirs to see
            self.assertEqual(self.status_of(server.api_search, body={"query": "their own topic"})[0], 200)
            release.set()
        self.assertEqual((status, message), (429, "Several searches are still running. Wait a moment and try again."))

    def test_finished_searches_are_forgotten_after_ten_minutes(self):
        self.as_user("forgetful")
        with patch.object(search, "search", return_value={"query": "q", "results": []}):
            sid = call(server.api_search, body={"query": "old topic"})["id"]
            for _ in range(500):
                if call(server.api_search_status, sid)["done"]:
                    break
                time.sleep(0.01)
            later = SimpleNamespace(time=lambda: time.time() + 601)
            with patch.object(server.searches, "time", later):
                call(server.api_search, body={"query": "new topic"})
        self.assertEqual(self.status_of(server.api_search_status, sid)[0], 404)


class Requests(unittest.TestCase):
    """Durable builds: the requests a stopped, running or finished build refuses."""

    def setUp(self):
        self.provider = patch.object(server.core, "_provider", return_value=FakeProvider())
        self.provider.start()
        sign_in()

    def tearDown(self):
        self.provider.stop()
        generate.JOBS.clear()
        reset_server()

    def refused(self, fn, *args, **kw):
        with self.assertRaises(server.ApiError) as e:
            call(fn, *args, **kw)
        return e.exception.status, e.exception.message

    def saved(self, status, **extra):
        record = {"id": uuid.uuid4().hex[:12], "title": "T", "status": status,
                  "request": {"audience": ""}, "paper": {"text": SOURCE, "title": "Galton", "url": ""}, **extra}
        store.save_request(record, TESTER)
        return record["id"]

    def test_sources_must_be_objects(self):
        self.assertEqual(self.refused(server.api_request_create, body={"sources": ["https://example.org"]}), (400, "Invalid source."))

    def test_an_unknown_build_is_not_found(self):
        self.assertEqual(self.refused(server.api_request, "0000000000ff"), (404, "That lesson build wasn't found."))

    def test_only_a_stopped_build_can_be_retried_and_only_a_waiting_one_reviewed(self):
        rid = self.saved("done")
        self.assertEqual(self.refused(server.api_request_retry, rid), (409, "Only a stopped build can be retried."))
        self.assertEqual(self.refused(server.api_request_outline, rid, body={"outline": {}}), (409, "This build is not waiting for outline review."))
        store.request_path(rid, TESTER).unlink()

    def test_a_reviewed_outline_must_still_be_valid(self):
        rid = self.saved("awaiting_outline")
        status, message = self.refused(server.api_request_outline, rid, body={"outline": {"title": "Only a title"}})
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
        call(server.api_request_cancel, rid)
        self.assertTrue(job.cancelled.is_set())
        self.assertEqual(job.status, "cancelled")
        store.request_path(rid, TESTER).unlink()



class Routing(unittest.TestCase):
    """Each API handler is registered by its @route and called with an explicit Request; nothing about a request is
    kept in module or thread state."""

    def test_each_handler_has_one_route_and_no_two_routes_clash(self):
        fns = [r.fn for r in server.ROUTES]
        self.assertEqual(len(fns), len(set(fns)))
        self.assertEqual(len({(r.method, r.pattern) for r in server.ROUTES}), len(server.ROUTES))
        self.assertTrue(all(r.fn.__name__.startswith("api_") for r in server.ROUTES))

    def test_a_path_without_a_parameter_wins_over_a_pattern(self):
        self.assertEqual(server.find_route("GET", "/api/gallery/community"), (next(r for r in server.ROUTES if r.fn is server.api_gallery_community), ()))
        r, args = server.find_route("GET", "/api/gallery/galton-1886")
        self.assertEqual((r.fn, args, r.shared), (server.api_gallery_lesson, ("galton-1886",), True))

    def test_a_pattern_passes_what_it_captured(self):
        r, args = server.find_route("POST", "/api/requests/abcdefabcdef/retry")
        self.assertEqual((r.fn, args), (server.api_request_retry, ("abcdefabcdef",)))
        self.assertIsNone(server.find_route("POST", "/api/requests/ABCDEF/retry"))
        self.assertIsNone(server.find_route("DELETE", "/api/status"), "the method is part of the route")
        self.assertIsNone(server.find_route("GET", "/api/status/"))

    def test_no_request_is_kept_outside_the_call(self):
        self.assertFalse(hasattr(server, "REQUEST"))

    def test_the_request_says_who_is_asking(self):
        self.assertEqual(server.Request(query={"status": ["done", "new"]}).param("status"), "done")
        self.assertEqual(server.Request().param("status", "waiting"), "waiting")
        with self.assertRaises(server.ApiError) as e:
            server.Request().owner()
        self.assertEqual(e.exception.status, 401)
        self.assertEqual(server.Request(user={"id": "u1", "email": "a@example.com"}).owner(), "u1")
        with patch.dict(os.environ, {"LEMMA_ADMINS": "Boss@Example.com"}):
            self.assertTrue(server.Request(user={"id": "b", "email": "boss@example.com"}).is_admin())
            with self.assertRaises(server.ApiError) as e:
                server.Request(user={"id": "u1", "email": "a@example.com"}).admin()
            self.assertEqual(e.exception.status, 404)
        self.assertEqual(server.Request(headers={"X-Lemma-Key": "k"}).credential(), (DEFAULT_PROVIDER, "k", ""))


if __name__ == "__main__":
    unittest.main()
