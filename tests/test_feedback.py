"""Feedback: only signed-in accounts send it, each field is checked, a daily cap applies, and only admins read it."""

from __future__ import annotations

import http.client
import json
import os
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_lemma import TESTER, reset_server, session_cookie, sign_in
from lemma import auth, feedback, server, store

OTHER = "0123456789abcdef"
ADMIN = "adminadminadmin0"


class Feedback(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"LEMMA_HOME": tempfile.mkdtemp(prefix="lemma-feedback-"), "LEMMA_ADMINS": f"{ADMIN}@example.com",
                                      "LEMMA_DAILY_FEEDBACK": ""})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(reset_server)
        server.REQUEST.headers, server.REQUEST.query, server.REQUEST.body = {}, {}, {}
        sign_in()

    def send(self, body, uid=TESTER):
        sign_in(uid)
        return server.api_feedback_create(body)

    def refused(self, status, call):
        with self.assertRaises(server.ApiError) as e:
            call()
        self.assertEqual(e.exception.status, status)
        return e.exception.message

    def as_admin(self, call, status=None, body=None):
        sign_in(ADMIN)
        server.REQUEST.query = {"status": [status]} if status else {}
        server.REQUEST.body = body or {}
        return call()

    def test_a_signed_in_account_sends_feedback_with_its_reply_address(self):
        out = self.send({"rating": "helpful", "message": "  Loved the slider.  ", "kind": "lesson", "page": "#/lesson/abc",
                         "lesson_id": "abc", "lesson_title": "Regression", "error_id": "0a1b2c3d", "request_id": "0123456789ab",
                         "unknown": "ignored"})
        self.assertEqual(out["reply_to"], f"{TESTER}@example.com")
        [item] = self.as_admin(lambda: server.api_feedback_list({}))
        self.assertEqual(item, {"id": out["id"], "user_id": TESTER, "email": f"{TESTER}@example.com", "name": "Tester",
                                "created": item["created"], "rating": "helpful", "message": "Loved the slider.", "kind": "lesson",
                                "page": "#/lesson/abc", "lesson_id": "abc", "lesson_title": "Regression", "error_id": "0a1b2c3d",
                                "request_id": "0123456789ab", "status": "new"})
        self.assertNotEqual(self.send({"message": "Just words."})["id"], out["id"])
        newest = self.as_admin(lambda: server.api_feedback_list({}))[0]
        self.assertEqual((newest["rating"], newest["kind"], newest["page"]), (None, "general", ""))

    def test_signed_out_is_refused(self):
        server.REQUEST.user = None
        self.assertIn("Sign in", self.refused(401, lambda: server.api_feedback_create({"rating": "helpful"})))

    def test_every_field_is_checked(self):
        bad = [
            {}, {"message": "   "}, {"rating": None, "message": ""},
            {"rating": "great"}, {"rating": ""}, {"rating": True}, {"rating": ["helpful"]},
            {"message": "x" * 2001}, {"message": 5}, {"rating": "helpful", "message": {"a": 1}},
            {"rating": "helpful", "kind": "praise"}, {"rating": "helpful", "kind": 1},
            {"rating": "helpful", "page": "#" * 301}, {"rating": "helpful", "page": ["#/"]},
            {"rating": "helpful", "lesson_id": "a" * 65}, {"rating": "helpful", "lesson_id": "../x"},
            {"rating": "helpful", "lesson_title": "t" * 301},
            {"rating": "helpful", "error_id": "0A1B2C3D"}, {"rating": "helpful", "error_id": "0a1b2c3"}, {"rating": "helpful", "error_id": 12345678},
            {"rating": "helpful", "request_id": "not-a-build"},
        ]
        for body in bad:
            with self.subTest(body=str(body)[:60]):
                self.refused(400, lambda: self.send(body))
        self.assertIn("2,000 characters", self.refused(400, lambda: self.send({"message": "x" * 2001})))
        self.assertIn("rating or write a message", self.refused(400, lambda: self.send({})))
        self.send({"message": " " + "x" * 2000 + "\n"})  # the limit counts what is left after trimming
        self.send({"rating": "not_helpful", "page": "#" * 300, "lesson_id": "a" * 64, "lesson_title": "t" * 300})
        self.assertEqual(len(self.as_admin(lambda: server.api_feedback_list({}))), 2)

    def test_the_daily_cap(self):
        with patch.dict(os.environ, {"LEMMA_DAILY_FEEDBACK": "2"}):
            self.send({"rating": "helpful"})
            self.refused(400, lambda: self.send({}))  # a refused submission doesn't use the allowance
            self.send({"rating": "helpful"})
            self.assertIn("today's 2 feedback messages", self.refused(429, lambda: self.send({"rating": "helpful"})))
            self.send({"rating": "helpful"}, OTHER)  # another account has its own allowance
        for _ in range(10):
            self.send({"rating": "helpful"}, ADMIN)
        self.refused(429, lambda: self.send({"rating": "helpful"}, ADMIN))  # 10 a day when unset
        with patch.dict(os.environ, {"LEMMA_DAILY_FEEDBACK": "unlimited"}):
            self.send({"rating": "helpful"}, ADMIN)

    def test_only_admins_read_change_and_delete_feedback(self):
        fid = self.send({"message": "first"})["id"]
        sign_in(OTHER)
        server.REQUEST.body = {"status": "done"}
        for call in (lambda: server.api_feedback_list({}), lambda: server.api_feedback_status(fid), lambda: server.api_feedback_delete(fid)):
            self.assertEqual(self.refused(404, call), "Not found.")
        server.REQUEST.user = None
        self.refused(404, lambda: server.api_feedback_list({}))

        second = self.send({"message": "second"}, OTHER)["id"]
        self.assertEqual([i["id"] for i in self.as_admin(lambda: server.api_feedback_list({}))], [second, fid])  # newest first
        self.assertEqual(self.as_admin(lambda: server.api_feedback_status(fid), body={"status": "done"}), {"id": fid, "status": "done"})
        self.assertEqual([i["id"] for i in self.as_admin(lambda: server.api_feedback_list({}), "done")], [fid])
        self.assertEqual([i["id"] for i in self.as_admin(lambda: server.api_feedback_list({}), "new")], [second])
        self.refused(400, lambda: self.as_admin(lambda: server.api_feedback_list({}), "open"))
        self.refused(400, lambda: self.as_admin(lambda: server.api_feedback_status(fid), body={"status": "closed"}))
        self.refused(404, lambda: self.as_admin(lambda: server.api_feedback_status("ffffffffffff"), body={"status": "done"}))

        self.assertEqual(self.as_admin(lambda: server.api_feedback_delete(fid)), {"ok": True})
        self.refused(404, lambda: self.as_admin(lambda: server.api_feedback_delete(fid)))
        self.assertEqual([i["id"] for i in self.as_admin(lambda: server.api_feedback_list({}))], [second])

    def test_admins_alone_see_how_much_is_new(self):
        self.send({"message": "one"})
        self.send({"message": "two"}, OTHER)
        sign_in(TESTER)
        self.assertNotIn("feedback_new", server.api_status({}))
        server.REQUEST.user = None
        self.assertNotIn("feedback_new", server.api_status({}))
        self.assertEqual(self.as_admin(lambda: server.api_status({}))["feedback_new"], 2)
        self.as_admin(lambda: server.api_feedback_status(feedback.items()[0]["id"]), body={"status": "done"})
        self.assertEqual(self.as_admin(lambda: server.api_status({}))["feedback_new"], 1)

    def test_deleting_an_account_removes_only_its_feedback(self):
        self.send({"message": "mine"})
        self.send({"message": "mine too"})
        self.send({"message": "theirs"}, OTHER)
        self.assertEqual(feedback.delete_for_account(TESTER), 2)
        self.assertEqual([i["user_id"] for i in feedback.items()], [OTHER])

    def test_deleting_a_user_signs_them_out(self):
        user = auth.upsert_user("google", "leaver", "Leaver", "leaver@example.com", "")
        token = auth.new_session(user["id"])
        keep = auth.new_session(auth.upsert_user("google", "stayer", "Stayer", "stayer@example.com", "")["id"])
        auth.delete_user(user["id"])
        self.assertIsNone(auth.user_for(token))
        self.assertEqual(auth.user_for(keep)["name"], "Stayer")

    def test_the_database_is_private(self):
        self.send({"rating": "helpful"})
        self.assertEqual(stat.S_IMODE((store.home() / "feedback.db").stat().st_mode), 0o600)


