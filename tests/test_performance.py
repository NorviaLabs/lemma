"""Performance: the hotspots the benchmark found (see the benchmark scripts' report), each held by a test.

* A lesson version is checked once: requests at the same moment share one run, results survive a restart (they
  are kept in ``$LEMMA_HOME/checks.db``, tied to the version of the checks themselves), and every path that needs a
  checked lesson (the gallery, the example, export, save, shared lessons) uses them. Approving a listing checks
  the lesson then, so the gallery never waits for it.
* Warm requests for a shared lesson don't re-hash it or re-read its source.
* Readers' and authors' names are looked up in one query, however many there are.
* The library reads only the lesson files that changed since it last read them.
* Scripts, styles and API answers are compressed for browsers that accept it; scripts and styles can be kept and
  revalidated (ETag), while pages are still never cached.
"""

from __future__ import annotations

import copy
import gzip
import importlib
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from support import LESSON_ID, SOURCE, Site, temp_home
from test_sharing import Base
from lemma import auth, server, store

STATIC = Path(str(server.STATIC))


def checks():
    return importlib.import_module("lemma.checks")


def shares():
    return importlib.import_module("lemma.shares")


class Counting:
    """Counts calls to server.core.require_valid, the one place a lesson's checks run, while still running them."""

    def __init__(self):
        self.calls, self.lock, self.real = [], threading.Lock(), server.core.require_valid

    def __call__(self, lesson, source):
        with self.lock:
            self.calls.append(lesson.get("id"))
        return self.real(lesson, source)

    def __enter__(self):
        self.patch = patch.object(server.core, "require_valid", side_effect=self)
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()


def forget_everything():
    """As after a deploy that changed nothing: no check results anywhere, in memory or on disk."""
    checks().forget()


def restart():
    """As after a server restart: memory is gone, what's on disk stays."""
    checks().forget(memory_only=True)


