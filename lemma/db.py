"""The small SQLite databases kept in LEMMA_HOME (accounts, feedback, metrics, shares, checks), opened one way.

Each is a private file (0600) in write-ahead-log mode, so readers never wait on a writer. Its schema is a numbered
list of migrations: the first time a process opens the file in a home, the ones it hasn't had yet run in order, all
in one transaction, and PRAGMA user_version records how far it has got. Migration 1 creates the tables with
IF NOT EXISTS, so a file made before the numbering is taken up as it is. A new column or index is a new migration at
the end of the list; a migration already released is never edited."""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager

from . import store


def _statements(script: str):
    """The script's statements, one at a time (sqlite3 decides where each ends, so a ';' in a string is safe)."""
    buf = ""
    for part in script.split(";"):
        buf += part + ";"
        if sqlite3.complete_statement(buf):
            if buf.strip(" \t\r\n;"):
                yield buf.strip()
            buf = ""
    if buf.strip(" \t\r\n;"):
        raise ValueError(f"an incomplete statement in a migration: {buf.strip()[:80]}")


class Database:
    """One database file in the home, e.g. Database("shares.db", [SCHEMA_1, ...], rows=True)."""

    def __init__(self, name: str, migrations: list[str] | tuple[str, ...], rows: bool = False, synchronous: str | None = None):
        self.name = name
        self.migrations = tuple(migrations)
        self.rows = rows  # rows as sqlite3.Row (by name) rather than tuples
        self.synchronous = synchronous  # e.g. "NORMAL": with WAL, safe, and a write needn't wait for a disk flush
        self._lock = threading.Lock()
        self._ready: set[str] = set()  # the files (one per home) this process has brought up to date

    def path(self) -> str:
        return str(store.home() / self.name)

    def _migrate(self, path: str) -> None:
        con = sqlite3.connect(path, timeout=10, isolation_level=None)  # transactions are begun here, by hand
        try:
            con.execute("PRAGMA journal_mode = WAL")
            con.execute("BEGIN IMMEDIATE")  # another process opening the file waits here, then sees the new version
            try:
                done = con.execute("PRAGMA user_version").fetchone()[0]
                for number, script in enumerate(self.migrations[done:], start=done + 1):
                    for statement in _statements(script):
                        con.execute(statement)
                    con.execute(f"PRAGMA user_version = {number:d}")
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()
        os.chmod(path, 0o600)

    def connect(self) -> sqlite3.Connection:
        path = self.path()
        if path not in self._ready:
            with self._lock:
                if path not in self._ready:
                    self._migrate(path)
                    self._ready.add(path)
        con = sqlite3.connect(path, timeout=10)
        if self.rows:
            con.row_factory = sqlite3.Row
        if self.synchronous:
            con.execute(f"PRAGMA synchronous = {self.synchronous}")
        return con

    @contextmanager
    def tx(self):
        """One transaction on a fresh connection: committed if the block ends normally, rolled back if it raises,
        and closed either way."""
        con = self.connect()
        try:
            with con:
                yield con
        finally:
            con.close()
