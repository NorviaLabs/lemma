"""Each version of a lesson is checked once, and the result is kept.

A lesson's checks (lesson.check_lesson: grounding, models that evaluate, reachable goals) can take seconds for a
lesson with simulations. Several paths need a checked lesson: the gallery, the example, saving, exporting, and every
reader of a shared lesson. So the result is kept for the version: a hash of the lesson, its source and the checks'
own code (FINGERPRINT). Requests that arrive at the same moment share one run, and results live in
``$LEMMA_HOME/checks.db``, so a restart doesn't lose them. Changing the checks' code changes the fingerprint, which
checks every lesson again.

Callers that know a lesson by its files (their paths, sizes and modification times) pass that as `known_as`, so an
unchanged lesson is neither hashed nor has its source read again.

A check runs in a separate process (`run_isolated`), like reading a PDF: it can't hold up the server's other requests,
it is stopped after CHECK_SECONDS, and at most CHECKS_AT_ONCE run at a time. A lesson anyone can write (by editing
it) must not be able to take the server's time, so each account also runs one check at a time (`account_slot`).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from importlib import resources

from . import db, store

# The code whose behaviour decides a check's result. Any change to it checks every lesson again.
CHECKER_FILES = ("lesson.py", "expr.py", "kernels.py", "checks.py")
FINGERPRINT = hashlib.sha256(b"".join(resources.files("lemma").joinpath(f).read_bytes() for f in CHECKER_FILES)).hexdigest()

# Both are kept per LEMMA_HOME (the first part of each key), like the results on disk they stand for.
_memory: dict[tuple[str, str], list[str]] = {}  # (home, version) -> problems ([] when it passed)
_known: dict[tuple, str] = {}  # (home, what a lesson is known as: its files) -> its version
_running: dict[str, threading.Lock] = {}  # version -> the lock held while it is being checked
_guard = threading.Lock()

CHECK_SECONDS = 20  # the longest a lesson's checks may take; a real lesson takes well under 5
CHECK_MEMORY = 1024 * 1024 * 1024  # bytes the checking process may use
CHECKS_AT_ONCE = 2  # checks running at the same time, in all
QUEUE_SECONDS = 30  # how long a check waits for its turn before the request is refused as busy
_at_once = threading.BoundedSemaphore(CHECKS_AT_ONCE)
_accounts: set[str] = set()  # accounts with a check running


class Refused(Exception):
    """A check that couldn't run now: too slow, the server busy, or the account already checking one."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


@contextmanager
def account_slot(account: str):
    """One check at a time per account: a second while the first runs is refused, not queued."""
    with _guard:
        if account in _accounts:
            raise Refused(429, "A lesson of yours is already being checked. Wait for it to finish, then try again.")
        _accounts.add(account)
    try:
        yield
    finally:
        with _guard:
            _accounts.discard(account)


