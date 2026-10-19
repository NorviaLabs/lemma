"""The library on disk and the hosted daily quotas, when their inputs or files are not what they should be."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import test_lemma  # noqa: F401  a temporary LEMMA_HOME and the Jev stand-in
from lemma import metrics, store


class Library(unittest.TestCase):
    def setUp(self):
        self.home = patch.dict(os.environ, {"LEMMA_HOME": tempfile.mkdtemp(prefix="lemma-store-")})
        self.home.start()
        self.addCleanup(self.home.stop)

    def test_ids_that_could_leave_the_library_are_refused(self):
        for call in (lambda: store.library("../alice"), lambda: store.load_lesson("../../etc/passwd"),
                     lambda: store.request_path("a/b"), lambda: store.save_lesson({"id": "x y"}, "src")):
            with self.assertRaises(KeyError):
                call()
        self.assertFalse((store.home() / "users").exists())

    def test_damaged_files_are_skipped_in_listings(self):
        store.save_lesson({"id": "good", "title": "Good"}, "source")
        (store.library() / "broken.json").write_text("{not json")
        self.assertEqual([x["id"] for x in store.list_lessons()], ["good"])
        store.save_request({"id": "r1", "created": 1})
        (store.requests() / "r2.json").write_text("{not json")
        self.assertEqual([r["id"] for r in store.list_requests()], ["r1"])

    def test_a_failed_write_leaves_the_old_file_and_no_temporary(self):
        store.save_lesson({"id": "keep", "title": "Old"}, None)
        with patch.object(store.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                store.save_lesson({"id": "keep", "title": "New"}, None)
        self.assertEqual(store.load_lesson("keep")[0]["title"], "Old")
        self.assertEqual([p.name for p in store.library().iterdir() if p.name.startswith(".tmp-")], [])


class Quotas(unittest.TestCase):
    def setUp(self):
        self.was = metrics.ENABLED
        metrics.ENABLED = True
        self.addCleanup(setattr, metrics, "ENABLED", self.was)

    def test_a_malformed_limit_falls_back_to_the_default(self):
        with patch.dict(os.environ, {"LEMMA_DAILY_BUILDS": "lots"}):
            self.assertEqual(metrics.limit("job"), metrics.QUOTAS["job"][1])

    def test_a_zero_limit_turns_the_feature_off(self):
        with patch.dict(os.environ, {"LEMMA_DAILY_SEARCHES": "0"}):
            self.assertFalse(metrics.take("quota-zero", "search"))

    def test_a_count_that_cannot_be_written_never_breaks_the_request(self):
        with patch.object(metrics.sqlite3, "connect", side_effect=sqlite3.OperationalError("database is locked")):
            self.assertIsNone(metrics.count("lesson_open"))


if __name__ == "__main__":
    unittest.main()
