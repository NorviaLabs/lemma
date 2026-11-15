"""Security fixes from the review, each held by tests.

* C1 Readers are recorded only when they start a shared lesson, by the app's progress report (a same-origin POST),
  never by opening it: a page load, even one another site causes, records nobody. A reader told they'd stay
  anonymous stays anonymous.
* C2 Editing a listed lesson takes it out of the gallery until an admin approves it again.
* T2 A lesson's checks run in a separate process with a time limit, at most two at once, one at a time per account,
  within a daily allowance per account. Versions already checked cost nothing.
* T3 A visitor's address comes from the CF-Connecting-IP header only when the connection is from a trusted proxy.
* C3 Only web, mail and in-page links are followed: the checks refuse lessons with other source links, the app and
  the player drop them however they're disguised, and the offline file runs only its own scripts (CSP hashes).
"""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

from support import EXAMPLE, LESSON_ID, ROOT, SOURCE, Site, account, reset_server, saved_lesson, strings, temp_home
from test_sharing import Base, MID
from lemma import export, lesson as L, server, store


def checks():
    return importlib.import_module("lemma.checks")


def shares():
    return importlib.import_module("lemma.shares")


# ---------------------------------------------------------------- C1


class ReadersAreRecordedOnlyWhenTheyStart(Base):
    def test_opening_a_shared_lesson_records_nothing(self):
        token = self.share()["token"]
        self.open(token, self.grace)
        self.open(token, self.alan)
        self.assertEqual(self.settings()["readers"]["count"], 0, "opening isn't reading")
        self.assertEqual(self.call(server.api_shared_list, user=self.grace), [])
        self.report(token, self.grace, reached=None)  # the app reports as the reader starts
        readers = self.settings()["readers"]
        self.assertEqual([p["name"] for p in readers["people"]], ["Grace Hopper"])
        self.assertEqual(len(self.call(server.api_shared_list, user=self.grace)), 1)

    def test_a_reader_told_they_stay_anonymous_stays_anonymous(self):
        token = self.share(listed=True)["token"]
        self.admin_act(shares().by_token(token)["id"], "approve")
        told = self.open(token, self.grace)["shared"]
        self.assertFalse(told["named"])
        self.share(listed=False)  # the author unlists it while she reads the intro
        self.call(server.api_shared_progress, token, user=self.grace, body={"reached": MID, "finished": [], "completed": False, "anonymous": True})
        readers = self.settings()["readers"]
        self.assertEqual((readers["count"], readers["people"], readers["others"]), (1, [], 1))
        self.refused(400, server.api_shared_progress, token, user=self.grace, body={"reached": MID, "anonymous": "yes"})

    def test_removing_from_the_list_lasts_until_the_reader_reads_again(self):
        token = self.share()["token"]
        self.report(token, self.grace, reached=None)
        self.call(server.api_shared_hide, token, user=self.grace)
        self.open(token, self.grace)
        self.assertEqual(self.call(server.api_shared_list, user=self.grace), [], "opening alone doesn't bring it back")
        self.report(token, self.grace, reached=MID)
        self.assertEqual(len(self.call(server.api_shared_list, user=self.grace)), 1)


