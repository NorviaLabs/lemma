"""Sharing a lesson: by link, and in the gallery's community section after an admin's review.

The author shares a lesson from their library. Anyone with the link can read it once signed in; nobody can edit it,
and nobody but the author ever gets its source text. Readers see the lesson as the author last saved it. The author
chooses whether their name is shown, whether readers may download it, and whether to ask for it to be listed in the
gallery. Admins (LEMMA_ADMINS) list it or not. The author sees who opened the link and how far they got, or, while
the lesson is listed, totals only; a reader who found it while listed is never named. Shares and readers live in
``$LEMMA_HOME/shares.db``.

The contract, as the app uses it:

* ``GET/POST/DELETE /api/lessons/<id>/share``  the author's settings and readers / share or change / stop sharing
* ``GET /api/shared/<token>/about``             the title, for the sign-in page (no sign-in needed)
* ``GET /api/shared/<token>``                   the lesson, for a signed-in reader; records the reader
* ``POST /api/shared/<token>/progress``         how far the reader got (concept ids only, never answers)
* ``GET /api/shared``, ``POST /api/shared/<token>/hide``  the reader's "Shared with you" list
* ``GET /api/gallery/community``                the listed lessons, as gallery cards (no sign-in needed)
* ``GET /api/admin/listings``, ``POST /api/admin/listings/<share id>``, ``GET /api/admin/listings/<share id>/lesson``
* ``POST /api/export`` with ``{"shared": <token>}`` the offline file, only if the author allows it
"""

from __future__ import annotations

import copy
import importlib
import json
import os
import re
import stat
import unittest
from pathlib import Path
from unittest.mock import patch

from support import EXAMPLE, LESSON_ID, SOURCE, Site, account, call_as, refused, reset_server, saved_lesson, temp_home
from lemma import lesson as L, server, store

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{22,64}$")
MID, REG, WHY = (c["id"] for c in EXAMPLE["concepts"])


def shares():
    """The new module, imported when a test needs it, so each test fails on its own until it exists."""
    return importlib.import_module("lemma.shares")


class Base(unittest.TestCase):
    def setUp(self):
        temp_home(self, "lemma-sharing-")
        admins = patch.dict(os.environ, {"LEMMA_ADMINS": "admin@example.com"})
        admins.start()
        self.addCleanup(admins.stop)
        self.addCleanup(reset_server)
        self.ada = account("ada", "Ada Lovelace").profile
        self.grace = account("grace", "Grace Hopper").profile
        self.alan = account("alan", "Alan Turing").profile
        self.admin = account("admin", "Admin").profile
        self.lesson = saved_lesson(self.ada["id"], category={"primary": {"id": "statistics", "name": "Statistics"}, "secondary": None},
                                   intro={**EXAMPLE["intro"], "known": ["What an average is"], "question": "Why is my tall son shorter than me?"})

    # ------------------------------------------------------------ calling the API as someone

    def call(self, fn, *args, user=None, body=None, query=None):
        return call_as(user, fn, *args, body=body, query=query)

    def refused(self, status, fn, *args, **kw):
        return refused(self, status, fn, *args, **kw)

    def share(self, user=None, lesson_id=LESSON_ID, **settings):
        return self.call(server.api_share_set, lesson_id, user=user or self.ada, body=settings)

    def settings(self, user=None, lesson_id=LESSON_ID):
        return self.call(server.api_share_get, lesson_id, user=user or self.ada)

    def open(self, token, user):
        return self.call(server.api_shared_open, token, user=user)

    def start(self, token, user):
        """A reader opens the lesson and starts it: the app's first progress report is what records them."""
        self.open(token, user)
        return self.report(token, user, reached=None)

    def report(self, token, user, reached=None, finished=(), completed=False):
        return self.call(server.api_shared_progress, token, user=user, body={"reached": reached, "finished": list(finished), "completed": completed})

    def admin_act(self, share_id, action):
        return self.call(server.api_admin_listing, share_id, user=self.admin, body={"action": action})

    def listed(self, **settings):
        """Shares the lesson, asks for the gallery, and has the admin list it."""
        out = self.share(listed=True, **settings)
        self.admin_act(self.share_id(out["token"]), "approve")
        return out

    def share_id(self, token):
        return shares().by_token(token)["id"]