def _child_env() -> dict:
    """The checking process's environment: enough to run Python, and none of the server's keys or secrets."""
    return {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")}


def run_isolated(lesson: dict, source: str | None) -> list[str]:
    """The lesson's problems, found by lesson.check_lesson in a separate process with a time and memory limit.
    Raises Refused when it takes too long, or when the server is already running as many checks as it may."""
    if not _at_once.acquire(timeout=QUEUE_SECONDS):
        raise Refused(503, "OpenLemma is busy checking other lessons. Try again in a minute.")
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = "import sys; sys.path.insert(0, sys.argv[1]); from lemma.checks import _child; _child(int(sys.argv[2]), int(sys.argv[3]))"
        try:  # -I: the working directory and PYTHON* variables can't change what the child imports
            done = subprocess.run([sys.executable, "-I", "-c", code, root, str(CHECK_MEMORY), str(int(CHECK_SECONDS) + 1)],
                                  input=json.dumps({"lesson": lesson, "source": source}).encode(), capture_output=True,
                                  timeout=CHECK_SECONDS, env=_child_env())
        except subprocess.TimeoutExpired:
            raise Refused(422, f"This lesson took too long to check (more than {CHECK_SECONDS:g} seconds). "
                               "Simplify its models or simulations, then save it again.") from None
        try:
            found = json.loads(done.stdout)
        except ValueError:
            raise Refused(422, "This lesson couldn't be checked. Simplify its models or simulations, then save it again.") from None
        return [str(p) for p in found]
    finally:
        _at_once.release()


def _child(max_memory: int, max_cpu: int) -> None:
    """The checking process: a lesson and its source on stdin, its problems as JSON on stdout."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (max_memory, max_memory))
        resource.setrlimit(resource.RLIMIT_CPU, (max_cpu, max_cpu))
    except (ImportError, ValueError, OSError):  # not every platform enforces them (macOS doesn't)
        pass
    from . import lesson as L
    data = json.loads(sys.stdin.buffer.read())
    sys.stdout.write(json.dumps(list(L.check_lesson(data["lesson"], data["source"]))))


# Version 1 is the schema as first released; add to the end, never edit (see db.py).
DB = db.Database("checks.db", [
    "CREATE TABLE IF NOT EXISTS checked (version TEXT PRIMARY KEY, problems TEXT NOT NULL, at REAL NOT NULL);",
])
_tx = DB.tx


def version(lesson: dict, source: str | None) -> str:
    """The version a check result belongs to: the lesson, its source and the checks themselves."""
    h = hashlib.sha256(FINGERPRINT.encode())
    h.update(json.dumps(lesson, ensure_ascii=False, sort_keys=True).encode())
    h.update(b"\0")
    h.update((source or "").encode())
    return h.hexdigest()


def _stored(v: str) -> list[str] | None:
    with _tx() as con:
        row = con.execute("SELECT problems FROM checked WHERE version = ?", (v,)).fetchone()
    return json.loads(row[0]) if row else None


def _store(v: str, problems: list[str]):
    with _tx() as con:
        con.execute("INSERT OR REPLACE INTO checked VALUES (?, ?, ?)", (v, json.dumps(problems), time.time()))


def problems(lesson_and_source, run, known_as: tuple | None = None) -> list[str]:
    """The lesson's problems, checked at most once per version.

    `lesson_and_source` gives (lesson, source) when they're needed: not at all for a lesson already known by its files.
    `run(lesson, source)` runs the checks and returns their problems."""
    home = str(store.home())
    key = (home, FINGERPRINT, *known_as) if known_as else None
    v = _known.get(key) if key else None
    if v is not None and (home, v) in _memory:
        return _memory[(home, v)]
    lesson, source = lesson_and_source()
    v = v or version(lesson, source)
    if key:
        if len(_known) > 50_000:  # old versions of edited lessons: start afresh rather than grow without end
            _known.clear()
        _known[key] = v
    if (home, v) in _memory:
        return _memory[(home, v)]
    with _guard:
        lock = _running.setdefault((home, v), threading.Lock())
    with lock:  # one run per version; those who arrive meanwhile wait for it
        if (home, v) not in _memory:
            found = _stored(v)
            if found is None:
                found = list(run(lesson, source))
                _store(v, found)
            if len(_memory) > 50_000:  # kept on disk anyway: start afresh rather than grow without end
                _memory.clear()
            _memory[(home, v)] = found
    with _guard:
        _running.pop((home, v), None)
    return _memory[(home, v)]


def remember(lesson: dict, source: str | None, found: list[str], known_as: tuple | None = None):
    """Records a result found elsewhere, such as by saving, so nobody checks that version again."""
    home, v = str(store.home()), version(lesson, source)
    _memory[(home, v)] = list(found)
    _store(v, list(found))
    if known_as:
        _known[(home, FINGERPRINT, *known_as)] = v


def forget(memory_only: bool = False):
    """Forgets results: in memory only (as a restart does), or everywhere."""
    _memory.clear()
    _known.clear()
    if not memory_only:
        with _tx() as con:
            con.execute("DELETE FROM checked")
