"""Feedback from signed-in accounts, in ``$LEMMA_HOME/feedback.db``, read by the accounts named in LEMMA_ADMINS.

Each item keeps the account's email address so whoever runs Lemma can reply, and where the person was (page,
lesson, error or build id) so the report can be followed up. It is deleted with the account.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

from . import store

RATINGS = ("helpful", "not_helpful")
KINDS = ("general", "lesson", "error", "build")
STATUSES = ("new", "done")
MAX_MESSAGE = 2000
# field -> (most characters, pattern it must match when given)
FIELDS = {
    "page": (300, None),
    "lesson_id": (64, store.ID_RE),
    "lesson_title": (300, None),
    "error_id": (8, re.compile(r"^[0-9a-f]{8}$")),  # as logs.report writes them
    "request_id": (12, re.compile(r"^[0-9a-f]{12}$")),  # a build request's id
}
COLUMNS = ("id", "user_id", "email", "name", "created", "rating", "message", "kind", *FIELDS, "status")

_lock = threading.Lock()
_ready: set[str] = set()


@contextmanager
def _tx():
    path = str(store.home() / "feedback.db")
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        if path not in _ready:
            with _lock:
                con.executescript("""
                    PRAGMA journal_mode = WAL;
                    CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, email TEXT NOT NULL,
                        name TEXT NOT NULL, created REAL NOT NULL, rating TEXT, message TEXT NOT NULL, kind TEXT NOT NULL,
                        page TEXT NOT NULL, lesson_id TEXT NOT NULL, lesson_title TEXT NOT NULL, error_id TEXT NOT NULL,
                        request_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new');
                    CREATE INDEX IF NOT EXISTS feedback_user ON feedback (user_id);
                """)
                os.chmod(path, 0o600)
                _ready.add(path)
        with con:
            yield con
    finally:
        con.close()


def _text(body: dict, key: str) -> str:
    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"The feedback's {key} must be text.")
    return value.strip()


def clean(body: dict) -> dict:
    """The fields of a submission, checked; raises ValueError with a message for the person sending it."""
    rating = body.get("rating")
    if rating is not None and rating not in RATINGS:
        raise ValueError("A rating must be helpful or not_helpful, or left out.")
    message = _text(body, "message")
    if len(message) > MAX_MESSAGE:
        raise ValueError(f"Keep your message to {MAX_MESSAGE:,} characters (it is {len(message):,}).")
    if not rating and not message:
        raise ValueError("Choose a rating or write a message before sending.")
    kind = body.get("kind")
    if kind is None:
        kind = "general"
    if kind not in KINDS:
        raise ValueError("The feedback's kind must be general, lesson, error or build.")
    out = {"rating": rating, "message": message, "kind": kind}
    for key, (most, pattern) in FIELDS.items():
        value = _text(body, key)
        if len(value) > most or (value and pattern and not pattern.match(value)):
            raise ValueError(f"The feedback's {key} isn't valid.")
        out[key] = value
    return out


def add(user: dict, fields: dict) -> str:
    """Stores a cleaned submission from `user` (an auth profile) and returns its id."""
    fid = uuid.uuid4().hex[:12]
    row = {"id": fid, "user_id": user["id"], "email": user.get("email") or "", "name": user.get("name") or "",
           "created": time.time(), **fields, "status": "new"}
    with _tx() as con:
        con.execute(f"INSERT INTO feedback ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})", [row[c] for c in COLUMNS])
    return fid


def items(status: str | None = None) -> list[dict]:
    """Every item, or those with `status`, newest first."""
    with _tx() as con:
        rows = con.execute(f"SELECT {', '.join(COLUMNS)} FROM feedback {'WHERE status = ?' if status else ''} ORDER BY created DESC, rowid DESC",
                           (status,) if status else ()).fetchall()
    return [dict(r) for r in rows]


def set_status(fid: str, status: str) -> bool:
    with _tx() as con:
        return con.execute("UPDATE feedback SET status = ? WHERE id = ?", (status, fid)).rowcount == 1


def delete(fid: str) -> bool:
    with _tx() as con:
        return con.execute("DELETE FROM feedback WHERE id = ?", (fid,)).rowcount == 1


def count_new() -> int:
    with _tx() as con:
        return con.execute("SELECT COUNT(*) FROM feedback WHERE status = 'new'").fetchone()[0]


def delete_for_account(user_id: str) -> int:
    """Removes everything `user_id` sent, as when the account is deleted; returns how many items there were."""
    with _tx() as con:
        return con.execute("DELETE FROM feedback WHERE user_id = ?", (user_id,)).rowcount
