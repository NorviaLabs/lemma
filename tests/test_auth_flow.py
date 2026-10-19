"""Signing in to a hosted Lemma with Google or GitHub, end to end, against stand-ins for the providers.

Nothing here contacts Google or GitHub: urllib's urlopen is replaced by a fake that answers each provider URL
from a table and records what Lemma sent, which is what the provider would observe.
"""

from __future__ import annotations

import io
import json
import time
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch

from hosting import HostedServer, set_cookies
from lemma import auth, metrics

GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_INFO = "https://openidconnect.googleapis.com/v1/userinfo"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
GITHUB_USER = "https://api.github.com/user"
GITHUB_EMAILS = "https://api.github.com/user/emails"

GOOGLE_ENV = {"LEMMA_PUBLIC_URL": "https://tools.example.com", "LEMMA_GOOGLE_CLIENT_ID": "gid", "LEMMA_GOOGLE_CLIENT_SECRET": "gsecret",
              "LEMMA_GITHUB_CLIENT_ID": "", "LEMMA_GITHUB_CLIENT_SECRET": ""}
GITHUB_ENV = {"LEMMA_PUBLIC_URL": "https://tools.example.com", "LEMMA_GITHUB_CLIENT_ID": "hid", "LEMMA_GITHUB_CLIENT_SECRET": "hsecret",
              "LEMMA_GOOGLE_CLIENT_ID": "", "LEMMA_GOOGLE_CLIENT_SECRET": ""}


