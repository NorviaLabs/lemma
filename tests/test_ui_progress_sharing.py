"""Continue where you left off, and sharing a lesson, in a real browser (flows in tests/ui.mjs).

Ada has a saved lesson (Galton's). Grace reads what Ada shares; an admin reviews the gallery. Each test prepares what
its flow needs through the server's own functions, runs one flow in headless Chrome, then checks what the server kept.

It needs Node.js, the test packages (`npm ci`) and Chrome or Chromium, found on the PATH or named by
LEMMA_TEST_CHROME; without any of them, it's skipped.
"""
import copy
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import fakejev  # noqa: F401  Jev is essential, so every search and build asks this stand-in
from lemma import auth, checks, server, store
from support import EXAMPLE, SOURCE, account, call_as, reset_server, saved_lesson
from test_ui import ROOT, find_chrome, why_skipped

LESSON_ID = "a1b2c3d4e5f6"
FREE_ID = "b1b2c3d4e5f6"



PEOPLE = {"ada": "Ada Lovelace", "grace": "Grace Hopper", "admin": "Admin"}


@unittest.skipIf(why_skipped(), why_skipped())
class ProgressAndSharingInTheBrowser(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = patch.dict(os.environ, {"LEMMA_HOME": self.tmp.name, "LEMMA_ADMINS": "admin@example.com"})
        self.env.start()
        self.users, self.cookies = {}, {}
        for name, full in PEOPLE.items():
            who = account(name, full)
            self.users[name] = who.profile
            self.cookies[name] = {"name": auth.SESSION_COOKIE, "value": who.token}
        self.title = saved_lesson(self.users["ada"]["id"], LESSON_ID)["title"]
        # A lesson with a concept taught without a model (its quotes are its source here, so it passes its checks)
        free = saved_lesson(self.users["ada"]["id"], FREE_ID, json.loads((ROOT / "lemma/examples/gallery/loss-aversion.json").read_text()), source=None)
        self.free = {"free": FREE_ID, "freeTitle": free["title"], "freeIndex": next(i for i, c in enumerate(free["concepts"]) if not c.get("model"))}
        self.httpd = server.make_server(0, exact=True)
        self.httpd.handle_error = self.quiet_disconnects(self.httpd.handle_error)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @staticmethod
    def quiet_disconnects(handle_error):
        def handle(request, address):
            if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
                handle_error(request, address)
        return handle

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        reset_server()
        self.env.stop()
        self.tmp.cleanup()

    # ------------------------------------------------------------ the server's side, as the app would do it

    def as_(self, name, fn, *args, body=None):
        return call_as(self.users[name] if name else None, fn, *args, body=body)

    def shared(self, **settings):
        """Ada shares her lesson; the ids the flows need."""
        out = self.as_("ada", server.api_share_set, LESSON_ID, body=settings)
        share = importlib.import_module("lemma.shares").by_token(out["token"])
        return {"lesson": LESSON_ID, "token": out["token"], "share": share["id"], "title": self.title}

    def settings(self):
        return self.as_("ada", server.api_share_get, LESSON_ID)

    def run_flow(self, flow, ids=None, width=None, extra=None):
        cfg = {**(extra or {}), "flow": flow, "base": f"http://127.0.0.1:{self.httpd.server_address[1]}/", "cookies": self.cookies,
               "users": {k: u["id"] for k, u in self.users.items()}, "chrome": find_chrome(), "cred": None,
               "ids": {"lesson": LESSON_ID, "title": self.title, **(ids or {})}, "width": width, "coverage": os.environ.get("LEMMA_UI_COVERAGE")}
        done = subprocess.run(["node", "tests/ui.mjs", json.dumps(cfg)], cwd=ROOT, capture_output=True, text=True, timeout=240)
        self.assertEqual(done.returncode, 0, f"\n{done.stdout}\n{done.stderr}")

    # ------------------------------------------------------------ continue where you left off

    def test_continue_where_you_left_off_and_start_from_the_beginning(self):
        self.run_flow("progress-continue")

    def test_a_finished_lesson_offers_review_and_start_again(self):
        self.run_flow("progress-finished")

    def test_an_edited_lesson_continues_from_what_is_still_there(self):
        self.run_flow("progress-changed")

    def test_a_gallery_lesson_keeps_its_place_signed_out_and_each_account_has_its_own(self):
        self.run_flow("progress-gallery")

    # ------------------------------------------------------------ sharing

    def test_the_author_shares_from_the_library(self):
        self.run_flow("share-author")
        out = self.settings()
        self.assertEqual((out["shared"], out["downloadable"], out["show_author"], out["listing"]), (True, True, True, "none"))

    def test_a_signed_out_reader_is_asked_to_sign_in_and_told_what_the_author_sees(self):
        self.run_flow("share-signed-out", self.shared())

    def test_a_reader_reads_and_the_author_sees_how_far(self):
        ids = self.shared(downloadable=True)
        self.run_flow("share-reader", ids, extra={"downloadable": True})
        [grace] = self.settings()["readers"]["people"]
        self.assertEqual((grace["name"], grace["reached"], grace["completed"]), ("Grace Hopper", 1, False))
        self.run_flow("share-readers", ids)

    def test_without_the_authors_leave_a_reader_gets_no_download(self):
        self.run_flow("share-reader", self.shared(), extra={"downloadable": False})

    def test_stopping_sharing_asks_first_and_kills_the_link(self):
        ids = self.shared()
        self.as_("grace", server.api_shared_open, ids["token"])
        self.run_flow("share-stop", ids, extra={"expectErrors": ["status of 404 (Not Found)"]})  # the dead link, as the browser notes it
        self.assertFalse(self.settings()["shared"])

    def test_the_gallery_shows_community_lessons_to_everyone(self):
        ids = self.shared(listed=True)
        self.as_("admin", server.api_admin_listing, ids["share"], body={"action": "approve"})
        self.run_flow("gallery-community", ids)

    def test_many_community_lessons_are_drawn_as_they_come_into_view(self):
        shares = importlib.import_module("lemma.shares")
        for i in range(8):
            lesson = dict(copy.deepcopy(EXAMPLE), id=f"c{i}b2c3d4e5f6"[:12], title=f"Community lesson {i}")
            lesson.pop("example", None)
            store.save_lesson(lesson, SOURCE, self.users["ada"]["id"])
            out = self.as_("ada", server.api_share_set, lesson["id"], body={"listed": True})
            self.as_("admin", server.api_admin_listing, shares.by_token(out["token"])["id"], body={"action": "approve"})
        self.run_flow("community-lazy")

    def test_an_admin_lists_a_lesson_from_the_review_page(self):
        ids = self.shared(listed=True)
        self.run_flow("gallery-review", ids, extra={"expectErrors": ["status of 404 (Not Found)"]})
        self.assertEqual(self.settings()["listing"], "listed")

    def test_a_reader_sees_the_lesson_opening_while_the_server_checks_it(self):
        ids = self.shared()
        checked = server.sharing._checked

        def slowly(*args):
            time.sleep(1.5)  # a lesson whose simulations take a while to check
            return checked(*args)
        checks.forget()  # not checked yet, so the server is slow to open it
        with patch.object(server.sharing, "_checked", side_effect=slowly):
            self.run_flow("shared-loading", ids)

    def test_the_editor_saves_a_lesson_with_a_concept_taught_without_a_model(self):
        self.run_flow("editor-model-free", self.free)
        self.assertEqual(store.load_lesson(FREE_ID, self.users["ada"]["id"])[0]["title"], self.free["freeTitle"] + " (edited twice)")
        self.assertEqual(store.load_lesson(LESSON_ID, self.users["ada"]["id"])[0]["title"], self.title + " (edited twice)")

    def test_a_title_with_a_very_long_word_stays_in_its_column(self):
        lesson = copy.deepcopy(EXAMPLE)
        lesson.pop("example", None)
        lesson.update(id="e1b2c3d4e5f6", title="Pneumonoultramicroscopicsilicovolcanoconiosis" * 3)
        store.save_lesson(lesson, SOURCE, self.users["ada"]["id"])
        self.run_flow("long-title", {"long": "e1b2c3d4e5f6"})

    def test_editing_a_listed_lesson_sends_it_back_to_review(self):
        ids = self.shared(listed=True)
        self.as_("admin", server.api_admin_listing, ids["share"], body={"action": "approve"})
        self.run_flow("edit-listed", ids)
        self.assertEqual(self.settings()["listing"], "waiting")

    def test_a_downloaded_lesson_never_runs_a_disguised_link(self):
        from lemma import export
        lesson = copy.deepcopy(EXAMPLE)
        lesson["source"]["url"] = "java\tscript:window.__ran = 1"  # as a hostile author might write it; the checks would refuse it
        path = Path(self.tmp.name) / "offline.html"
        path.write_text(export.lesson_html(lesson), encoding="utf-8")
        self.run_flow("offline-link", extra={"file": str(path), "expectErrors": ["Content Security Policy", "Refused to run the JavaScript URL"]})

    def test_downloads_start_wherever_they_are_offered(self):
        ids = self.shared(downloadable=True)
        self.as_("grace", server.api_shared_progress, ids["token"], body={"reached": None})  # Grace has started it
        self.run_flow("downloads", ids)

    def test_on_a_phone_everything_fits(self):
        self.run_flow("phone-progress-sharing", self.shared(), width=390)


if __name__ == "__main__":
    unittest.main()