class SharingALesson(Base):
    def test_a_lesson_not_yet_shared_has_the_default_choices(self):
        self.assertEqual(self.settings(), {"shared": False, "show_author": True, "downloadable": False, "listing": "none",
                                           "readers": {"count": 0, "reading": 0, "finished": 0, "named": True, "people": [], "others": 0}})

    def test_sharing_makes_a_link_with_the_chosen_settings(self):
        out = self.share()
        self.assertTrue(out["shared"])
        self.assertRegex(out["token"], TOKEN_RE)
        self.assertEqual((out["show_author"], out["downloadable"], out["listing"]), (True, False, "none"))
        again = self.share(downloadable=True, show_author=False)
        self.assertEqual(again["token"], out["token"], "changing a setting keeps the link")
        self.assertEqual((again["show_author"], again["downloadable"]), (False, True))
        self.assertEqual(self.settings()["token"], out["token"])

    def test_each_share_has_its_own_unguessable_link(self):
        other = copy.deepcopy(self.lesson)
        other["id"] = "b1b2c3d4e5f6"
        store.save_lesson(other, SOURCE, self.ada["id"])
        a, b = self.share()["token"], self.share(lesson_id="b1b2c3d4e5f6")["token"]
        self.assertNotEqual(a, b)
        self.assertNotIn(LESSON_ID, a)
        self.assertNotIn(self.ada["id"], a)

    def test_only_the_author_can_see_or_change_the_sharing(self):
        self.share()
        for fn in (server.api_share_get, server.api_share_set, server.api_share_stop):
            with self.subTest(fn=fn.__name__):
                self.assertIn("isn't in your library", self.refused(404, fn, LESSON_ID, user=self.grace, body={"downloadable": True}))
                self.refused(401, fn, LESSON_ID, user=None)
        self.assertFalse(self.settings()["downloadable"], "nothing changed")

    def test_a_lesson_that_isnt_there_cant_be_shared(self):
        self.refused(404, server.api_share_set, "ffffffffffff", user=self.ada)
        self.refused(404, server.api_share_set, "../etc", user=self.ada)

    def test_a_lesson_without_its_source_cant_be_shared(self):
        orphan = dict(self.lesson, id="c1b2c3d4e5f6")
        store.save_lesson(orphan, None, self.ada["id"])
        self.assertIn("source", self.refused(409, server.api_share_set, "c1b2c3d4e5f6", user=self.ada))

    def test_settings_must_be_true_or_false(self):
        for bad in ({"downloadable": "yes"}, {"show_author": 1}, {"listed": None}, {"downloadable": [True]}):
            with self.subTest(bad=bad):
                self.refused(400, server.api_share_set, LESSON_ID, user=self.ada, body=bad)
        self.assertFalse(self.settings()["shared"], "a refused request shares nothing")

    def test_stopping_kills_the_link_and_sharing_again_makes_a_new_one(self):
        old = self.share(listed=True)["token"]
        stopped = self.call(server.api_share_stop, LESSON_ID, user=self.ada)
        self.assertFalse(stopped["shared"])
        self.assertEqual(stopped["listing"], "none", "stopping also leaves the gallery")
        self.refused(404, server.api_shared_open, old, user=self.grace)
        self.refused(404, server.api_shared_about, old, user=None)
        new = self.share()["token"]
        self.assertNotEqual(new, old)
        self.refused(404, server.api_shared_open, old, user=self.grace)
        self.assertEqual(self.open(new, self.grace)["title"], self.lesson["title"])

    def test_the_library_says_which_lessons_are_shared(self):
        self.share()
        self.start(self.settings()["token"], self.grace)
        rows = {r["id"]: r for r in self.call(server.api_lessons, user=self.ada)}
        self.assertEqual(rows[LESSON_ID]["shared"], {"listing": "none", "readers": 1})
        other = dict(self.lesson, id="b1b2c3d4e5f6")
        store.save_lesson(other, SOURCE, self.ada["id"])
        rows = {r["id"]: r for r in self.call(server.api_lessons, user=self.ada)}
        self.assertIsNone(rows["b1b2c3d4e5f6"]["shared"])

    def test_deleting_the_lesson_deletes_its_share(self):
        token = self.share(listed=True)["token"]
        self.admin_act(self.share_id(token), "approve")
        self.start(token, self.grace)
        self.call(server.api_lesson_delete, LESSON_ID, user=self.ada)
        self.refused(404, server.api_shared_open, token, user=self.grace)
        self.assertEqual(self.call(server.api_gallery_community, user=None), [])
        self.assertEqual(self.call(server.api_shared_list, user=self.grace), [])

    def test_the_database_is_private(self):
        self.share()
        self.assertEqual(stat.S_IMODE((store.home() / "shares.db").stat().st_mode), 0o600)


