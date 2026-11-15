"""Shared lessons and who read them, in ``$LEMMA_HOME/shares.db``.

An author shares a lesson from their library by link: a random token that can't be guessed from the lesson or the
account, replaced by a new one whenever sharing stops and starts again. Readers get the lesson as the author last saved
it (server/sharing.py reads it from the author's library each time), never its source text. The author chooses whether
their name is shown, whether readers may download the lesson, and whether to ask for it to be listed in the gallery,
which an admin then approves or not.

For each reader this keeps only when they opened the lesson and how far they got: the furthest concept reached, the
concepts finished, and whether they finished the lesson. Never their answers. A reader who opened the lesson while it
was listed in the gallery is anonymous to the author from then on. Everything about a share goes with its lesson, and
with the account (``delete_for_account``).
"""

from __future__ import annotations

import json
import secrets
import time
import uuid

from . import db

LISTINGS = ("none", "waiting", "listed", "rejected")
ACTIONS = ("approve", "reject", "remove", "checked")

# Version 1 is the schema as first released; add to the end, never edit (see db.py). synchronous = NORMAL: with WAL,
# safe, and a reader's progress needn't wait for a disk flush.
DB = db.Database("shares.db", [
    """CREATE TABLE IF NOT EXISTS shares (id TEXT PRIMARY KEY, token TEXT UNIQUE, owner TEXT NOT NULL,
           lesson_id TEXT NOT NULL, active INTEGER NOT NULL, show_author INTEGER NOT NULL,
           downloadable INTEGER NOT NULL, listing TEXT NOT NULL DEFAULT 'none', asked REAL, listed_at REAL,
           changed INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL,
           UNIQUE (owner, lesson_id));
       CREATE TABLE IF NOT EXISTS readers (share_id TEXT NOT NULL, reader TEXT NOT NULL, first REAL NOT NULL,
           last REAL NOT NULL, reached TEXT, finished TEXT NOT NULL DEFAULT '[]',
           completed INTEGER NOT NULL DEFAULT 0, anonymous INTEGER NOT NULL DEFAULT 0,
           hidden INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (share_id, reader));
       CREATE INDEX IF NOT EXISTS readers_reader ON readers (reader);""",
], rows=True, synchronous="NORMAL")
_tx = DB.tx


