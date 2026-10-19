"""Accounts for a hosted Lemma: sign in with Google or GitHub, one profile and one library per person.

A local Lemma has no accounts. A hosted one reads its settings from the environment:

* ``LEMMA_PUBLIC_URL``: where people reach it, e.g. ``https://tools.example.com/lemma``. Sign-in
  providers send people back to ``<public url>/auth/<provider>/callback``.
* ``LEMMA_GOOGLE_CLIENT_ID`` / ``LEMMA_GOOGLE_CLIENT_SECRET`` and ``LEMMA_GITHUB_CLIENT_ID`` /
  ``LEMMA_GITHUB_CLIENT_SECRET``: one OAuth app per provider. A provider without both is not offered.

Users and sessions live in ``$LEMMA_HOME/accounts.db``. A session cookie holds a random token; the
database keeps only its SHA-256, so a copy of the database can't be used to sign in. Lemma asks only
for the person's name, email address and picture.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass

from . import store

SESSION_COOKIE = "lemma_session"
STATE_COOKIE = "lemma_oauth"
SESSION_DAYS = 30


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class OAuthProvider:
    id: str
    name: str
    authorize: str
    token: str
    scope: str


OAUTH = {
    p.id: p
    for p in (
        OAuthProvider("google", "Google", "https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token", "openid email profile"),
        OAuthProvider("github", "GitHub", "https://github.com/login/oauth/authorize", "https://github.com/login/oauth/access_token", "read:user user:email"),
    )
}


LOCAL_URL = ""  # set by server.make_server: this computer's address, where sign-ins return when LEMMA_PUBLIC_URL isn't set


def public_url() -> str:
    return (os.environ.get("LEMMA_PUBLIC_URL") or LOCAL_URL).rstrip("/")


def cookie_path() -> str:
    return (urllib.parse.urlsplit(public_url()).path or "") + "/"


def _client(pid: str) -> tuple[str, str]:
    up = pid.upper()
    return os.environ.get(f"LEMMA_{up}_CLIENT_ID", ""), os.environ.get(f"LEMMA_{up}_CLIENT_SECRET", "")


def providers() -> list[dict]:
    """The sign-in options this server offers, first the one to suggest."""
    if not public_url():
        return []
    return [{"id": p.id, "name": p.name, "label": f"Continue with {p.name}"} for p in OAUTH.values() if all(_client(p.id))]


# ---------------------------------------------------------------- database

_db_lock = threading.Lock()
_ready: set[str] = set()


def _db() -> sqlite3.Connection:
    path = str(store.home() / "accounts.db")
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    if path not in _ready:
        with _db_lock:
            con.executescript("""
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL, subject TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', avatar TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL, last_seen REAL NOT NULL, UNIQUE (provider, subject));
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created REAL NOT NULL, expires REAL NOT NULL);
            """)
            os.chmod(path, 0o600)
            _ready.add(path)
    return con


@contextmanager
def _tx():
    """One transaction on a fresh connection, committed and closed afterwards."""
    con = _db()
    try:
        with con:
            yield con
    finally:
        con.close()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _profile(row) -> dict:
    return {"id": row["id"], "provider": row["provider"], "name": row["name"], "email": row["email"], "avatar": row["avatar"], "created": row["created"]}


def upsert_user(provider: str, subject: str, name: str, email: str, avatar: str) -> dict:
    uid = hashlib.sha256(f"{provider}:{subject}".encode()).hexdigest()[:16]
    now = time.time()
    with _tx() as con:
        con.execute("""INSERT INTO users (id, provider, subject, name, email, avatar, created, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT (id) DO UPDATE SET name = excluded.name, email = excluded.email, avatar = excluded.avatar, last_seen = excluded.last_seen""",
                    (uid, provider, subject, name[:200], email[:320], avatar[:1000], now, now))
        return _profile(con.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())


def new_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _tx() as con:
        con.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        con.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (_hash(token), user_id, now, now + SESSION_DAYS * 86400))
    return token


def user_for(token: str | None) -> dict | None:
    if not token:
        return None
    with _tx() as con:
        row = con.execute("SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id WHERE token_hash = ? AND expires > ?",
                          (_hash(token), time.time())).fetchone()
    return _profile(row) if row else None


def end_session(token: str | None):
    if token:
        with _tx() as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


def delete_user(user_id: str):
    """Removes the account and signs it out everywhere (deploy/README.md lists the rest an account deletion removes)."""
    with _tx() as con:
        con.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))  # foreign keys aren't enforced, so not cascaded
        con.execute("DELETE FROM users WHERE id = ?", (user_id,))


# ---------------------------------------------------------------- OAuth


def _callback(pid: str) -> str:
    return f"{public_url()}/auth/{pid}/callback"


def sign_in_url(pid: str, state: str) -> str:
    if pid not in [x["id"] for x in providers()]:
        raise AuthError("That sign-in option isn't available.")
    p = OAUTH[pid]
    q = {"client_id": _client(pid)[0], "redirect_uri": _callback(pid), "response_type": "code", "scope": p.scope, "state": state}
    if pid == "google":
        q["prompt"] = "select_account"
    return f"{p.authorize}?{urllib.parse.urlencode(q)}"


def _call(url: str, data: dict | None = None, token: str = "") -> dict | list:
    headers = {"Accept": "application/json", "User-Agent": "Lemma"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=15) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise AuthError(f"Signing in didn't work ({getattr(e, 'reason', e)}). Please try again.") from None


def finish_sign_in(pid: str, code: str) -> dict:
    """Swaps the code the provider sent back for the person's profile, and stores them."""
    p = OAUTH.get(pid)
    if not p or not code:
        raise AuthError("Signing in didn't finish. Please try again.")
    cid, secret = _client(pid)
    tok = _call(p.token, {"client_id": cid, "client_secret": secret, "code": code, "redirect_uri": _callback(pid), "grant_type": "authorization_code"})
    access = isinstance(tok, dict) and tok.get("access_token")
    if not access:
        raise AuthError("Signing in didn't finish. Please try again.")
    if pid == "google":
        info = _call("https://openidconnect.googleapis.com/v1/userinfo", token=access)
        if not info.get("sub") or not info.get("email_verified", False):
            raise AuthError("OpenLemma needs a Google account with a verified email address.")
        return upsert_user("google", str(info["sub"]), info.get("name") or "", info.get("email") or "", info.get("picture") or "")
    info = _call("https://api.github.com/user", token=access)
    email = info.get("email") or ""
    if not email:
        emails = _call("https://api.github.com/user/emails", token=access)
        email = next((e["email"] for e in emails if e.get("primary") and e.get("verified")), "") if isinstance(emails, list) else ""
    if not info.get("id"):
        raise AuthError("Signing in didn't finish. Please try again.")
    if not email:  # GitHub only lets a verified address be public, so either way it is verified
        raise AuthError("OpenLemma needs a GitHub account with a verified email address.")
    return upsert_user("github", str(info["id"]), info.get("name") or info.get("login") or "", email, info.get("avatar_url") or "")