class ReadingASharedLesson(Base):
    def test_signed_out_the_link_names_the_lesson_and_asks_to_sign_in(self):
        token = self.share()["token"]
        self.assertEqual(self.call(server.api_shared_about, token, user=None),
                         {"title": self.lesson["title"], "author": "Ada Lovelace", "concepts": 3, "category": "Statistics", "named": True})
        self.assertIn("Sign in", self.refused(401, server.api_shared_open, token, user=None))

    def test_a_hidden_author_is_not_named_anywhere(self):
        token = self.share(show_author=False)["token"]
        self.assertIsNone(self.call(server.api_shared_about, token, user=None)["author"])
        lesson = self.open(token, self.grace)
        self.assertIsNone(lesson["shared"]["author"])
        self.assertNotIn("Ada", json.dumps(lesson))
        self.assertNotIn("ada@example.com", json.dumps(lesson))

    def test_a_reader_gets_the_lesson_but_never_the_source_or_the_authors_private_notes(self):
        token = self.share(downloadable=True)["token"]
        lesson = self.open(token, self.grace)
        self.assertEqual(lesson["title"], self.lesson["title"])
        self.assertEqual([c["id"] for c in lesson["concepts"]], [MID, REG, WHY])
        self.assertEqual(lesson["shared"], {"id": self.share_id(token), "token": token, "author": "Ada Lovelace", "downloadable": True,
                                            "listed": False, "owner": False, "named": True})
        self.assertNotEqual(lesson["id"], LESSON_ID, "the author's library id stays private")
        self.assertRegex(lesson["id"], store.ID_RE)
        self.assertNotIn("known", lesson["intro"], "what the author said they already know is theirs")
        self.assertNotIn("question", lesson["intro"], "and so is the question they asked")
        self.assertNotIn("plan", lesson)
        text = json.dumps(lesson)
        self.assertNotIn("ada@example.com", text)
        self.assertNotIn(self.ada["id"], text)
        # The source text: a passage no quote uses never reaches the reader.
        passage = "The fleshy parts of the scalp of the head and of the soles of the feet conclude the list."
        self.assertIn(passage, " ".join(SOURCE.split()))
        self.assertNotIn(passage, text)

    def test_readers_see_the_lesson_as_last_saved(self):
        token = self.share()["token"]
        edited = copy.deepcopy(self.lesson)
        edited["title"] = "Why tall parents have shorter children, revised"
        self.call(server.api_save, body={"lesson": edited}, user=self.ada)
        self.assertEqual(self.open(token, self.grace)["title"], "Why tall parents have shorter children, revised")
        self.assertEqual(self.call(server.api_shared_about, token, user=None)["title"], "Why tall parents have shorter children, revised")

    def test_readers_never_wait_for_checks_the_author_already_ran(self):
        """Each saved version is checked once: sharing checks it, and so does saving an edit, so no reader pays for it."""
        token = self.share()["token"]
        edited = copy.deepcopy(self.lesson)
        edited["title"] = "A title readers get without waiting"
        self.call(server.api_save, body={"lesson": edited}, user=self.ada)  # saving runs the checks itself
        with patch.object(L, "check_lesson", wraps=L.check_lesson) as checks:
            self.assertEqual(self.open(token, self.grace)["title"], "A title readers get without waiting")
            self.assertEqual(self.call(server.api_shared_about, token, user=None)["title"], "A title readers get without waiting")
            self.share(downloadable=True)
            self.assertEqual(checks.call_count, 0, "the version saved was already checked")
        broken = copy.deepcopy(edited)
        broken["concepts"][0]["understand"]["quote"] = "Words that are nowhere in the source at all, not even close."
        self.refused(422, server.api_save, body={"lesson": broken}, user=self.ada)
        self.assertEqual(self.open(token, self.grace)["title"], "A title readers get without waiting", "a refused save changes nothing")

    def test_a_reader_cant_save_or_overwrite_it(self):
        token = self.share()["token"]
        lesson = self.open(token, self.grace)
        self.refused(409, server.api_save, body={"lesson": lesson}, user=self.grace)  # no source in the reader's library
        hijack = dict(lesson, id=LESSON_ID, title="Hijacked")
        self.refused(409, server.api_save, body={"lesson": hijack}, user=self.grace)
        self.assertEqual(store.load_lesson(LESSON_ID, self.ada["id"])[0]["title"], self.lesson["title"])

    def test_a_made_up_or_malformed_link_is_not_found(self):
        self.share()
        for token in ("A" * 22, "nope", "../../x", ""):
            with self.subTest(token=token):
                self.refused(404, server.api_shared_open, token, user=self.grace)
                self.refused(404, server.api_shared_about, token, user=None)

    def test_the_author_opening_their_own_link_isnt_a_reader(self):
        token = self.share()["token"]
        self.assertTrue(self.open(token, self.ada)["shared"]["owner"])
        self.report(token, self.ada, reached=REG, finished=[MID])
        self.assertEqual(self.settings()["readers"]["count"], 0)


