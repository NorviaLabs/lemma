"""Sharing a lesson by link and in the gallery's community section (see shares.py): the author's settings and what
they see of readers, what a reader gets, and their progress."""

from __future__ import annotations

import json
import re

from .. import auth, export, shares, store
from .core import ApiError, NO_SOURCE, Request, _library_key, ensure_checked, route
from .gallery import card_quote, gallery_cover, quote_author


SHARE_SETTINGS = ("show_author", "downloadable", "listed")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
GONE = "This lesson is no longer shared. Ask whoever sent the link for a new one."


def _checked(owner: str, lesson_id: str, lesson: dict, account: str | None = None):
    """A saved lesson passes its checks before anyone but its author reads it: once per version, known by its files,
    so its source is read only when the checks actually run."""
    ensure_checked(lambda: (lesson, store.read_source(lesson_id, owner)), _library_key(owner, lesson_id), account)


def _own_lesson(req: Request, lesson_id) -> tuple[dict, str | None]:
    try:
        return store.load_lesson(lesson_id, req.owner())
    except (KeyError, OSError, ValueError):
        raise ApiError(404, "That lesson isn't in your library.") from None


def _reader(req: Request) -> dict:
    if not req.user:
        raise ApiError(401, "Sign in to read this lesson. It's free, and you don't need an AI provider key.")
    return req.user


def _name(user_id: str, names: dict | None = None) -> str:
    profile = names.get(user_id) if names is not None else auth.user(user_id)
    return (profile or {}).get("name") or "A reader"


def _author(share, names: dict | None = None) -> str | None:
    """The name readers see, or None when the author chose not to show it. `names` holds profiles already looked up."""
    return _name(share["owner"], names) if share["show_author"] else None


def _live(token) -> tuple[dict, dict, str | None]:
    """The live share a link belongs to, with its lesson as the author last saved it, checked before anyone reads it."""
    share = shares.by_token(token) if isinstance(token, str) and TOKEN_RE.match(token) else None
    if share is None:
        raise ApiError(404, GONE)
    try:
        lesson = store.read_lesson(share["lesson_id"], share["owner"])  # parsed once per version of its file: read only
    except (KeyError, OSError, ValueError):
        raise ApiError(404, GONE) from None
    lesson = {k: v for k, v in lesson.items() if k != "plan"}
    _checked(share["owner"], share["lesson_id"], lesson)
    return share, lesson, None


def _category(lesson) -> str:
    return store._category_name(lesson)


def _for_readers(share, lesson, user_id: str | None, named: bool) -> dict:
    """The lesson as a reader gets it: no source text, none of the author's own notes, and not the author's library id."""
    out = {k: v for k, v in json.loads(json.dumps(lesson)).items() if k not in ("plan", "shared")}
    intro = dict(out.get("intro") or {})
    intro.pop("known", None)  # what the author said they already know, and the question they asked, are theirs
    intro.pop("question", None)
    out["intro"] = intro
    out["id"] = f"s-{share['id']}"
    out["shared"] = {"id": share["id"], "token": share["token"], "author": _author(share), "downloadable": share["downloadable"],
                     "listed": share["listing"] == "listed", "owner": user_id == share["owner"], "named": named}
    return out


def _readers(share, lesson) -> dict:
    """What the author sees: totals, then each reader by name with how far they got; while the lesson is listed in the
    gallery, totals and how many reached each concept only. Someone who found it in the gallery is never named."""
    rows = shares.readers(share["id"]) if share else []
    ids = [c["id"] for c in lesson.get("concepts") or []]

    def reached(r):
        return len(ids) if r["completed"] else (ids.index(r["reached"]) + 1 if r["reached"] in ids else 0)

    listed = bool(share and share["active"] and share["listing"] == "listed")
    out = {"count": len(rows), "reading": sum(1 for r in rows if not r["completed"] and reached(r) > 0),
           "finished": sum(1 for r in rows if r["completed"]), "named": not listed}
    if listed:
        out.update(people=[], others=len(rows),
                   by_concept=[{"id": c["id"], "title": c["title"], "reached": sum(1 for r in rows if reached(r) > i)}
                               for i, c in enumerate(lesson.get("concepts") or [])])
    else:
        named = [r for r in rows if not r["anonymous"]]
        names = auth.users(r["reader"] for r in named)  # one query, however many readers
        out.update(others=len(rows) - len(named),
                   people=[{"name": _name(r["reader"], names), "reached": reached(r), "total": len(ids), "completed": r["completed"], "last": r["last"]}
                           for r in named])
    return out


def _share_view(share, lesson) -> dict:
    live = bool(share and share["active"])
    out = {"shared": live, "show_author": share["show_author"] if share else True, "downloadable": share["downloadable"] if share else False,
           "listing": share["listing"] if live else "none", "readers": _readers(share, lesson)}
    if live:
        out["token"] = share["token"]
    return out


@route("GET", r"/api/lessons/([A-Za-z0-9_-]{1,64})/share")
def api_share_get(req, lesson_id):
    lesson, _ = _own_lesson(req, lesson_id)
    return _share_view(shares.get(req.owner(), lesson_id), lesson)


