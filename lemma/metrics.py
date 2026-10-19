"""Daily quotas and anonymous counts for a hosted Lemma, in ``$LEMMA_HOME/metrics.db``.

* Quotas cap each account's daily searches and builds, which Lemma pays Jev for with the server's key.
* Counts are per day and event name only (lessons opened, goals reached, builds that passed or failed):
  no account, lesson, paper or address is recorded with them.

A local Lemma has neither: ``ENABLED`` is set by ``server.make_server`` when Lemma is hosted.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import store

ENABLED = False
# Events the browser may report; the server counts its own (searches, signups, job outcomes) directly.
BROWSER_EVENTS = frozenset({"lesson_open", "concept_finish", "goal_self", "goal_shown", "check_first_try", "check_retry", "lesson_finish"})
QUOTAS = {  # kind -> (environment variable, default per account per day)
    "search": ("LEMMA_DAILY_SEARCHES", 40),
    "job": ("LEMMA_DAILY_BUILDS", 20),  # outlines and builds both count: a new lesson is usually one of each
}

_lock = threading.Lock()
_ready: set[str] = set()


def _day() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


@contextmanager
def _tx():
    path = str(store.home() / "metrics.db")
    con = sqlite3.connect(path, timeout=10)
    try:
        if path not in _ready:
            with _lock:
                con.executescript("""
                    PRAGMA journal_mode = WAL;
                    CREATE TABLE IF NOT EXISTS usage (user_id TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL,
                        n INTEGER NOT NULL, PRIMARY KEY (user_id, day, kind));
                    CREATE TABLE IF NOT EXISTS counts (day TEXT NOT NULL, name TEXT NOT NULL,
                        n INTEGER NOT NULL, PRIMARY KEY (day, name));
                """)
                os.chmod(path, 0o600)
                _ready.add(path)
        with con:
            yield con
    finally:
        con.close()


def limit(kind: str) -> int:
    var, default = QUOTAS[kind]
    try:
        return int(os.environ.get(var, default))
    except ValueError:
        return default


def take(user_id: str | None, kind: str) -> bool:
    """Use one of the account's daily `kind` allowance; False when today's is spent. Always True locally."""
    if not ENABLED or not user_id:
        return True
    day, cap = _day(), limit(kind)
    if cap <= 0:
        return False
    with _tx() as con:
        # One statement checks and spends, so parallel requests can't all read the old count.
        granted = con.execute("""INSERT INTO usage (user_id, day, kind, n) VALUES (?, ?, ?, 1)
                                 ON CONFLICT (user_id, day, kind) DO UPDATE SET n = n + 1 WHERE n < ?""",
                              (user_id, day, kind, cap)).rowcount == 1
        if granted:
            con.execute("DELETE FROM usage WHERE day < ?", (time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400)),))
    return granted


def count(name: str) -> None:
    if not ENABLED:
        return
    try:
        with _tx() as con:
            con.execute("""INSERT INTO counts (day, name, n) VALUES (?, ?, 1)
                           ON CONFLICT (day, name) DO UPDATE SET n = n + 1""", (_day(), name))
    except sqlite3.Error:
        pass  # a missed count must never break a lesson


def report(days: int = 30) -> dict:
    """{day: {event: count}} for the last `days` days, newest first."""
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - (days - 1) * 86400))
    out: dict[str, dict[str, int]] = {}
    with _tx() as con:
        for day, name, n in con.execute("SELECT day, name, n FROM counts WHERE day >= ? ORDER BY day DESC, name", (since,)):
            out.setdefault(day, {})[name] = n
    return out