class DownloadingASharedLesson(Base):
    def test_downloading_is_the_authors_choice(self):
        token = self.share()["token"]
        self.assertIn("author", self.refused(403, server.api_export, body={"shared": token}, user=self.grace))
        self.refused(401, server.api_export, body={"shared": token}, user=None)
        self.share(downloadable=True)
        html = self.call(server.api_export, body={"shared": token}, user=self.grace)
        self.assertIn(self.lesson["title"], html)
        self.assertIn("connect-src 'none'", html)
        self.assertNotIn(token, html, "the offline file doesn't carry the link")
        self.assertNotIn("What an average is", html, "nor the author's private notes")

    def test_a_download_is_made_from_the_lesson_as_the_author_saved_it(self):
        token = self.share(downloadable=True)["token"]
        tampered = self.open(token, self.grace)
        tampered["title"] = "Something else entirely"
        html = self.call(server.api_export, body={"shared": token, "lesson": tampered}, user=self.grace)
        self.assertNotIn("Something else entirely", html)
        self.assertIn(self.lesson["title"], html)

    def test_no_download_once_the_link_is_off(self):
        token = self.share(downloadable=True)["token"]
        self.call(server.api_share_stop, LESSON_ID, user=self.ada)
        self.refused(404, server.api_export, body={"shared": token}, user=self.grace)