def _share(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in ("active", "show_author", "downloadable", "changed"):
        d[k] = bool(d[k])
    return d


def _reader(row) -> dict:
    d = dict(row)
    d["finished"] = json.loads(d["finished"] or "[]")
    for k in ("completed", "anonymous", "hidden"):
        d[k] = bool(d[k])
    return d


# ---------------------------------------------------------------- the author's side


def get(owner: str, lesson_id: str) -> dict | None:
    """The lesson's share, live or stopped, or None if it was never shared."""
    with _tx() as con:
        return _share(con.execute("SELECT * FROM shares WHERE owner = ? AND lesson_id = ?", (owner, lesson_id)).fetchone())


def for_owner(owner: str) -> dict[str, dict]:
    """Every live share of an account's lessons, by lesson id, with its reader count."""
    with _tx() as con:
        rows = con.execute("""SELECT shares.*, (SELECT COUNT(*) FROM readers WHERE readers.share_id = shares.id) AS reader_count
                              FROM shares WHERE owner = ? AND active = 1""", (owner,)).fetchall()
    return {r["lesson_id"]: {**_share(r), "reader_count": r["reader_count"]} for r in rows}


def share(owner: str, lesson_id: str, show_author: bool | None = None, downloadable: bool | None = None, listed: bool | None = None) -> dict:
    """Shares the lesson, or changes how it is shared. A lesson shared again after it stopped gets a new link.

    `listed` asks for the gallery (a review first), or leaves it; asking again after a refusal changes nothing until
    the author has unticked it once."""
    now = time.time()
    with _tx() as con:
        row = _share(con.execute("SELECT * FROM shares WHERE owner = ? AND lesson_id = ?", (owner, lesson_id)).fetchone())
        if row is None:
            row = {"id": uuid.uuid4().hex[:12], "token": None, "owner": owner, "lesson_id": lesson_id, "active": False,
                   "show_author": True, "downloadable": False, "listing": "none", "asked": None, "listed_at": None,
                   "changed": False, "created": now, "updated": now}
            con.execute("""INSERT INTO shares (id, token, owner, lesson_id, active, show_author, downloadable, listing, created, updated)
                           VALUES (?, NULL, ?, ?, 0, 1, 0, 'none', ?, ?)""", (row["id"], owner, lesson_id, now, now))
        if not row["active"]:
            row.update(active=True, token=secrets.token_urlsafe(16))
        if show_author is not None:
            row["show_author"] = show_author
        if downloadable is not None:
            row["downloadable"] = downloadable
        if listed is True and row["listing"] == "none":
            row.update(listing="waiting", asked=now, changed=False)
        elif listed is False:
            row.update(listing="none", listed_at=None, changed=False)
        con.execute("""UPDATE shares SET token = ?, active = 1, show_author = ?, downloadable = ?, listing = ?, asked = ?,
                       listed_at = ?, changed = ?, updated = ? WHERE id = ?""",
                    (row["token"], int(row["show_author"]), int(row["downloadable"]), row["listing"], row["asked"],
                     row["listed_at"], int(row["changed"]), now, row["id"]))
        return _share(con.execute("SELECT * FROM shares WHERE id = ?", (row["id"],)).fetchone())


def stop(owner: str, lesson_id: str) -> dict | None:
    """Stops sharing: the link stops working at once and the lesson leaves the gallery. Its readers are kept."""
    with _tx() as con:
        con.execute("""UPDATE shares SET active = 0, token = NULL, listing = 'none', listed_at = NULL, changed = 0, updated = ?
                       WHERE owner = ? AND lesson_id = ?""", (time.time(), owner, lesson_id))
        return _share(con.execute("SELECT * FROM shares WHERE owner = ? AND lesson_id = ?", (owner, lesson_id)).fetchone())


def edited(owner: str, lesson_id: str) -> bool:
    """The author saved the lesson again. A listed lesson leaves the gallery until an admin approves it again, flagged
    as changed since it was listed (so an approved lesson can't be swapped for something else); it stays shared by
    link. True when the lesson is now waiting for review."""
    with _tx() as con:
        con.execute("""UPDATE shares SET listing = 'waiting', changed = 1, asked = ?, listed_at = NULL, updated = ?
                       WHERE owner = ? AND lesson_id = ? AND active = 1 AND listing = 'listed'""", (time.time(), time.time(), owner, lesson_id))
        row = con.execute("SELECT listing FROM shares WHERE owner = ? AND lesson_id = ? AND active = 1", (owner, lesson_id)).fetchone()
    return bool(row) and row["listing"] == "waiting"


def delete_for_lesson(owner: str, lesson_id: str):
    with _tx() as con:
        for (sid,) in con.execute("SELECT id FROM shares WHERE owner = ? AND lesson_id = ?", (owner, lesson_id)).fetchall():
            con.execute("DELETE FROM readers WHERE share_id = ?", (sid,))
        con.execute("DELETE FROM shares WHERE owner = ? AND lesson_id = ?", (owner, lesson_id))


def delete_for_account(user_id: str) -> int:
    """Removes everything an account shared, with its readers, and the account's own reading of others' lessons."""
    with _tx() as con:
        owned = [sid for (sid,) in con.execute("SELECT id FROM shares WHERE owner = ?", (user_id,)).fetchall()]
        for sid in owned:
            con.execute("DELETE FROM readers WHERE share_id = ?", (sid,))
        con.execute("DELETE FROM shares WHERE owner = ?", (user_id,))
        con.execute("DELETE FROM readers WHERE reader = ?", (user_id,))
    return len(owned)


# ---------------------------------------------------------------- readers


def by_token(token: str) -> dict | None:
    """The live share a link belongs to, or None."""
    if not token:
        return None
    with _tx() as con:
        return _share(con.execute("SELECT * FROM shares WHERE token = ? AND active = 1", (token,)).fetchone())


def by_id(share_id: str) -> dict | None:
    with _tx() as con:
        return _share(con.execute("SELECT * FROM shares WHERE id = ?", (share_id,)).fetchone())


def reader(share_id: str, reader_id: str) -> dict | None:
    with _tx() as con:
        row = con.execute("SELECT * FROM readers WHERE share_id = ? AND reader = ?", (share_id, reader_id)).fetchone()
    return _reader(row) if row else None


def opened(share_id: str, reader_id: str, anonymous: bool):
    """A reader opened the lesson. Once anonymous (opened while listed), always anonymous. It is back on their list."""
    now = time.time()
    with _tx() as con:
        con.execute("""INSERT INTO readers (share_id, reader, first, last, anonymous) VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT (share_id, reader) DO UPDATE SET last = excluded.last, hidden = 0,
                       anonymous = MAX(anonymous, excluded.anonymous)""", (share_id, reader_id, now, now, int(anonymous)))


def progressed(share_id: str, reader_id: str, reached: str | None, finished: list[str], completed: bool, anonymous: bool):
    """How far a reader got: the furthest concept reached, the concepts finished, and whether the lesson is done. The
    first report records the reader (and puts it back on their list if they had removed it)."""
    now = time.time()
    with _tx() as con:
        con.execute("""INSERT INTO readers (share_id, reader, first, last, reached, finished, completed, anonymous)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT (share_id, reader) DO UPDATE SET last = excluded.last, reached = excluded.reached,
                       finished = excluded.finished, completed = excluded.completed, hidden = 0,
                       anonymous = MAX(anonymous, excluded.anonymous)""",
                    (share_id, reader_id, now, now, reached, json.dumps(finished), int(completed), int(anonymous)))


def readers(share_id: str) -> list[dict]:
    """A share's readers, the most recent first."""
    with _tx() as con:
        rows = con.execute("SELECT * FROM readers WHERE share_id = ? ORDER BY last DESC, first DESC", (share_id,)).fetchall()
    return [_reader(r) for r in rows]


def shared_with(reader_id: str) -> list[tuple[dict, dict]]:
    """The live shares a reader opened and hasn't removed from their list, most recently read first."""
    with _tx() as con:
        rows = con.execute("""SELECT shares.*, readers.last AS read_last FROM readers JOIN shares ON shares.id = readers.share_id
                              WHERE readers.reader = ? AND readers.hidden = 0 AND shares.active = 1 AND shares.owner != ?
                              ORDER BY readers.last DESC""", (reader_id, reader_id)).fetchall()
    return [(_share(r), {"last": r["read_last"]}) for r in rows]


def hide(share_id: str, reader_id: str):
    with _tx() as con:
        con.execute("UPDATE readers SET hidden = 1 WHERE share_id = ? AND reader = ?", (share_id, reader_id))


# ---------------------------------------------------------------- the gallery


def listed() -> list[dict]:
    """The lessons listed in the gallery, most recently listed first."""
    with _tx() as con:
        rows = con.execute("SELECT * FROM shares WHERE active = 1 AND listing = 'listed' ORDER BY listed_at DESC").fetchall()
    return [_share(r) for r in rows]


def listings(status: str) -> list[dict]:
    """Live shares in one state of review: waiting (oldest first), listed or rejected (newest first)."""
    order = "asked ASC" if status == "waiting" else "updated DESC"
    with _tx() as con:
        rows = con.execute(f"SELECT * FROM shares WHERE active = 1 AND listing = ? ORDER BY {order}", (status,)).fetchall()
    return [_share(r) for r in rows]


def count_waiting() -> int:
    with _tx() as con:
        return con.execute("SELECT COUNT(*) FROM shares WHERE active = 1 AND listing = 'waiting'").fetchone()[0]


def review(share_id: str, action: str) -> dict | None:
    """An admin's decision. Raises ValueError when the share isn't in a state the action applies to."""
    share_row = by_id(share_id)
    if share_row is None or not share_row["active"]:
        return None
    now, listing = time.time(), share_row["listing"]
    if action == "approve" and listing in ("waiting", "rejected"):
        change = {"listing": "listed", "listed_at": now, "changed": 0}
    elif action == "reject" and listing in ("waiting", "listed"):
        change = {"listing": "rejected", "listed_at": None, "changed": 0}
    elif action == "remove" and listing == "listed":
        change = {"listing": "rejected", "listed_at": None, "changed": 0}
    elif action == "checked" and listing == "listed":
        change = {"changed": 0}
    else:
        raise ValueError("This lesson isn't waiting for that any more. Reload the list.")
    sets = ", ".join(f"{k} = ?" for k in change)
    with _tx() as con:
        con.execute(f"UPDATE shares SET {sets}, updated = ? WHERE id = ?", (*change.values(), now, share_id))
    return by_id(share_id)