class ReadersOverHTTP(unittest.TestCase):
    def setUp(self):
        temp_home(self, "lemma-sec-")
        self.site = Site().__enter__()
        self.addCleanup(self.site.__exit__, None, None, None)
        ada, grace = account("ada", "Ada Lovelace"), account("grace", "Grace Hopper")
        self.ada, self.grace = ada.cookie, grace.cookie
        saved_lesson(ada.id)

    def req(self, method, path, body=None, **headers):
        """(status, JSON): exactly the headers given, the Origin included, as a browser would send them."""
        r = self.site.req(method, path, body, cookie=headers.pop("Cookie", ""), origin=False, headers=headers)
        return r.status, r.body

    def test_a_page_load_caused_by_another_site_records_nobody(self):
        origin = self.site.origin
        token = self.req("POST", f"/api/lessons/{LESSON_ID}/share", {}, Cookie=self.ada, Origin=origin)[1]["token"]
        # What a browser sends when another site navigates it here: the Lax cookie, no Origin.
        s, lesson = self.req("GET", f"/api/shared/{token}", Cookie=self.grace, **{"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"})
        self.assertEqual(s, 200)
        self.assertEqual(self.req("POST", f"/api/shared/{token}/progress", {"reached": None}, Cookie=self.grace, Origin="http://evil.example")[0], 403)
        self.assertEqual(self.req("GET", f"/api/lessons/{LESSON_ID}/share", Cookie=self.ada)[1]["readers"]["count"], 0)
        self.assertEqual(self.req("POST", f"/api/shared/{token}/progress", {"reached": None}, Cookie=self.grace, Origin=origin)[0], 200)
        self.assertEqual(self.req("GET", f"/api/lessons/{LESSON_ID}/share", Cookie=self.ada)[1]["readers"]["count"], 1)


# ---------------------------------------------------------------- C2


class ListedLessonsAreReviewedAgain(Base):
    def test_an_edit_takes_a_listed_lesson_out_of_the_gallery_until_approved_again(self):
        token = self.listed()["token"]
        edited = dict(copy.deepcopy(self.lesson), title="Something else entirely")
        out = self.call(server.api_save, body={"lesson": edited}, user=self.ada)
        self.assertEqual(out, {"ok": True, "id": LESSON_ID, "review": True})
        self.assertEqual(self.call(server.api_gallery_community, user=None), [], "not in the gallery until reviewed")
        self.assertEqual(self.settings()["listing"], "waiting")
        self.assertEqual(self.open(token, self.grace)["title"], "Something else entirely", "still shared by link")
        [item] = self.call(server.api_admin_listings, user=self.admin, query={"status": ["waiting"]})
        self.assertTrue(item["changed"], "the admin sees it was edited since it was listed")
        self.admin_act(item["id"], "approve")
        [card] = self.call(server.api_gallery_community, user=None)
        self.assertEqual(card["title"], "Something else entirely")
        [item] = self.call(server.api_admin_listings, user=self.admin, query={"status": ["listed"]})
        self.assertFalse(item["changed"])

    def test_an_edit_to_a_lesson_not_listed_changes_nothing_about_sharing(self):
        self.share()
        out = self.call(server.api_save, body={"lesson": dict(copy.deepcopy(self.lesson), title="A new title")}, user=self.ada)
        self.assertEqual(out, {"ok": True, "id": LESSON_ID, "review": False})
        self.assertEqual(self.settings()["listing"], "none")


# ---------------------------------------------------------------- T2