class FakeProviders:
    """Answers provider URLs from `routes` (a dict, list, raw bytes, or an exception to raise) and records each call."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def urlopen(self, request, timeout=None):
        sent = urllib.parse.parse_qs(request.data.decode()) if request.data else None
        self.calls.append({"url": request.full_url, "data": sent, "auth": request.get_header("Authorization")})
        answer = self.routes[request.full_url]
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(answer if isinstance(answer, bytes) else json.dumps(answer).encode())

    def __enter__(self):
        self.patcher = patch.object(auth.urllib.request, "urlopen", self.urlopen)
        self.patcher.start()
        return self

    def __exit__(self, *exc):
        self.patcher.stop()


class SignInFlow(unittest.TestCase):
    def sign_in(self, site, pid, code="c0de"):
        """Starts at /auth/<pid>/start and returns the callback's (status, Location, cookies set)."""
        s, r, _ = site.req("GET", f"/auth/{pid}/start")
        self.assertEqual(s, 302)
        state = set_cookies(r)[auth.STATE_COOKIE][0]
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(r.getheader("Location")).query)["state"], [state])
        s, r, _ = site.req("GET", f"/auth/{pid}/callback?code={code}&state={state}", cookies={auth.STATE_COOKIE: state})
        return s, r.getheader("Location"), set_cookies(r)

    def error_shown(self, location):
        prefix = "https://tools.example.com/#/signin?error="
        self.assertTrue(location.startswith(prefix), location)
        return urllib.parse.unquote(location[len(prefix):])

    def test_google_sign_in_starts_a_session_that_later_requests_recognise(self):
        routes = {GOOGLE_TOKEN: {"access_token": "at-123"},
                  GOOGLE_INFO: {"sub": "g-77", "email_verified": True, "name": "Ada Lovelace", "email": "ada@example.com", "picture": "https://lh3.googleusercontent.com/a"}}
        before = sum(day.get("sign_in", 0) for day in metrics.report().values())
        with HostedServer(GOOGLE_ENV) as site, FakeProviders(routes) as fake:
            s, location, cookies = self.sign_in(site, "google")
            self.assertEqual((s, location), (302, "https://tools.example.com/#/"))
            token, attrs = cookies[auth.SESSION_COOKIE]
            self.assertTrue(token)
            self.assertIn(f"Max-Age={auth.SESSION_DAYS * 86400}; HttpOnly; SameSite=Lax; Secure", attrs)
            self.assertEqual(cookies[auth.STATE_COOKIE][0], "")  # the one-time state is cleared

            exchange, info = fake.calls
            self.assertEqual(exchange["url"], GOOGLE_TOKEN)
            self.assertEqual({k: v[0] for k, v in exchange["data"].items()},
                             {"client_id": "gid", "client_secret": "gsecret", "code": "c0de", "grant_type": "authorization_code",
                              "redirect_uri": "https://tools.example.com/auth/google/callback"})
            self.assertEqual((info["url"], info["auth"]), (GOOGLE_INFO, "Bearer at-123"))

            user = json.loads(site.req("GET", "/api/status", cookies={auth.SESSION_COOKIE: token})[2])["user"]
            self.assertEqual((user["provider"], user["name"], user["email"], user["avatar"]),
                             ("google", "Ada Lovelace", "ada@example.com", "https://lh3.googleusercontent.com/a"))
            self.assertEqual(sum(day.get("sign_in", 0) for day in metrics.report().values()), before + 1)

            # Signing in again updates the same account rather than making a second one.
            routes[GOOGLE_INFO] = dict(routes[GOOGLE_INFO], name="Ada King")
            token2 = self.sign_in(site, "google")[2][auth.SESSION_COOKIE][0]
            again = json.loads(site.req("GET", "/api/status", cookies={auth.SESSION_COOKIE: token2})[2])["user"]
            self.assertEqual((again["id"], again["name"]), (user["id"], "Ada King"))

    def test_cancelling_at_the_provider_returns_to_sign_in_without_a_session(self):
        with HostedServer(GOOGLE_ENV) as site, FakeProviders({}) as fake:
            s, r, _ = site.req("GET", "/auth/google/callback?error=access_denied&state=x", cookies={auth.STATE_COOKIE: "x"})
            self.assertEqual((s, r.getheader("Location")), (302, "https://tools.example.com/#/signin"))
            self.assertNotIn(auth.SESSION_COOKIE, set_cookies(r))
            self.assertEqual(fake.calls, [])

    def test_google_accounts_need_a_verified_email(self):
        routes = {GOOGLE_TOKEN: {"access_token": "at"}, GOOGLE_INFO: {"sub": "g-1", "email": "x@example.com", "email_verified": False}}
        with HostedServer(GOOGLE_ENV) as site, FakeProviders(routes):
            s, location, cookies = self.sign_in(site, "google")
            self.assertIn("verified email address", self.error_shown(location))
            self.assertNotIn(auth.SESSION_COOKIE, cookies)

    def test_a_token_reply_without_an_access_token_does_not_sign_in(self):
        with HostedServer(GOOGLE_ENV) as site, FakeProviders({GOOGLE_TOKEN: {"error": "invalid_grant"}}) as fake:
            s, location, cookies = self.sign_in(site, "google")
            self.assertEqual(self.error_shown(location), "Signing in didn't finish. Please try again.")
            self.assertNotIn(auth.SESSION_COOKIE, cookies)
            self.assertEqual([c["url"] for c in fake.calls], [GOOGLE_TOKEN])  # the profile is never asked for

    def test_an_unreachable_or_garbled_provider_reads_as_a_retryable_error(self):
        for answer, reason in ((urllib.error.URLError("timed out"), "timed out"), (TimeoutError("slow"), "slow"), (b"<html>busy</html>", "Expecting value")):
            with self.subTest(reason=reason), HostedServer(GOOGLE_ENV) as site, FakeProviders({GOOGLE_TOKEN: answer}):
                s, location, cookies = self.sign_in(site, "google")
                message = self.error_shown(location)
                self.assertTrue(message.startswith(f"Signing in didn't work ({reason}"), message)
                self.assertNotIn(auth.SESSION_COOKIE, cookies)

    def test_a_callback_without_a_code_never_calls_the_provider(self):
        with HostedServer(GOOGLE_ENV) as site, FakeProviders({}) as fake:
            s, location, cookies = self.sign_in(site, "google", code="")
            self.assertEqual(self.error_shown(location), "Signing in didn't finish. Please try again.")
            self.assertEqual(fake.calls, [])

    def test_an_unconfigured_provider_is_not_offered(self):
        with HostedServer(GOOGLE_ENV) as site:
            s, r, _ = site.req("GET", "/auth/github/start")
            self.assertEqual(s, 302)
            self.assertEqual(self.error_shown(r.getheader("Location")), "That sign-in option isn't available.")
            self.assertEqual(set_cookies(r)[auth.STATE_COOKIE][0], "")  # no sign-in was started

    def test_github_uses_the_primary_verified_email_when_the_profile_hides_it(self):
        routes = {GITHUB_TOKEN: {"access_token": "gh-1"},
                  GITHUB_USER: {"id": 42, "login": "octocat", "name": None, "email": None, "avatar_url": "https://avatars.githubusercontent.com/u/42"},
                  GITHUB_EMAILS: [{"email": "old@example.com", "primary": False, "verified": True},
                                  {"email": "unverified@example.com", "primary": True, "verified": False},
                                  {"email": "octo@example.com", "primary": True, "verified": True}]}
        with HostedServer(GITHUB_ENV) as site, FakeProviders(routes) as fake:
            s, location, cookies = self.sign_in(site, "github")
            self.assertEqual(location, "https://tools.example.com/#/")
            user = json.loads(site.req("GET", "/api/status", cookies={auth.SESSION_COOKIE: cookies[auth.SESSION_COOKIE][0]})[2])["user"]
            self.assertEqual((user["provider"], user["name"], user["email"]), ("github", "octocat", "octo@example.com"))
            self.assertEqual([c["auth"] for c in fake.calls[1:]], ["Bearer gh-1", "Bearer gh-1"])

    def test_github_profile_email_is_used_without_asking_for_the_list(self):
        routes = {GITHUB_TOKEN: {"access_token": "gh-2"}, GITHUB_USER: {"id": 43, "login": "x", "name": "Grace", "email": "grace@example.com"}}
        with FakeProviders(routes) as fake, patch.dict("os.environ", GITHUB_ENV):
            user = auth.finish_sign_in("github", "code")
        self.assertEqual((user["name"], user["email"]), ("Grace", "grace@example.com"))
        self.assertNotIn(GITHUB_EMAILS, [c["url"] for c in fake.calls])

    def test_github_without_an_account_id_or_email_list(self):
        no_id = {GITHUB_TOKEN: {"access_token": "t"}, GITHUB_USER: {"login": "ghost", "email": "g@example.com"}}
        with HostedServer(GITHUB_ENV) as site, FakeProviders(no_id):
            s, location, cookies = self.sign_in(site, "github")
            self.assertEqual(self.error_shown(location), "Signing in didn't finish. Please try again.")
            self.assertNotIn(auth.SESSION_COOKIE, cookies)
        odd = {GITHUB_TOKEN: {"access_token": "t"}, GITHUB_USER: {"id": 44, "login": "quiet"}, GITHUB_EMAILS: {"message": "Not Found"}}
        with FakeProviders(odd), patch.dict("os.environ", GITHUB_ENV):
            self.assertEqual(auth.finish_sign_in("github", "code")["email"], "")


class Sessions(unittest.TestCase):
    def test_a_session_ends_after_thirty_days_or_on_sign_out(self):
        user = auth.upsert_user("google", "sess-1", "Sam", "sam@example.com", "")
        token = auth.new_session(user["id"])
        self.assertEqual(auth.user_for(token)["id"], user["id"])
        later = time.time() + auth.SESSION_DAYS * 86400 + 60
        with patch.object(auth.time, "time", return_value=later):
            self.assertIsNone(auth.user_for(token))
        auth.end_session(token)
        self.assertIsNone(auth.user_for(token))

    def test_no_token_is_nobody(self):
        self.assertIsNone(auth.user_for(None))
        self.assertIsNone(auth.user_for(""))
        auth.end_session(None)  # signing out without a session is harmless

    def test_the_database_never_holds_a_usable_token(self):
        user = auth.upsert_user("github", "sess-2", "Lin", "lin@example.com", "")
        token = auth.new_session(user["id"])
        with auth._tx() as con:
            stored = [row[0] for row in con.execute("SELECT token_hash FROM sessions WHERE user_id = ?", (user["id"],))]
        self.assertEqual(len(stored), 1)
        self.assertNotIn(token, stored[0])


if __name__ == "__main__":
    unittest.main()