class WhatTheAuthorSees(Base):
    def test_readers_by_name_with_how_far_they_got(self):
        token = self.share()["token"]
        self.open(token, self.grace)
        self.report(token, self.grace, reached=REG, finished=[MID])
        self.start(token, self.alan)
        readers = self.settings()["readers"]
        self.assertEqual({k: readers[k] for k in ("count", "reading", "finished", "named", "others")},
                         {"count": 2, "reading": 1, "finished": 0, "named": True, "others": 0})
        people = {p["name"]: p for p in readers["people"]}
        self.assertEqual(list(people), ["Alan Turing", "Grace Hopper"], "newest first")
        self.assertEqual({k: people["Grace Hopper"][k] for k in ("reached", "total", "completed")}, {"reached": 2, "total": 3, "completed": False})
        self.assertEqual({k: people["Alan Turing"][k] for k in ("reached", "completed")}, {"reached": 0, "completed": False}, "opened, not started")
        self.assertGreater(people["Grace Hopper"]["last"], 0)
        self.assertNotIn("email", json.dumps(readers), "names only")

    def test_a_reader_who_finishes(self):
        token = self.share()["token"]
        self.open(token, self.grace)
        self.report(token, self.grace, reached=WHY, finished=[MID, REG, WHY], completed=True)
        readers = self.settings()["readers"]
        self.assertEqual((readers["count"], readers["reading"], readers["finished"]), (1, 0, 1))
        self.assertTrue(readers["people"][0]["completed"])

    def test_only_how_far_is_accepted_never_anything_else(self):
        token = self.share()["token"]
        self.open(token, self.grace)
        bad = [{"reached": "nope"}, {"reached": 3}, {"finished": "mid_parent"}, {"finished": ["nope"]}, {"finished": [MID, MID]},
               {"finished": [MID] * 50}, {"completed": "yes"}, {"reached": REG, "finished": [{"id": MID}]}]
        for body in bad:
            with self.subTest(body=body):
                self.refused(400, server.api_shared_progress, token, user=self.grace, body=body)
        self.assertEqual(self.report(token, self.grace, reached=REG, finished=[MID]), {"ok": True})
        stored = json.dumps(self.settings())
        self.assertNotIn("goals", stored)

    def test_reporting_needs_a_reader_and_a_live_link(self):
        token = self.share()["token"]
        self.refused(401, server.api_shared_progress, token, user=None, body={"reached": REG})
        self.refused(404, server.api_shared_progress, "B" * 22, user=self.grace, body={"reached": REG})

    def test_readers_are_kept_when_sharing_stops_and_starts_again(self):
        token = self.share()["token"]
        self.start(token, self.grace)
        self.call(server.api_share_stop, LESSON_ID, user=self.ada)
        self.share()
        self.assertEqual(self.settings()["readers"]["count"], 1)

    def test_progress_is_read_against_the_lesson_as_it_is_now(self):
        token = self.share()["token"]
        self.open(token, self.grace)
        self.report(token, self.grace, reached=WHY, finished=[MID, REG])
        edited = copy.deepcopy(self.lesson)
        edited["concepts"] = [edited["concepts"][2], edited["concepts"][0], edited["concepts"][1]]
        with patch.object(server.core, "require_valid"):  # whether the new order teaches well isn't what's tested here
            self.call(server.api_save, body={"lesson": edited}, user=self.ada)
        self.assertEqual(self.settings()["readers"]["people"][0]["reached"], 1, "why_regression is now concept 1")