@route("POST", r"/api/lessons/([A-Za-z0-9_-]{1,64})/share")
def api_share_set(req, lesson_id):
    body = req.body
    settings = {}
    for key in SHARE_SETTINGS:
        if key in body:
            if not isinstance(body[key], bool):
                raise ApiError(400, f"{key} must be true or false.")
            settings[key] = body[key]
    lesson, source = _own_lesson(req, lesson_id)
    if not source:
        raise ApiError(409, NO_SOURCE)
    owner = req.owner()
    _checked(owner, lesson_id, {k: v for k, v in lesson.items() if k != "plan"}, account=owner)  # only a lesson that passes its checks is shared
    return _share_view(shares.share(owner, lesson_id, **settings), lesson)


@route("DELETE", r"/api/lessons/([A-Za-z0-9_-]{1,64})/share")
def api_share_stop(req, lesson_id):
    lesson, _ = _own_lesson(req, lesson_id)
    return _share_view(shares.stop(req.owner(), lesson_id), lesson)


@route("GET", r"/api/shared/([A-Za-z0-9_-]{20,64})/about")
def api_shared_about(req, token):
    """For the sign-in page: what the lesson is and who shared it. Anyone with the link may ask."""
    share, lesson, _ = _live(token)
    return {"title": lesson.get("title", ""), "author": _author(share), "concepts": len(lesson.get("concepts") or []),
            "category": _category(lesson), "named": share["listing"] != "listed"}


@route("GET", r"/api/shared/([A-Za-z0-9_-]{20,64})")
def api_shared_open(req, token):
    user = _reader(req)
    share, lesson, _ = _live(token)
    owner = user["id"] == share["owner"]
    listed = share["listing"] == "listed"
    # Opening records nothing (another site can cause a page load): a reader is recorded when they start, by the
    # app's first progress report, after they've been told what the author sees.
    mine = None if owner else shares.reader(share["id"], user["id"])
    return _for_readers(share, lesson, user["id"], named=not listed and not (mine and mine["anonymous"]))


@route("POST", r"/api/shared/([A-Za-z0-9_-]{20,64})/progress")
def api_shared_progress(req, token):
    user = _reader(req)
    share, lesson, _ = _live(token)
    body = req.body
    ids = [c["id"] for c in lesson.get("concepts") or []]
    reached, finished, completed = body.get("reached"), body.get("finished", []), body.get("completed", False)
    told_anonymous = body.get("anonymous", False)  # what the reader was told when they opened it
    if not isinstance(told_anonymous, bool):
        raise ApiError(400, "anonymous must be true or false.")
    if reached is not None and (not isinstance(reached, str) or reached not in ids):
        raise ApiError(400, "reached must be one of the lesson's concepts.")
    if (not isinstance(finished, list) or len(finished) > len(ids) or not all(isinstance(x, str) and x in ids for x in finished)
            or len(set(finished)) != len(finished)):
        raise ApiError(400, "finished must list the lesson's concepts, each once.")
    if not isinstance(completed, bool):
        raise ApiError(400, "completed must be true or false.")
    if user["id"] != share["owner"]:  # the author's own reading isn't counted
        shares.progressed(share["id"], user["id"], reached, finished, completed, anonymous=share["listing"] == "listed" or told_anonymous)
    return {"ok": True}


@route("GET", r"/api/shared")
def api_shared_list(req):
    user = _reader(req)
    items = []
    found = shares.shared_with(user["id"])
    names = auth.users(share["owner"] for share, _ in found if share["show_author"])
    for share, read in found:
        try:
            lesson = store.read_lesson(share["lesson_id"], share["owner"])
        except (KeyError, OSError, ValueError):
            continue
        items.append({"token": share["token"], "title": lesson.get("title", ""), "source": (lesson.get("source") or {}).get("title", ""),
                      "author": _author(share, names), "concepts": len(lesson.get("concepts") or []), "category": _category(lesson),
                      "downloadable": share["downloadable"], "opened": read["last"], "share": share["id"]})
    return items


@route("POST", r"/api/shared/([A-Za-z0-9_-]{20,64})/hide")
def api_shared_hide(req, token):
    user = _reader(req)
    share, _, _ = _live(token)
    shares.hide(share["id"], user["id"])
    return {"ok": True}


def _export_shared(req: Request, token):
    user = _reader(req)
    share, lesson, source = _live(token)
    if not share["downloadable"] and user["id"] != share["owner"]:
        raise ApiError(403, "The author hasn't allowed downloads of this lesson.")
    copy_ = _for_readers(share, lesson, user["id"], named=False)
    copy_.pop("shared", None)  # the offline file doesn't carry the link
    return export.lesson_html(copy_)


@route("GET", r"/api/gallery/community")
def api_gallery_community(req):
    """The lessons people shared that an admin listed, as gallery cards. Anyone may see them; reading one needs an account."""
    items = []
    listed = shares.listed()
    names = auth.users(share["owner"] for share in listed if share["show_author"])
    for share in listed:
        try:
            share, lesson, _ = _live(share["token"])
        except ApiError:
            continue
        cover = gallery_cover(lesson) if lesson.get("concepts") else None
        items.append({"token": share["token"], "title": lesson.get("title", ""), "source": lesson.get("source") or {}, "author": _author(share, names),
                      "field": _category(lesson), "concepts": [c["title"] for c in lesson.get("concepts") or []],
                      "cover": cover and {"title": cover["title"], "idea": cover["idea"], "model": cover.get("model"),
                                          "quote": card_quote((cover.get("understand") or {}).get("quote")),
                                          "quote_author": quote_author(lesson, cover.get("understand") or {}), "values": {}}})
    return items