class FeedbackOverHTTP(unittest.TestCase):
    def test_send_feedback_from_the_browser(self):
        env = patch.dict(os.environ, {"LEMMA_HOME": tempfile.mkdtemp(prefix="lemma-feedback-"), "LEMMA_ADMINS": "tester@example.com"})
        env.start()
        self.addCleanup(env.stop)
        httpd = server.make_server(0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close(), reset_server()))
        cookie = session_cookie()

        def req(method, path, body=None, cookie=cookie):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            h = {"Host": f"localhost:{port}", "Origin": f"http://localhost:{port}", "Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})}
            c.request(method, path, json.dumps(body) if body is not None else None, h)
            r = c.getresponse()
            data = json.loads(r.read())
            c.close()
            return r.status, data

        self.assertEqual(req("POST", "/api/feedback", {"rating": "helpful"}, cookie="")[0], 401)
        s, out = req("POST", "/api/feedback", {"rating": "not_helpful", "message": "The goal was unclear.", "kind": "lesson", "page": "#/lesson/x"})
        self.assertEqual((s, out["reply_to"]), (200, "tester@example.com"))
        self.assertEqual(req("POST", "/api/feedback", {"message": "x" * 2001})[0], 400)
        self.assertEqual(req("GET", "/api/status")[1]["feedback_new"], 1)
        s, items = req("GET", "/api/feedback?status=new")
        self.assertEqual((s, [i["id"] for i in items]), (200, [out["id"]]))
        self.assertEqual(req("POST", f"/api/feedback/{out['id']}/status", {"status": "done"}), (200, {"id": out["id"], "status": "done"}))
        self.assertEqual(req("GET", "/api/feedback?status=new")[1], [])
        self.assertEqual(req("DELETE", f"/api/feedback/{out['id']}"), (200, {"ok": True}))
        self.assertEqual(req("GET", "/api/feedback"), (200, []))


if __name__ == "__main__":
    unittest.main()
