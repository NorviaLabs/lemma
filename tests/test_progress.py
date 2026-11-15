"""Continue where you left off: the learner's place, kept in this browser only.

lemma/static/progress.js (window.LemmaProgress) saves and restores a learner's place in localStorage, per account and
per lesson, matches it back to a lesson that has changed, and summarises it for the lesson intro, the library and a
shared lesson's author. Its cases run in node (tests/progress.js). The player and the pages that use it are covered in
a real browser by tests/test_ui_progress_sharing.py. This file also holds what the server must keep out of it: nothing
about a learner's progress is stored on the server, and a downloaded lesson still sends nothing and saves nothing.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import fakejev  # noqa: F401  Jev is essential, so every search and build asks this stand-in
from lemma import export, server

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "lemma/static"

# The cases in tests/progress.js, each a requirement of the progress module.
CASES = [
    "each account keeps its own place in each lesson",
    "a lesson's key says where it came from",
    "what is saved comes back, and clearing forgets it",
    "another account's place is not this account's",
    "anything unreadable is nothing saved, never an error",
    "storage that refuses is ignored quietly",
    "a concept's screens: its title, then each activity by id",
    "a concept from before activities lists its screens by kind",
    "an unchanged lesson keeps the place exactly",
    "a screen that moved is found by its id",
    "a screen that is gone starts its concept again, and says the lesson changed",
    "a concept that moved keeps its place under its new number",
    "a concept that is gone is forgotten, and the place moves to the first unfinished concept",
    "a finished concept that is gone no longer counts as finished",
    "a concept still being built is waited for, not forgotten",
    "reconciling never changes what was passed in",
    "nothing saved: nothing to continue",
    "part way through the idea in brief",
    "part way through a concept",
    "finished",
    "the library's line needs no lesson, only what was saved",
    "what a shared lesson's author is told: how far, never answers",
]


def results(lines: str) -> dict[str, str]:
    """{case: "PASS" | "FAIL <why>"} from a script that prints one line per case."""
    out = {}
    for line in lines.splitlines():
        m = re.match(r"^(PASS|FAIL)\s+(.*?)(?:\s+::\s+(.*))?$", line)
        if m:
            out[m.group(2)] = m.group(1) + (f" {m.group(3)}" if m.group(3) else "")
    return out


@unittest.skipUnless(shutil.which("node"), "node is needed to run the progress module's cases")
class ProgressModule(unittest.TestCase):
    def test_every_case(self):
        run = subprocess.run(["node", "tests/progress.js"], cwd=ROOT, capture_output=True, text=True, timeout=120)
        got = results(run.stdout)
        for case in CASES:
            with self.subTest(case):
                self.assertEqual(got.get(case, "FAIL (never ran)" + (f": {run.stderr[-400:]}" if run.stderr else "")), "PASS")


class TheAppLoadsIt(unittest.TestCase):
    def test_the_app_loads_the_progress_module_before_the_player(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        scripts = re.findall(r'<script (?:type="module" )?src="static/([a-z/-]+\.js)"></script>', page)
        self.assertIn("progress.js", scripts)
        self.assertLess(scripts.index("progress.js"), scripts.index("player.js"))
        self.assertLess(scripts.index("progress.js"), scripts.index("app/main.js"))

    def test_the_server_serves_it(self):
        self.assertTrue((STATIC / "progress.js").is_file())
        self.assertIn("LemmaProgress", (STATIC / "progress.js").read_text(encoding="utf-8"))


class KeptInTheBrowserOnly(unittest.TestCase):
    """Progress stays in the browser: no route takes it, and a downloaded lesson neither saves nor sends it."""

    def test_no_route_stores_a_learners_own_progress(self):
        # The one exception is a shared lesson's summary for its author (tests/test_sharing.py). Nothing else takes it.
        routes = [r.pattern for r in server.ROUTES]
        self.assertTrue(any(p.startswith(r"/api/shared/") and p.endswith("/progress") for p in routes), "the shared lesson's report")
        self.assertEqual([p for p in routes if "progress" in p and not p.startswith(r"/api/shared/")], [])

    def test_a_downloaded_lesson_keeps_no_place_and_sends_nothing(self):
        lesson, _ = server.load_example()
        html = export.lesson_html(lesson)
        self.assertIn("connect-src 'none'", html)
        self.assertNotIn("lemma.progress.", html)  # the offline file is mounted without the progress hook
        self.assertNotIn("progress.js", export.SCRIPTS)
        # ... and the app does give the player the hook (see tests/test_ui_progress_sharing.py for its behaviour)
        self.assertIn("progress:", (STATIC / "app" / "learn.js").read_text(encoding="utf-8"))
        self.assertIn("hooks.progress", (STATIC / "player.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