class TheGallery(Base):
    def test_asking_to_be_listed_waits_for_an_admin(self):
        token = self.share(listed=True)["token"]
        self.assertEqual(self.settings()["listing"], "waiting")
        self.assertEqual(self.call(server.api_gallery_community, user=None), [], "not listed until an admin says so")
        self.assertEqual(self.open(token, self.grace)["title"], self.lesson["title"], "shared by link meanwhile")
        self.assertEqual(self.call(server.api_status, user=self.admin)["gallery_waiting"], 1)
        self.assertNotIn("gallery_waiting", self.call(server.api_status, user=self.ada))
        self.assertNotIn("gallery_waiting", self.call(server.api_status, user=None))

    def test_admins_alone_review_listings(self):
        token = self.share(listed=True)["token"]
        sid = self.share_id(token)
        for user in (self.ada, self.grace, None):
            with self.subTest(user=user and user["name"]):
                self.assertEqual(self.refused(404, server.api_admin_listings, user=user, query={"status": ["waiting"]}), "Not found.")
                self.refused(404, server.api_admin_listing, sid, user=user, body={"action": "approve"})
                self.refused(404, server.api_admin_listing_lesson, sid, user=user)
        [item] = self.call(server.api_admin_listings, user=self.admin, query={"status": ["waiting"]})
        self.assertEqual({k: item[k] for k in ("id", "title", "author", "email", "field", "concepts", "changed")},
                         {"id": sid, "title": self.lesson["title"], "author": "Ada Lovelace", "email": "ada@example.com",
                          "field": "Statistics", "concepts": 3, "changed": False})
        self.assertGreater(item["asked"], 0)

    def test_an_admin_previews_without_becoming_a_reader(self):
        token = self.share(listed=True)["token"]
        lesson = self.call(server.api_admin_listing_lesson, self.share_id(token), user=self.admin)
        self.assertEqual(lesson["title"], self.lesson["title"])
        self.assertEqual(self.settings()["readers"]["count"], 0)

    def test_approved_lessons_appear_in_the_community_section_for_anyone(self):
        token = self.listed()["token"]
        self.assertEqual(self.settings()["listing"], "listed")
        [card] = self.call(server.api_gallery_community, user=None)
        self.assertEqual({k: card[k] for k in ("token", "title", "author", "field")},
                         {"token": token, "title": self.lesson["title"], "author": "Ada Lovelace", "field": "Statistics"})
        self.assertEqual(card["concepts"], [c["title"] for c in self.lesson["concepts"]])
        self.assertEqual(card["source"]["title"], self.lesson["source"]["title"])
        self.assertTrue(card["cover"]["model"], "the card is led by one of its own models, like the built-in gallery")
        self.assertEqual(self.call(server.api_shared_about, token, user=None)["title"], self.lesson["title"])
        self.assertEqual([x["slug"] for x in self.call(server.api_gallery, user=None)], [x["slug"] for x in server.gallery_index()],
                         "the built-in gallery is unchanged")

    def test_a_listed_lesson_can_hide_its_author(self):
        self.listed(show_author=False)
        [card] = self.call(server.api_gallery_community, user=None)
        self.assertIsNone(card["author"])

    def test_not_approved_stays_shared_by_link_and_asking_again_waits_again(self):
        token = self.share(listed=True)["token"]
        self.admin_act(self.share_id(token), "reject")
        self.assertEqual(self.settings()["listing"], "rejected")
        self.assertEqual(self.call(server.api_gallery_community, user=None), [])
        self.assertEqual(self.open(token, self.grace)["title"], self.lesson["title"])
        self.assertEqual(self.share(listed=True)["listing"], "rejected", "ticking the box again changes nothing")
        self.assertEqual(self.share(listed=False)["listing"], "none")
        self.assertEqual(self.share(listed=True)["listing"], "waiting", "unticking then ticking asks again")

    def test_an_admin_can_remove_a_listed_lesson(self):
        token = self.listed()["token"]
        self.admin_act(self.share_id(token), "remove")
        self.assertEqual(self.call(server.api_gallery_community, user=None), [])
        self.assertEqual(self.settings()["listing"], "rejected")

    def test_the_author_can_unlist(self):
        self.listed()
        self.assertEqual(self.share(listed=False)["listing"], "none")
        self.assertEqual(self.call(server.api_gallery_community, user=None), [])

    def test_editing_a_listed_lesson_sends_it_back_to_review_flagged_for_the_admins(self):
        # (It used to stay listed, flagged: the security review found that let an approved lesson be swapped for
        # anything. tests/test_security.py holds the rest.)
        token = self.listed()["token"]
        edited = copy.deepcopy(self.lesson)
        edited["title"] = "A clearer title"
        self.call(server.api_save, body={"lesson": edited}, user=self.ada)
        self.assertEqual(self.call(server.api_gallery_community, user=None), [])
        [item] = self.call(server.api_admin_listings, user=self.admin, query={"status": ["waiting"]})
        self.assertEqual((item["title"], item["changed"]), ("A clearer title", True))
        self.admin_act(item["id"], "approve")
        [item] = self.call(server.api_admin_listings, user=self.admin, query={"status": ["listed"]})
        self.assertFalse(item["changed"])
        del token

    def test_review_actions_and_filters_are_checked(self):
        token = self.share(listed=True)["token"]
        sid = self.share_id(token)
        self.refused(400, server.api_admin_listing, sid, user=self.admin, body={"action": "delete"})
        self.refused(400, server.api_admin_listings, user=self.admin, query={"status": ["open"]})
        self.refused(404, server.api_admin_listing, "ffffffffffff", user=self.admin, body={"action": "approve"})
        self.assertEqual(self.admin_act(sid, "approve")["listing"], "listed")

    def test_listed_means_totals_only_and_gallery_readers_are_never_named(self):
        token = self.listed()["token"]
        opened = self.open(token, self.grace)
        self.assertEqual((opened["shared"]["listed"], opened["shared"]["named"]), (True, False))
        self.report(token, self.grace, reached=REG, finished=[MID])
        readers = self.settings()["readers"]
        self.assertEqual((readers["count"], readers["named"], readers["people"]), (1, False, []))
        self.assertEqual(readers["by_concept"], [{"id": MID, "title": self.lesson["concepts"][0]["title"], "reached": 1},
                                                 {"id": REG, "title": self.lesson["concepts"][1]["title"], "reached": 1},
                                                 {"id": WHY, "title": self.lesson["concepts"][2]["title"], "reached": 0}])
        self.assertNotIn("Grace", json.dumps(readers))
        # Unlisted later, someone who found it in the gallery is still not named; a reader by link is.
        self.share(listed=False)
        self.start(token, self.alan)
        readers = self.settings()["readers"]
        self.assertEqual([p["name"] for p in readers["people"]], ["Alan Turing"])
        self.assertEqual((readers["count"], readers["others"]), (2, 1))
        self.assertFalse(self.open(token, self.grace)["shared"]["named"], "and is told so")