class ChecksAreContained(Base):
    def heavy(self):
        """A seven-concept lesson with agent simulations, saved with a source that grounds its quotes."""
        lesson, _ = server.load_gallery("schelling-segregation")
        lesson = {k: v for k, v in lesson.items() if k not in ("example", "gallery")}
        lesson["id"] = "f1b2c3d4e5f6"
        store.save_lesson(lesson, "\n\n".join(strings(lesson)), self.ada["id"])
        return lesson

    def test_checks_run_outside_the_server_process(self):
        checks().forget()
        edited = dict(copy.deepcopy(self.lesson), title="Checked elsewhere")
        broken = copy.deepcopy(edited)
        broken["concepts"][0]["understand"]["quote"] = "Words that are nowhere in the source at all, not even close."
        with patch.object(L, "check_lesson", side_effect=AssertionError("checked inside the server")):
            self.assertEqual(self.call(server.api_save, body={"lesson": edited}, user=self.ada)["ok"], True)
            problems = self.refused(422, server.api_save, body={"lesson": broken}, user=self.ada)
        self.assertIn("quality check", problems)

    def test_a_lesson_too_slow_to_check_is_refused_quickly(self):
        checks().forget()
        lesson = self.heavy()
        edited = dict(lesson, title="Slow to check")
        with patch.object(checks(), "CHECK_SECONDS", 0.3):
            started = time.monotonic()
            message = self.refused(422, server.api_save, body={"lesson": edited}, user=self.ada)
            elapsed = time.monotonic() - started
        self.assertIn("took too long to check", message)
        self.assertLess(elapsed, 3)

    def test_one_check_at_a_time_per_account(self):
        checks().forget()
        edited = dict(copy.deepcopy(self.lesson), title="Waits its turn")
        with checks().account_slot(self.ada["id"]):
            self.assertIn("already being checked", self.refused(429, server.api_save, body={"lesson": edited}, user=self.ada))
        self.assertEqual(self.call(server.api_save, body={"lesson": edited}, user=self.ada)["ok"], True)

    def test_at_most_two_checks_run_at_once(self):
        checks().forget()
        self.assertEqual(checks().CHECKS_AT_ONCE, 2)
        edited = dict(copy.deepcopy(self.lesson), title="Busy server")
        gate = checks()._at_once
        gate.acquire(); gate.acquire()
        try:
            with patch.object(checks(), "QUEUE_SECONDS", 0.2):
                self.assertIn("busy", self.refused(503, server.api_save, body={"lesson": edited}, user=self.ada))
        finally:
            gate.release(); gate.release()

    def test_a_daily_allowance_of_checks_per_account(self):
        checks().forget()
        with patch.dict(os.environ, {"LEMMA_DAILY_CHECKS": "2"}):
            for i in range(2):
                self.call(server.api_save, body={"lesson": dict(copy.deepcopy(self.lesson), title=f"Version {i}")}, user=self.ada)
            self.assertIn("checks", self.refused(429, server.api_save, body={"lesson": dict(copy.deepcopy(self.lesson), title="Version 3")}, user=self.ada))
            self.call(server.api_save, body={"lesson": dict(copy.deepcopy(self.lesson), title="Version 0")}, user=self.ada)  # checked already: free
            other = dict(copy.deepcopy(self.lesson), id="e1b2c3d4e5f6", title="Grace's")
            store.save_lesson(other, SOURCE, self.grace["id"])
            self.call(server.api_save, body={"lesson": dict(other, title="Grace's, edited")}, user=self.grace)  # her own allowance


# ---------------------------------------------------------------- T3


class VisitorsCantChooseTheirAddress(unittest.TestCase):
    def setUp(self):
        temp_home(self, "lemma-sec-")
        self.addCleanup(reset_server)

    def posts(self, headers_list):
        """The statuses of a POST per headers, to a server started for them (so its allowances start afresh)."""
        with Site() as site:
            return [site.req("POST", "/api/event", {"name": "lesson_open"}, cookie="", headers=h).status for h in headers_list]

    def test_the_header_is_ignored_from_anyone_but_a_trusted_proxy(self):
        spoofed = [{"CF-Connecting-IP": f"198.51.100.{i}"} for i in range(4)]
        with patch.object(server.http, "RATE_LIMIT", 3), patch.dict(os.environ, {"LEMMA_TRUSTED_PROXIES": "203.0.113.7"}):
            self.assertEqual(self.posts(spoofed), [200, 200, 200, 429], "a made-up address doesn't buy a fresh allowance")

    def test_a_tunnel_on_this_machine_or_its_private_network_is_believed(self):
        self.assertTrue(server.trusted_proxy("127.0.0.1"), "these tests connect from this machine, as a tunnel does")
        visitors = [{"CF-Connecting-IP": f"198.51.100.{i}"} for i in range(4)]
        with patch.object(server.http, "RATE_LIMIT", 3):
            self.assertEqual(self.posts(visitors), [200] * 4, "four visitors behind the tunnel, each with their own allowance")
            self.assertEqual(self.posts([{"CF-Connecting-IP": "198.51.100.9"}] * 4), [200, 200, 200, 429])

    def test_which_proxies_are_trusted(self):
        trusted = server.trusted_proxy
        for ip, want in (("127.0.0.1", True), ("::1", True), ("172.18.0.3", True), ("10.0.0.5", True), ("192.168.1.4", True),
                         ("8.8.8.8", False), ("1.1.1.1", False), ("not an address", False)):
            with self.subTest(ip=ip):
                self.assertEqual(trusted(ip), want)
        with patch.dict(os.environ, {"LEMMA_TRUSTED_PROXIES": "203.0.113.0/24, 2001:db8::1"}):
            self.assertEqual([trusted(ip) for ip in ("203.0.113.9", "2001:db8::1", "127.0.0.1", "10.0.0.5")], [True, True, False, False])


