"""The library on disk and the hosted daily quotas, when their inputs or files are not what they should be."""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_lemma  # noqa: F401  a temporary LEMMA_HOME and the Jev stand-in
from lemma import __main__ as cli
from lemma import metrics, server, store


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
    """Daily caps are configuration with safe defaults: a missing setting falls back to the usual caps, never to
    none, so a forgotten line in production can't run up the server's bills. Lifting a cap takes an explicit
    `unlimited`, as local.env does for development. The code never asks where it runs."""

    UNSET = {"LEMMA_DAILY_SEARCHES": "", "LEMMA_DAILY_BUILDS": "", "LEMMA_DAILY_READS": "", "LEMMA_DAILY_FEEDBACK": "",
             "LEMMA_SITE_DAILY_SEARCHES": "", "LEMMA_SITE_DAILY_BUILDS": ""}

    def setUp(self):  # the site's allowance is shared, so each test starts from an empty count
        home = patch.dict(os.environ, {"LEMMA_HOME": tempfile.mkdtemp(prefix="lemma-quota-")})
        home.start()
        self.addCleanup(home.stop)

    def test_a_missing_cap_falls_back_to_the_safe_default(self):
        with patch.dict(os.environ, self.UNSET):
            self.assertEqual({k: metrics.limit(k) for k in metrics.QUOTAS}, {"search": 40, "job": 20, "read": 100, "feedback": 10})
            self.assertEqual({k: metrics.limit(k, site=True) for k in metrics.SITE_QUOTAS}, {"search": 400, "job": 200})
            with patch.dict(metrics.QUOTAS, {"job": ("LEMMA_DAILY_BUILDS", 2)}):
                self.assertEqual([metrics.take("quota-default", "job") for _ in range(3)], [True, True, False])

    def test_only_an_explicit_unlimited_lifts_a_cap(self):
        with patch.dict(os.environ, {"LEMMA_DAILY_SEARCHES": "unlimited", "LEMMA_DAILY_BUILDS": " Unlimited ", "LEMMA_DAILY_READS": "unlimited",
                                     "LEMMA_DAILY_FEEDBACK": "unlimited", "LEMMA_SITE_DAILY_SEARCHES": "unlimited",
                                     "LEMMA_SITE_DAILY_BUILDS": "unlimited"}):
            for kind in metrics.QUOTAS:
                self.assertIsNone(metrics.limit(kind))
                self.assertIsNone(metrics.limit(kind, site=True) if kind in metrics.SITE_QUOTAS else None)
                self.assertTrue(all(metrics.take("quota-free", kind) for _ in range(250)), kind)

    def test_a_set_cap_is_enforced(self):
        with patch.dict(os.environ, dict(self.UNSET, LEMMA_DAILY_BUILDS="2")):
            self.assertEqual([metrics.take("quota-two", "job") for _ in range(3)], [True, True, False])

    def test_the_site_cap_counts_every_account_together(self):
        with patch.dict(os.environ, dict(self.UNSET, LEMMA_SITE_DAILY_BUILDS="3")):
            self.assertEqual([metrics.take(f"site-{i}", "job") for i in range(3)], [True, True, True])
            with self.assertRaises(metrics.SiteSpent) as e:
                metrics.take("site-new", "job")
            self.assertIn("today's 3 outlines and builds for everyone", str(e.exception))
            self.assertTrue(metrics.take("site-new", "search"))  # searches have their own allowance
            self.assertTrue(metrics.take("site-new", "read"))  # and reads have none for the site

    def test_a_refusal_by_the_site_costs_the_account_nothing(self):
        with patch.dict(os.environ, dict(self.UNSET, LEMMA_DAILY_BUILDS="2", LEMMA_SITE_DAILY_BUILDS="1")):
            self.assertTrue(metrics.take("site-a", "job"))
            for _ in range(3):
                with self.assertRaises(metrics.SiteSpent):
                    metrics.take("site-b", "job")
            with patch.dict(os.environ, {"LEMMA_SITE_DAILY_BUILDS": "unlimited"}):
                self.assertEqual([metrics.take("site-b", "job") for _ in range(3)], [True, True, False])

    def test_an_account_at_its_own_cap_is_told_about_its_own(self):
        with patch.dict(os.environ, dict(self.UNSET, LEMMA_DAILY_BUILDS="1", LEMMA_SITE_DAILY_BUILDS="2")):
            self.assertEqual([metrics.take("own-a", "job") for _ in range(2)], [True, False])
            self.assertTrue(metrics.take("own-b", "job"))  # own-a's refused try didn't use the site's second

    def test_a_malformed_cap_stops_lemma_from_starting(self):
        # A typo must not quietly change a cap, so nothing starts until it is fixed.
        for var, value in [("LEMMA_DAILY_BUILDS", v) for v in ("lots", "-1", "none", "40.5")] + [("LEMMA_DAILY_FEEDBACK", "ten"),
                                                                                                  ("LEMMA_SITE_DAILY_BUILDS", "lots")]:
            with self.subTest(var=var, value=value), patch.dict(os.environ, dict(self.UNSET, **{var: value})):
                with self.assertRaises(ValueError) as e:
                    server.make_server(0)
                self.assertIn(var, str(e.exception))
                with self.assertRaises(SystemExit), patch("sys.stderr"):
                    cli.main(["--no-browser"])

    def test_the_development_config_lifts_every_cap(self):
        lines = (Path(__file__).resolve().parent.parent / "local.env").read_text().splitlines()
        config = dict(line.split("=", 1) for line in lines if line.strip() and not line.startswith("#"))
        self.assertEqual({k: v for k, v in config.items() if k.startswith(("LEMMA_DAILY_", "LEMMA_SITE_DAILY_"))},
                         {var: "unlimited" for var, *_ in (*metrics.QUOTAS.values(), *metrics.SITE_QUOTAS.values())})

    def test_production_never_lifts_a_cap(self):
        compose = (Path(__file__).resolve().parent.parent / "deploy" / "compose.yaml").read_text()
        caps = dict(re.findall(r"^\s*(LEMMA_(?:SITE_)?DAILY_\w+):\s*\"?([^\"\s#]+)", compose, re.M))
        self.assertEqual(set(caps), {var for var, *_ in (*metrics.QUOTAS.values(), *metrics.SITE_QUOTAS.values())})
        self.assertTrue(all(v.isdigit() for v in caps.values()), caps)

    def test_a_zero_limit_turns_the_feature_off(self):
        with patch.dict(os.environ, {"LEMMA_DAILY_SEARCHES": "0"}):
            self.assertFalse(metrics.take("quota-zero", "search"))

    def test_a_count_that_cannot_be_written_never_breaks_the_request(self):
        with patch.object(metrics.sqlite3, "connect", side_effect=sqlite3.OperationalError("database is locked")):
            self.assertIsNone(metrics.count("lesson_open"))


if __name__ == "__main__":
    unittest.main()
