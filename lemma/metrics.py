"""Daily quotas and anonymous counts, in ``$LEMMA_HOME/metrics.db``, the same on your own computer as hosted.

* Quotas cap each account's daily searches and builds, which Lemma pays Jev for with the server's key, the
  sources it reads on the server, and the feedback it sends. Searches and builds also have a cap for the whole
  site, so many new accounts at once can't run up the bill either. They are configuration with safe defaults: a missing setting means the usual
  cap, never none, and only an explicit `unlimited` lifts one (as local.env does for development).
* Counts are per day and event name only (lessons opened, goals reached, builds that passed or failed):
  no account, lesson, paper or address is recorded with them.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import store

# Events the browser may report; the server counts its own (searches, signups, job outcomes) directly.
BROWSER_EVENTS = frozenset({"lesson_open", "concept_finish", "goal_self", "goal_shown", "check_first_try", "check_retry", "lesson_finish"})
QUOTAS = {  # kind -> (environment variable, cap per account per day when it isn't set); "unlimited" lifts it, 0 turns it off
    "search": ("LEMMA_DAILY_SEARCHES", 40),
    "job": ("LEMMA_DAILY_BUILDS", 20),  # outlines and builds both count: a new lesson is usually one of each
    "read": ("LEMMA_DAILY_READS", 100),  # links and files read on their own, before a lesson is requested
    "feedback": ("LEMMA_DAILY_FEEDBACK", 10),  # messages to whoever runs Lemma, so one account can't flood them
}
SITE_QUOTAS = {  # kind -> (environment variable, cap for all accounts together per day, what the learner is told ran out)
    "search": ("LEMMA_SITE_DAILY_SEARCHES", 400, "searches"),
    "job": ("LEMMA_SITE_DAILY_BUILDS", 200, "outlines and builds"),
}
SITE = "*site*"  # the usage row shared by every account; no account id has this form


class SiteSpent(Exception):
    """Today's allowance for the whole site is used up; the message says so in plain words."""

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


def limit(kind: str, site: bool = False) -> int | None:
    """Today's cap per account (or, with `site`, for the whole site) for `kind`, or None when it is set to `unlimited`."""
    var, default = SITE_QUOTAS[kind][:2] if site else QUOTAS[kind]
    value = os.environ.get(var, "").strip().lower()
    if not value:
        return default  # a forgotten setting keeps the safe cap
    if value == "unlimited":
        return None
    if not value.isdigit():
        raise ValueError(f"{var} must be a whole number of a day's {kind}s {'for the site' if site else 'per account'}, "
                         f"or unlimited (it is {value!r}).")
    return int(value)


def check():
    """Raises ValueError, naming the setting, when a cap is set to something that isn't a whole number."""
    for kind in QUOTAS:
        limit(kind)
    for kind in SITE_QUOTAS:
        limit(kind, site=True)


def take(user_id: str | None, kind: str) -> bool:
    """Use one of the account's daily `kind` allowance; False when today's is spent. Raises SiteSpent, using
    nothing, when the whole site's allowance is."""
    day = _day()
    caps = [(user_id, limit(kind))] if user_id else []
    if kind in SITE_QUOTAS:
        caps.append((SITE, limit(kind, site=True)))
    caps = [(who, cap) for who, cap in caps if cap is not None]
    for who, cap in caps:
        if cap <= 0:
            return _refuse(who, kind, cap)
    if not caps:
        return True
    try:
        with _tx() as con:
            for who, cap in caps:
                # One statement checks and spends, so parallel requests can't all read the old count.
                if con.execute("""INSERT INTO usage (user_id, day, kind, n) VALUES (?, ?, ?, 1)
                                  ON CONFLICT (user_id, day, kind) DO UPDATE SET n = n + 1 WHERE n < ?""",
                               (who, day, kind, cap)).rowcount != 1:
                    raise _Refused(who, cap)  # leaving the transaction this way takes back what it spent
            con.execute("DELETE FROM usage WHERE day < ?", (time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400)),))
    except _Refused as r:
        return _refuse(r.who, kind, r.cap)
    return True


class _Refused(Exception):
    def __init__(self, who, cap):
        self.who, self.cap = who, cap


def _refuse(who: str, kind: str, cap: int) -> bool:
    if who == SITE:
        raise SiteSpent(f"OpenLemma has used all of today's {f'{cap} ' if cap else ''}{SITE_QUOTAS[kind][2]} for everyone, to keep its costs in check. "
                        "They reset at midnight UTC. The gallery and your library still work.")
    return False


def count(name: str) -> None:
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