class SharedWithYou(Base):
    def test_the_readers_list_of_shared_lessons(self):
        token = self.share(downloadable=True)["token"]
        self.assertEqual(self.call(server.api_shared_list, user=self.grace), [])
        self.start(token, self.grace)
        [item] = self.call(server.api_shared_list, user=self.grace)
        self.assertEqual({k: item[k] for k in ("token", "title", "author", "concepts", "category", "downloadable")},
                         {"token": token, "title": self.lesson["title"], "author": "Ada Lovelace", "concepts": 3, "category": "Statistics", "downloadable": True})
        self.assertEqual(item["source"], self.lesson["source"]["title"])
        self.assertGreater(item["opened"], 0)
        self.assertEqual(self.call(server.api_shared_list, user=self.ada), [], "the author's own share isn't shared with them")
        self.refused(401, server.api_shared_list, user=None)

    def test_removing_one_from_the_list_keeps_it_counted(self):
        token = self.share()["token"]
        self.start(token, self.grace)
        self.assertEqual(self.call(server.api_shared_hide, token, user=self.grace), {"ok": True})
        self.assertEqual(self.call(server.api_shared_list, user=self.grace), [])
        self.assertEqual(self.settings()["readers"]["count"], 1)
        self.start(token, self.grace)  # reading it again brings it back
        self.assertEqual(len(self.call(server.api_shared_list, user=self.grace)), 1)

    def test_a_share_that_stopped_leaves_the_list(self):
        token = self.share()["token"]
        self.start(token, self.grace)
        self.call(server.api_share_stop, LESSON_ID, user=self.ada)
        self.assertEqual(self.call(server.api_shared_list, user=self.grace), [])


class DeletingAnAccount(Base):
    def test_deleting_an_account_removes_its_shares_and_its_reading(self):
        mine = self.share()["token"]
        grace_lesson = dict(self.lesson, id="d1b2c3d4e5f6")
        store.save_lesson(grace_lesson, SOURCE, self.grace["id"])
        theirs = self.share(user=self.grace, lesson_id="d1b2c3d4e5f6")["token"]
        self.start(mine, self.grace)
        self.start(theirs, self.alan)
        shares().delete_for_account(self.grace["id"])
        self.refused(404, server.api_shared_open, theirs, user=self.alan)
        self.assertEqual(self.settings()["readers"]["count"], 0, "her reading of Ada's lesson is gone too")
        self.assertEqual(self.open(mine, self.alan)["title"], self.lesson["title"], "Ada's share is untouched")