class ChecksRunOnce(Base):
    def test_requests_at_the_same_moment_share_one_check(self):
        forget_everything()
        errors = []

        def open_it():
            try:
                self.call(server.api_gallery_lesson, "wuhan-2020", user=None)
            except Exception as e:  # pragma: no cover - reported below
                errors.append(e)
        with Counting() as counted:
            threads = [threading.Thread(target=open_it) for _ in range(8)]
            [t.start() for t in threads]
            [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(counted.calls, ["gallery-wuhan-2020"], "eight requests, one check")

    def test_readers_arriving_together_share_one_check_of_a_shared_lesson(self):
        token = self.share()["token"]
        forget_everything()
        with Counting() as counted:
            threads = [threading.Thread(target=lambda: self.call(server.api_shared_about, token, user=None)) for _ in range(8)]
            [t.start() for t in threads]
            [t.join() for t in threads]
        self.assertEqual(counted.calls, [LESSON_ID])

    def test_check_results_survive_a_restart(self):
        token = self.share()["token"]
        self.call(server.api_gallery_lesson, "wuhan-2020", user=None)
        restart()
        with Counting() as counted:
            self.call(server.api_gallery_lesson, "wuhan-2020", user=None)
            self.open(token, self.grace)
            self.call(server.api_example, user=None)
            self.call(server.api_example, user=None)
        self.assertEqual(counted.calls.count("gallery-wuhan-2020"), 0)
        self.assertEqual(counted.calls.count(LESSON_ID), 0)
        self.assertLessEqual(len(counted.calls), 1, "the example is checked once at most")

    def test_a_change_to_the_checks_themselves_checks_again(self):
        self.call(server.api_gallery_lesson, "wuhan-2020", user=None)
        with Counting() as counted, patch.object(checks(), "FINGERPRINT", "a newer version of lesson.py"):
            checks().forget(memory_only=True)
            self.call(server.api_gallery_lesson, "wuhan-2020", user=None)
        self.assertEqual(counted.calls, ["gallery-wuhan-2020"])

    def test_a_failed_check_is_remembered_too_and_still_refuses(self):
        broken = copy.deepcopy(self.lesson)
        broken["concepts"][0]["understand"]["quote"] = "Words that are nowhere in the source at all, not even close."
        with Counting() as counted:
            for _ in range(3):
                self.refused(422, server.api_save, body={"lesson": broken}, user=self.ada)
        self.assertEqual(len(counted.calls), 1)

    def test_the_example_export_and_save_reuse_checks(self):
        self.call(server.api_example, user=None)
        self.call(server.api_export, body={"lesson": self.lesson}, user=self.ada)
        with Counting() as counted:
            self.call(server.api_example, user=None)
            self.call(server.api_export, body={"lesson": self.lesson}, user=self.ada)
            self.call(server.api_save, body={"lesson": self.lesson}, user=self.ada)  # unchanged: this version passed already
        self.assertEqual(counted.calls, [])
        edited = dict(self.lesson, title="A new title")
        with Counting() as counted:
            self.call(server.api_save, body={"lesson": edited}, user=self.ada)
            self.call(server.api_export, body={"lesson": edited}, user=self.ada)
        self.assertEqual(counted.calls, [LESSON_ID], "a new version is checked once, when it is saved")

    def test_approving_a_listing_checks_it_so_the_gallery_never_waits(self):
        token = self.share(listed=True)["token"]
        forget_everything()
        self.admin_act(shares().by_token(token)["id"], "approve")
        restart()
        with Counting() as counted:
            [card] = self.call(server.api_gallery_community, user=None)
        self.assertEqual((card["token"], counted.calls), (token, []))


class SharedPathsStayCheap(Base):
    def readers(self, share_id, n, anonymous=False):
        for i in range(n):
            u = auth.upsert_user("google", f"bulk{i}", f"Reader {i}", f"bulk{i}@example.com", "")
            shares().opened(share_id, u["id"], anonymous)

    def test_the_share_page_looks_readers_names_up_in_one_query(self):
        token = self.share()["token"]
        self.readers(shares().by_token(token)["id"], 300)
        with patch.object(auth.DB, "connect", wraps=auth.DB.connect) as db:
            out = self.settings()
        self.assertEqual(len(out["readers"]["people"]), 300)
        self.assertEqual(out["readers"]["people"][0]["name"], "Reader 299")
        self.assertLessEqual(db.call_count, 1)

    def test_lists_of_shared_lessons_look_names_up_in_one_query(self):
        for i in range(8):
            lesson = dict(copy.deepcopy(self.lesson), id=f"{i}1b2c3d4e5f6"[:12])
            store.save_lesson(lesson, SOURCE, self.ada["id"])
            token = self.share(lesson_id=lesson["id"], listed=True)["token"]
            self.admin_act(shares().by_token(token)["id"], "approve")
            self.start(token, self.grace)
        for name, call in (("community", lambda: self.call(server.api_gallery_community, user=None)),
                           ("shared with you", lambda: self.call(server.api_shared_list, user=self.grace)),
                           ("admin listings", lambda: self.call(server.api_admin_listings, user=self.admin, query={"status": ["listed"]}))):
            with self.subTest(name), patch.object(auth.DB, "connect", wraps=auth.DB.connect) as db:
                self.assertEqual(len(call()), 8)
                self.assertLessEqual(db.call_count, 1, "names in one query, not one per lesson")

    def test_warm_requests_for_a_shared_lesson_neither_rehash_it_nor_read_its_source(self):
        token = self.share(listed=True)["token"]
        self.admin_act(shares().by_token(token)["id"], "approve")
        self.open(token, self.grace)
        self.call(server.api_gallery_community, user=None)
        read = []
        real_read = Path.read_text

        def reading(path, *a, **kw):
            read.append(path.name)
            return real_read(path, *a, **kw)
        with patch.object(checks(), "version", wraps=checks().version) as hashed, patch.object(Path, "read_text", autospec=True, side_effect=reading):
            self.open(token, self.grace)
            self.call(server.api_shared_about, token, user=None)
            self.report(token, self.grace, reached=None)
            self.call(server.api_gallery_community, user=None)
        self.assertEqual(hashed.call_count, 0, "an unchanged lesson is known by its file, not hashed again")
        self.assertEqual([n for n in read if n.endswith(".source.txt")], [], "its source isn't needed")
        # however the files are known, an edit is seen at once
        edited = dict(copy.deepcopy(self.lesson), title="Seen at once")
        self.call(server.api_save, body={"lesson": edited}, user=self.ada)
        self.assertEqual(self.open(token, self.grace)["title"], "Seen at once")


class LibraryStaysCheap(Base):
    def test_the_library_reads_only_the_lessons_that_changed(self):
        for i in range(12):
            store.save_lesson(dict(copy.deepcopy(self.lesson), id=f"{i:02d}b2c3d4e5f6"[:12], title=f"Lesson {i}"), SOURCE, self.ada["id"])
        first = self.call(server.api_lessons, user=self.ada)
        with patch.object(store.json, "loads", wraps=json.loads) as parsed:
            again = self.call(server.api_lessons, user=self.ada)
            status = self.call(server.api_status, user=self.ada)
        self.assertEqual(again, first)
        self.assertEqual(status["library_count"], 13)
        self.assertEqual(parsed.call_count, 0, "nothing changed, so nothing is read again")
        store.save_lesson(dict(copy.deepcopy(self.lesson), id="05b2c3d4e5f6", title="Renamed"), SOURCE, self.ada["id"])
        with patch.object(store.json, "loads", wraps=json.loads) as parsed:
            rows = {r["id"]: r for r in self.call(server.api_lessons, user=self.ada)}
        self.assertEqual(parsed.call_count, 1)
        self.assertEqual(rows["05b2c3d4e5f6"]["title"], "Renamed")
        self.assertEqual(list(rows)[0], "05b2c3d4e5f6", "still newest first")
        store.delete_lesson("05b2c3d4e5f6", self.ada["id"])
        self.assertNotIn("05b2c3d4e5f6", [r["id"] for r in self.call(server.api_lessons, user=self.ada)])


class Compression(unittest.TestCase):
    def setUp(self):
        temp_home(self, "lemma-perf-")
        self.site = Site().__enter__()
        self.addCleanup(self.site.__exit__, None, None, None)

    def get(self, path, **headers):
        """(response, raw body), with exactly the headers given."""
        r = self.site.req("GET", path, origin=False, headers=headers)
        return r.response, r.raw

    def test_scripts_and_styles_are_compressed_and_can_be_revalidated(self):
        for name in ("app/main.js", "app/shell.js", "player.js", "ui.js", "styles.css", "progress.js"):
            with self.subTest(name):
                raw = (STATIC / name).read_bytes()
                r, body = self.get(f"/static/{name}", **{"Accept-Encoding": "gzip, deflate, br"})
                self.assertEqual((r.status, r.getheader("Content-Encoding")), (200, "gzip"))
                self.assertEqual(gzip.decompress(body), raw)
                self.assertLess(len(body), len(raw) / 2)
                self.assertIn("Accept-Encoding", r.getheader("Vary") or "")
                self.assertEqual(r.getheader("Cache-Control"), "no-cache", "kept, but checked on every visit, so a deploy shows at once")
                etag = r.getheader("ETag")
                self.assertTrue(etag)
                again, body = self.get(f"/static/{name}", **{"Accept-Encoding": "gzip", "If-None-Match": etag})
                self.assertEqual((again.status, body), (304, b""))
                plain, body = self.get(f"/static/{name}")
                self.assertEqual((plain.status, plain.getheader("Content-Encoding"), body), (200, None, raw))

    def test_api_answers_are_compressed_for_browsers_that_ask(self):
        r, body = self.get("/api/gallery", **{"Accept-Encoding": "gzip"})
        self.assertEqual(r.getheader("Content-Encoding"), "gzip")
        self.assertEqual(len(json.loads(gzip.decompress(body))), 19)
        r, body = self.get("/api/gallery")
        self.assertIsNone(r.getheader("Content-Encoding"))
        self.assertEqual(len(json.loads(body)), 19)

    def test_pages_are_compressed_and_still_never_cached(self):
        for path in ("/", "/privacy", "/faq"):
            with self.subTest(path):
                r, body = self.get(path, **{"Accept-Encoding": "gzip"})
                self.assertEqual((r.status, r.getheader("Cache-Control"), r.getheader("Content-Encoding")), (200, "no-store", "gzip"))
                self.assertIn(b"<html", gzip.decompress(body))


if __name__ == "__main__":
    unittest.main()
