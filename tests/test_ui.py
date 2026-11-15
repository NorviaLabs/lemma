"""The app in a real browser: continuing or starting over a stopped build, on the build page and in the Library.

Each test sets up builds the way the app makes them (a build really stopped part way, its finished concepts saved),
serves them with the real server on a free port, and runs one flow of tests/ui.mjs in headless Chrome. The AI
provider and Jev are stand-ins, as everywhere in the tests.

It needs Node.js, the test packages (`npm ci`) and Chrome or Chromium, found on the PATH or named by
LEMMA_TEST_CHROME; without any of them, it's skipped. LEMMA_UI_COVERAGE=<folder> also saves the browser's coverage of
the app's modules, player.js and ui.js there, for c8.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fakejev  # noqa: F401  Jev is essential, so every search and build asks this stand-in
from lemma import generate, ingest, llm, server, store
from lemma.llm import ProviderError
from support import SOURCE, TESTER, call, reset_server, session_cookie, sign_in
from test_lemma import wait
from test_multisource import MultiSourceProvider
from test_saved_concepts import Stops, settle_threads

ROOT = Path(__file__).resolve().parent.parent
CHROMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def find_chrome() -> str | None:
    named = os.environ.get("LEMMA_TEST_CHROME")
    if named:
        return named if Path(named).exists() else None
    found = next((shutil.which(n) for n in CHROMES if shutil.which(n)), None)
    return found or (MAC_CHROME if Path(MAC_CHROME).exists() else None)


def why_skipped() -> str | None:
    if not shutil.which("node"):
        return "node is needed for the browser tests"
    if not (ROOT / "node_modules" / "puppeteer-core").is_dir():
        return "run `npm ci` for the browser tests"
    if not find_chrome():
        return "Chrome or Chromium is needed for the browser tests (or set LEMMA_TEST_CHROME)"
    return None


class Claude(MultiSourceProvider):
    id, name, model = "claude", "Claude", "claude-opus-5-5"


class OpenAI(MultiSourceProvider):
    """The learner's current provider and model in these tests, as the browser's saved settings name them."""
    id, name, model = "openai", "OpenAI", "gpt-6.1-sol"


class ClaudeStops(Stops):
    id, name, model = "claude", "Claude", "claude-opus-5-5"


class OpenAIStops(Stops):
    id, name, model = "openai", "OpenAI", "gpt-6.1-sol"


class StopsFirst(ClaudeStops):
    """Hangs on every concept, so the build stops before any is finished."""

    def reply(self, task, turn):
        if "Its id must be" in task:
            self.hanging.set()
            self.stopped.wait(10)
            raise ProviderError("The connection closed.")
        return super().reply(task, turn)


class Gate(OpenAI):
    """Builds every concept but the last, which waits until the build is cancelled. Used for requests that carry the
    test header X-Test-Gate, so one build can be running while a flow looks at it."""

    def conversation(self, system, document):
        conv = super().conversation(system, document)
        send = conv.send

        def gated(text, cancelled=None, on_progress=None):
            if 'Its id must be "why_regression"' in text and cancelled is not None:
                cancelled.wait(60)
                raise ProviderError("Stopped.")
            return send(text, cancelled, on_progress)
        conv.send = gated
        return conv


def current_provider(req):
    headers = req.headers
    return Gate() if headers.get("X-Test-Gate") else OpenAI()


CRED = {"provider": "openai", "keys": {"openai": "sk-test"}, "models": {"openai": "gpt-6.1-sol"}}


@unittest.skipIf(why_skipped(), why_skipped())
class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = patch.dict(os.environ, {"LEMMA_HOME": self.tmp.name})
        self.env.start()
        sign_in()
        self.patches = [
            patch.object(server.builds, "_first_readable", return_value=SimpleNamespace(title="Galton", url="https://example.org/galton", text=SOURCE)),
            patch.object(server.core, "_provider", side_effect=current_provider),
            # The connect step checks a key by listing its models, which would ask the real service.
            patch.object(llm.HTTPProvider, "models", return_value=[{"id": "gpt-6.1-sol", "name": "gpt-6.1-sol", "context": 400000}]),
        ]
        for p in self.patches:
            p.start()
        self.httpd = server.make_server(0, exact=True)
        self.httpd.handle_error = self.quiet_disconnects(self.httpd.handle_error)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @staticmethod
    def quiet_disconnects(handle_error):
        """The browser leaves pages with a poll still being answered; only those dropped connections go unreported."""
        def handle(request, address):
            if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
                handle_error(request, address)
        return handle

    def tearDown(self):
        for job in list(generate.JOBS.values()):
            job.cancelled.set()  # releases a build a failed flow left waiting
        self.httpd.shutdown()
        self.httpd.server_close()
        settle_threads()
        for p in self.patches:
            p.stop()
        reset_server()
        self.env.stop()
        self.tmp.cleanup()

    # ------------------------------------------------------------ builds, made as the app makes them

    def settled(self, rid):
        for _ in range(1000):
            record = call(server.api_request, rid)
            if record["status"] != "running":
                return record
            time.sleep(.01)
        self.fail("the build did not settle")

    def outlined(self, provider=Claude, sources=None):
        """A build at outline review."""
        with patch.object(server.core, "_provider", return_value=provider()):
            rid = call(server.api_request_create, body={"sources": sources or [{"url": "https://example.org/galton", "title": "Galton"}],
                                                        "topic": "Why do tall parents have shorter children?"})["id"]
            record = self.settled(rid)
        self.assertEqual(record["status"], "awaiting_outline", record.get("error"))
        return rid, record["outline"]

    def stopped(self, built_by=ClaudeStops, finished=2, sources=None):
        """A build whose outline was approved, stopped by a server restart after `finished` concepts."""
        rid, outline = self.outlined(sources=sources)
        provider = built_by("why_regression")
        with patch.object(server.core, "_provider", return_value=provider):
            call(server.api_request_outline, rid, body={"outline": outline})
        job = generate.JOBS[rid]
        self.assertTrue(provider.hanging.wait(10))
        for _ in range(1000):
            if len(store.BuiltConcepts(rid, TESTER).load()) == finished:
                break
            time.sleep(.01)
        time.sleep(.2)  # the last finished concept's step is saved just after the concept
        with server.builds._requests_lock:  # the server stops: its memory is gone, and its threads never write again
            generate.JOBS.pop(rid)
        job.cancelled.set()
        provider.stopped.set()
        wait(job)
        self.assertEqual(len(store.BuiltConcepts(rid, TESTER).load()), finished)
        return rid

    def run_flow(self, flow, ids, cred=CRED, width=None, extra=None):
        cookie = session_cookie().split("=", 1)
        cfg = {**(extra or {}), "flow": flow, "base": f"http://127.0.0.1:{self.httpd.server_address[1]}/", "cookie": {"name": cookie[0], "value": cookie[1]},
               "chrome": find_chrome(), "cred": cred, "ids": ids, "width": width, "coverage": os.environ.get("LEMMA_UI_COVERAGE")}
        done = subprocess.run(["node", "tests/ui.mjs", json.dumps(cfg)], cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(done.returncode, 0, f"\n{done.stdout}\n{done.stderr}")

    # ------------------------------------------------------------ flows

    def test_library_choice_then_continue_keeps_the_finished_concepts_and_credits_both_models(self):
        rid = self.stopped()
        self.run_flow("library-continue", {"build": rid})
        lesson, _ = store.load_lesson(rid, TESTER)
        self.assertEqual([m["name"] for m in lesson["made_with"]], ["Claude", "OpenAI"])

    def test_library_start_over_asks_before_deleting_the_finished_concepts(self):
        rid = self.stopped(built_by=OpenAIStops)
        self.run_flow("library-start-over", {"build": rid})
        self.assertFalse(store.BuiltConcepts(rid, TESTER).dir.exists())
        self.assertEqual(call(server.api_request, rid)["status"], "awaiting_outline")

    def test_build_page_of_an_errored_build_keeps_its_error_and_offers_the_choice(self):
        rid = self.stopped()
        record = store.load_request(rid, TESTER)
        record.update(status="error", error="The checks couldn't run just now, so the build stopped. Retry in a moment. (error 3f9a1c2e)")
        server.builds._stop_steps(record)
        store.save_request(record, TESTER)
        self.run_flow("build-page-start-over", {"build": rid})
        self.assertFalse(store.BuiltConcepts(rid, TESTER).dir.exists())

    def test_with_nothing_finished_start_over_doesnt_ask(self):
        rid = self.stopped(built_by=StopsFirst, finished=0)
        self.run_flow("nothing-finished", {"build": rid})

    def test_a_build_stopped_before_its_outline_was_approved_retries_as_before(self):
        rid, _ = self.outlined()
        record = store.load_request(rid, TESTER)
        record["status"] = "running"  # the server stopped while the outline was being made
        record["steps"] = [{"id": "outline", "label": "Reading your sources and proposing an outline", "state": "active", "detail": "Drafting"}]
        store.save_request(record, TESTER)
        generate.JOBS.pop(rid)
        self.run_flow("no-choice", {"build": rid})

    def test_without_a_provider_continue_goes_through_connecting_and_carries_on(self):
        rid = self.stopped()
        self.run_flow("connect-carries-the-choice", {"build": rid}, cred=None)
        self.assertEqual(call(server.api_request, rid)["status"], "done")

    def test_cancelling_while_learning_leads_to_the_choice(self):
        rid, _ = self.outlined(OpenAI)
        self.run_flow("cancel-while-learning", {"build": rid})
        self.assertEqual(call(server.api_request, rid)["resume"]["kept"], 2)

    def test_the_library_never_redraws_under_an_open_choice_but_catches_up_after(self):
        rid = self.stopped()
        running, _ = self.outlined(OpenAI)
        self.run_flow("library-refresh-under-choice", {"build": rid, "running": running})

    def test_a_retry_the_server_refuses_says_why_in_place(self):
        rid = self.stopped()
        refusal = "You already have lessons building. Wait for one to finish, or cancel it."
        with patch.object(server.builds, "_new_job", side_effect=server.ApiError(429, refusal)):
            self.run_flow("retry-refused", {"build": rid}, extra={"refusal": refusal, "expectErrors": ["status of 429 (Too Many Requests)"]})
        self.assertEqual(len(store.BuiltConcepts(rid, TESTER).load()), 2)  # nothing lost

    def test_the_credit_line_names_every_model_and_old_lessons_read_as_before(self):
        base = json.loads((ROOT / "lemma/examples/gallery/galton-1886.json").read_text())
        base.pop("example", None)
        ids = [c["id"] for c in base["concepts"]]
        a, b, c, d = ({"name": "Claude", "model": "claude-opus-5-5"}, {"name": "OpenAI", "model": "gpt-6.1-sol"},
                      {"name": "OpenCode Go", "model": "gpt-5.6-luna"}, {"name": "ChatGPT", "model": "gpt-6.1-sol"})
        lessons = {  # lesson id -> (what it records, the credit it should show)
            "old": ({"provider": b}, " Made with OpenAI (gpt-6.1-sol)."),
            "oldnomodel": ({"provider": {"name": "Hand-written example", "model": ""}}, " Made with Hand-written example."),
            "oldnone": ({}, ""),
            "one": ({"provider": b, "made_with": [dict(b, concepts=ids)]}, " Made with OpenAI (gpt-6.1-sol)."),
            "two": ({"provider": a, "made_with": [dict(a, concepts=ids[:2]), dict(b, concepts=ids[2:])]},
                    " Made with Claude (claude-opus-5-5) and OpenAI (gpt-6.1-sol)."),
            "three": ({"provider": a, "made_with": [dict(a, concepts=ids[:1]), dict(b, concepts=ids[1:2]), dict(c, concepts=ids[2:])]},
                      " Made with Claude (claude-opus-5-5), OpenAI (gpt-6.1-sol), and OpenCode Go (gpt-5.6-luna)."),
            "four": ({"provider": a, "made_with": [dict(a, concepts=ids[:1]), dict(b, concepts=ids[1:2]), dict(c, concepts=ids[2:]), dict(d, concepts=[])]},
                     " Made with Claude (claude-opus-5-5), OpenAI (gpt-6.1-sol), OpenCode Go (gpt-5.6-luna), and ChatGPT (gpt-6.1-sol)."),
            "dupes": ({"provider": a, "made_with": [dict(a, concepts=ids[:1]), dict(a, concepts=ids[1:])]}, " Made with Claude (claude-opus-5-5)."),
            "badlist": ({"provider": b, "made_with": "Claude"}, " Made with OpenAI (gpt-6.1-sol)."),
            "badentries": ({"provider": b, "made_with": [{"model": "x"}, None, {"name": ""}]}, " Made with OpenAI (gpt-6.1-sol)."),
        }
        for lid, (fields, _) in lessons.items():
            lesson = dict(base, id=lid)
            lesson.pop("provider", None)
            store.save_lesson({**lesson, **fields}, SOURCE, TESTER)
        self.run_flow("credit-lines", {}, extra={"expect": {lid: want for lid, (_, want) in lessons.items()}, "exported": "three"})

    def test_a_source_that_couldnt_be_read_is_named_and_starting_over_reads_it_again(self):
        blocked = {"https://blocked.example/b"}

        def read(urls):
            if urls[0] in blocked:
                raise ingest.IngestError("The site refused the download.")
            return SimpleNamespace(title=urls[0].split("/")[2], url=urls[0], text=SOURCE)
        with patch.object(server.builds, "_first_readable", side_effect=read):
            rid = self.stopped(sources=[{"url": "https://ok.example/a", "title": "Readable"}, {"url": "https://blocked.example/b", "title": "Blocked"}])
            blocked.clear()  # the site works again
            self.run_flow("unread-source", {"build": rid})
        sources = json.loads(store.load_request(rid, TESTER)["paper"]["text"])["lemma_sources"]
        self.assertEqual([s["id"] for s in sources], ["s1", "s2"])

    def test_on_a_phone_the_choice_fits(self):
        rid = self.stopped()
        self.run_flow("phone", {"build": rid}, width=390)


if __name__ == "__main__":
    unittest.main()