class OverHTTP(unittest.TestCase):
    """The routes, the sign-in they need and the same-origin rule, through the real server."""

    def setUp(self):
        temp_home(self, "lemma-sharing-http-")
        admins = patch.dict(os.environ, {"LEMMA_ADMINS": "admin@example.com"})
        admins.start()
        self.addCleanup(admins.stop)
        self.site = Site().__enter__()
        self.addCleanup(self.site.__exit__, None, None, None)
        self.cookies = {name: account(name, full).cookie for name, full in (("ada", "Ada Lovelace"), ("grace", "Grace Hopper"), ("admin", "Admin"))}
        saved_lesson(account("ada", "Ada Lovelace").id)

    def req(self, method, path, body=None, who=None, origin=None):
        """(status, JSON or text), as `who` (a name in self.cookies) or signed out; `origin` replaces the page's own."""
        r = self.site.req(method, path, body, cookie=self.cookies[who] if who else "", headers={"Origin": origin} if origin else None)
        return r.status, (r.body if not isinstance(r.body, bytes) else r.raw.decode())

    def test_the_whole_round_trip(self):
        s, out = self.req("POST", f"/api/lessons/{LESSON_ID}/share", {"show_author": True}, who="ada")
        self.assertEqual(s, 200, out)
        token = out["token"]
        self.assertEqual(self.req("GET", f"/api/lessons/{LESSON_ID}/share", who="grace")[0], 404)
        self.assertEqual(self.req("POST", f"/api/lessons/{LESSON_ID}/share", {"downloadable": True}, who="ada", origin="http://evil.example")[0], 403)
        s, about = self.req("GET", f"/api/shared/{token}/about")
        self.assertEqual((s, about["author"]), (200, "Ada Lovelace"))
        self.assertEqual(self.req("GET", f"/api/shared/{token}")[0], 401)
        s, lesson = self.req("GET", f"/api/shared/{token}", who="grace")
        self.assertEqual((s, lesson["shared"]["token"]), (200, token))
        self.assertEqual(self.req("POST", f"/api/shared/{token}/progress", {"reached": MID, "finished": [], "completed": False}, who="grace"), (200, {"ok": True}))
        s, settings = self.req("GET", f"/api/lessons/{LESSON_ID}/share", who="ada")
        self.assertEqual([p["name"] for p in settings["readers"]["people"]], ["Grace Hopper"])
        s, mine = self.req("GET", "/api/shared", who="grace")
        self.assertEqual([x["token"] for x in mine], [token])
        self.assertEqual(self.req("POST", "/api/export", {"shared": token}, who="grace")[0], 403)
        self.req("POST", f"/api/lessons/{LESSON_ID}/share", {"downloadable": True}, who="ada")
        s, html = self.req("POST", "/api/export", {"shared": token}, who="grace")
        self.assertEqual(s, 200)
        self.assertIn("<!doctype html>", html)
        self.assertEqual(self.req("POST", f"/api/shared/{token}/hide", {}, who="grace"), (200, {"ok": True}))
        self.assertEqual(self.req("GET", "/api/shared", who="grace"), (200, []))
        self.req("POST", f"/api/lessons/{LESSON_ID}/share", {"listed": True}, who="ada")
        self.assertEqual(self.req("GET", "/api/admin/listings?status=waiting", who="grace")[0], 404)
        s, waiting = self.req("GET", "/api/admin/listings?status=waiting", who="admin")
        self.assertEqual((s, len(waiting)), (200, 1))
        self.assertEqual(self.req("GET", f"/api/admin/listings/{waiting[0]['id']}/lesson", who="admin")[0], 200)
        self.assertEqual(self.req("POST", f"/api/admin/listings/{waiting[0]['id']}", {"action": "approve"}, who="admin")[0], 200)
        s, cards = self.req("GET", "/api/gallery/community")
        self.assertEqual((s, [c["token"] for c in cards]), (200, [token]))
        self.assertEqual(self.req("DELETE", f"/api/lessons/{LESSON_ID}/share", who="ada")[0], 200)
        self.assertEqual(self.req("GET", f"/api/shared/{token}", who="grace")[0], 404)
        self.assertEqual(self.req("GET", "/api/gallery/community"), (200, []))

    def test_links_that_dont_look_like_links_are_not_found(self):
        token = self.req("POST", f"/api/lessons/{LESSON_ID}/share", {}, who="ada")[1]["token"]
        self.assertEqual(self.req("GET", f"/api/shared/{token}/about")[0], 200)
        for path in ("/api/shared/short", "/api/shared/" + "x" * 65, "/api/shared/%2e%2e%2fx/about"):
            with self.subTest(path=path):
                self.assertEqual(self.req("GET", path, who="grace")[0], 404)


class TheDocumentsSaySo(unittest.TestCase):
    """Privacy and the FAQ tell people what sharing shows, and to whom."""

    def test_privacy_and_faq_explain_sharing(self):
        static = Path(str(server.STATIC))
        privacy = (static / "privacy.html").read_text(encoding="utf-8")
        faq = (static / "faq.html").read_text(encoding="utf-8")
        self.assertIn("Lessons you share", privacy)
        self.assertIn("stays in your browser", privacy)  # where you are in a lesson
        self.assertIn('<details id="sharing">', faq)
        self.assertIn("see your name and how far you", faq)
        self.assertNotIn("Only your account can open them.", privacy, "no longer true of shared lessons")


if __name__ == "__main__":
    unittest.main()