# ---------------------------------------------------------------- C3


BAD_LINKS = ["javascript:alert(1)", "java\tscript:alert(1)", "java\nscript:alert(1)", "\x01javascript:alert(1)", " JaVaScRiPt:alert(1)",
             "vbscript:msgbox(1)", "data:text/html,<script>alert(1)</script>", "file:///etc/passwd", "ftp://example.org/x"]
GOOD_LINKS = ["https://example.org/paper.pdf", "http://example.org/", ""]


class OnlySafeLinks(unittest.TestCase):
    def test_the_checks_refuse_a_lesson_with_a_source_link_that_isnt_a_web_address(self):
        for url in BAD_LINKS:
            for where in ("source", "sources"):
                with self.subTest(url=url, where=where):
                    lesson = copy.deepcopy(EXAMPLE)
                    if where == "source":
                        lesson["source"]["url"] = url
                    else:
                        lesson["sources"] = [{"id": "s1", "title": "A source", "url": url}]
                    self.assertTrue(any("link" in p for p in L.check_lesson(lesson, None)), url)
        for url in GOOD_LINKS:
            with self.subTest(url=url):
                lesson = copy.deepcopy(EXAMPLE)
                lesson["source"]["url"] = url
                self.assertFalse(any("link" in p for p in L.check_lesson(lesson, None)), url)

    def test_the_offline_file_runs_only_its_own_scripts(self):
        html = export.lesson_html(copy.deepcopy(EXAMPLE))
        csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
        script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src")).split()[1:]
        self.assertNotIn("'unsafe-inline'", script_src)
        inline = re.findall(r"<script>(.*?)</script>", html, re.S)
        self.assertGreaterEqual(len(inline), 6)
        for body in inline:
            digest = "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"
            self.assertIn(digest, script_src)
        self.assertIn("connect-src 'none'", csp)

    def test_the_shared_element_builder_loads_before_what_uses_it(self):
        # ui.js holds the one h() and safeUrl(); the app and the player only borrow them, online and offline.
        page = (ROOT / "lemma" / "static" / "index.html").read_text(encoding="utf-8")
        scripts = re.findall(r'<script (?:type="module" )?src="static/([a-z/-]+\.js)"></script>', page)
        self.assertLess(scripts.index("ui.js"), scripts.index("player.js"))
        self.assertLess(scripts.index("ui.js"), scripts.index("app/main.js"))  # a module: it runs after every classic script
        html = export.lesson_html(copy.deepcopy(EXAMPLE))
        self.assertLess(html.index("root.LemmaUI = "), html.index("root.LemmaPlayer = "))

    @unittest.skipUnless(shutil.which("node"), "node is needed to run the link cases")
    def test_the_app_and_player_follow_only_safe_links(self):
        run = subprocess.run(["node", "tests/safe_links.js", json.dumps({"bad": BAD_LINKS, "good": GOOD_LINKS + ["#/shared/abc", "mailto:a@example.org", "privacy", "static/x.png"]})],
                             cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
