"""The databases in LEMMA_HOME: private WAL files whose schema is a numbered list of migrations, applied once, in
order, all or nothing; and the five stores that use them keep what they held before there were numbers."""

from __future__ import annotations

import sqlite3
import stat
import threading
import unittest

from support import temp_home
from lemma import auth, checks, db, feedback, metrics, shares, store

FIRST = """CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, body TEXT NOT NULL);
           CREATE INDEX IF NOT EXISTS notes_body ON notes (body);"""
SECOND = "ALTER TABLE notes ADD COLUMN tag TEXT NOT NULL DEFAULT 'a;b'"


def raw(path):
    return sqlite3.connect(path)


class Migrations(unittest.TestCase):
    def setUp(self):
        temp_home(self, "lemma-db-")

    def test_a_new_file_is_private_in_wal_mode_and_at_the_last_version(self):
        d = db.Database("notes.db", [FIRST, SECOND])
        with d.tx() as con:
            con.execute("INSERT INTO notes (id, body) VALUES ('1', 'x')")
        path = store.home() / "notes.db"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        con = raw(path)
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT id, body, tag FROM notes").fetchall(), [("1", "x", "a;b")])

    def test_only_the_migrations_a_file_has_not_had_run(self):
        with db.Database("notes.db", [FIRST]).tx() as con:
            con.execute("INSERT INTO notes (id, body) VALUES ('1', 'x')")
        # A later release adds a column; the same process (a new Database) or the next one picks it up.
        with db.Database("notes.db", [FIRST, SECOND]).tx() as con:
            self.assertEqual(con.execute("SELECT id, tag FROM notes").fetchall(), [("1", "a;b")])
        # Opening it again runs nothing (the ALTER would fail if it ran twice).
        with db.Database("notes.db", [FIRST, SECOND]).tx() as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_a_file_made_before_the_numbering_is_taken_up_as_it_is(self):
        path = store.home() / "notes.db"
        con = raw(path)
        con.executescript("CREATE TABLE notes (id TEXT PRIMARY KEY, body TEXT NOT NULL); INSERT INTO notes VALUES ('old', 'kept');")
        con.close()
        with db.Database("notes.db", [FIRST, SECOND]).tx() as con:
            self.assertEqual(con.execute("SELECT id, body, tag FROM notes").fetchall(), [("old", "kept", "a;b")])

    def test_a_failing_migration_changes_nothing_and_is_tried_again_next_time(self):
        bad = db.Database("notes.db", [FIRST, "ALTER TABLE notes ADD COLUMN tag TEXT; ALTER TABLE nope ADD COLUMN x"])
        with self.assertRaises(sqlite3.OperationalError):
            bad.connect()
        con = raw(store.home() / "notes.db")
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall(), [])
        con.close()
        with db.Database("notes.db", [FIRST, SECOND]).tx() as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_a_transaction_commits_or_rolls_back_whole(self):
        d = db.Database("notes.db", [FIRST])
        with self.assertRaises(RuntimeError):
            with d.tx() as con:
                con.execute("INSERT INTO notes (id, body) VALUES ('1', 'x')")
                raise RuntimeError
        with d.tx() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0)

    def test_rows_by_name_and_synchronous_when_asked(self):
        with db.Database("notes.db", [FIRST], rows=True, synchronous="NORMAL").tx() as con:
            con.execute("INSERT INTO notes (id, body) VALUES ('1', 'x')")
            self.assertEqual(con.execute("SELECT body FROM notes").fetchone()["body"], "x")
            self.assertEqual(con.execute("PRAGMA synchronous").fetchone()[0], 1)
        with db.Database("notes.db", [FIRST]).tx() as con:
            self.assertEqual(con.execute("SELECT body FROM notes").fetchone(), ("x",))

    def test_each_home_gets_its_own_file(self):
        d = db.Database("notes.db", [FIRST])
        with d.tx() as con:
            con.execute("INSERT INTO notes (id, body) VALUES ('1', 'x')")
        temp_home(self, "lemma-db-other-")
        with d.tx() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 0)

    def test_many_first_openings_at_once_migrate_once(self):
        d = db.Database("notes.db", [FIRST, SECOND])
        errors = []

        def open_it(i):
            try:
                with d.tx() as con:
                    con.execute("INSERT INTO notes (id, body) VALUES (?, 'x')", (str(i),))
            except Exception as e:  # noqa: BLE001 - any failure is the finding
                errors.append(e)
        threads = [threading.Thread(target=open_it, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        with d.tx() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 16)

    def test_a_string_left_open_is_a_mistake_in_the_migration(self):
        with self.assertRaises(ValueError):
            list(db._statements("CREATE TABLE a (x TEXT); INSERT INTO a VALUES ('never closed)"))


class TheStores(unittest.TestCase):
    """The five stores open their files through db, each at version 1, keeping rows written before the numbering."""

    STORES = {"accounts.db": auth, "feedback.db": feedback, "metrics.db": metrics, "shares.db": shares, "checks.db": checks}

    def setUp(self):
        temp_home(self, "lemma-db-stores-")

    def test_each_store_uses_one_database(self):
        for name, module in self.STORES.items():
            with self.subTest(name):
                self.assertIsInstance(module.DB, db.Database)
                self.assertEqual(module.DB.name, name)
                with module._tx() as con:
                    self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 1)
                    self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                self.assertEqual(stat.S_IMODE((store.home() / name).stat().st_mode), 0o600)

    def test_a_store_made_before_the_numbering_is_taken_up_as_it_is(self):
        # Released versions made these tables with the same script and left user_version at 0.
        for name, module in self.STORES.items():
            con = raw(store.home() / name)
            con.executescript(module.DB.migrations[0])
            con.close()
        con = raw(store.home() / "metrics.db")
        with con:
            con.execute("INSERT INTO counts (day, name, n) VALUES (?, 'opened', 4)", (metrics._day(),))
        con.close()
        metrics.count("opened")
        with metrics._tx() as con:
            self.assertEqual(con.execute("SELECT n FROM counts WHERE name = 'opened'").fetchone()[0], 5)
        for name, module in self.STORES.items():
            with self.subTest(name), module._tx() as con:
                self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
