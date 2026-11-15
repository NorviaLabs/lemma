"""Searching for sources: each search runs in the background, and its level is remembered per field."""

from __future__ import annotations

import threading
import time
import uuid

from .. import categorize, jev, levels, logs, metrics, search, store
from . import core
from .core import ApiError, _lock, _parse_level, route


# Searches run in the background so the page can show each library answering and each source being checked.
SEARCHES: dict[str, dict] = {}
SEARCHES_EACH = 3  # searches one account can have running at once
SEARCH_NEEDS_PROVIDER = "Connect an AI provider on your account page to search. OpenLemma uses it to work out what to look up."


def _field(body) -> dict | None:
    """A field the learner chose for a search, in place of Jev's pick: one or two categories."""
    ids = body.get("field")
    if ids is None:
        return None
    if not (isinstance(ids, list) and 1 <= len(ids) <= 2 and len(set(ids)) == len(ids)
            and all(isinstance(i, str) and i in categorize.CATEGORIES and i != "other" for i in ids)):
        raise ApiError(400, "Choose a field from the list.")
    return categorize.chosen_field(ids)


def _saved_level(owner: str, field: dict) -> str:
    """The level the account last searched this field at, else the last level it used anywhere."""
    saved = store.settings(owner)
    for cid in field["ids"]:
        if (saved.get("levels") or {}).get(cid) in levels.LEVELS:
            return saved["levels"][cid]
    return saved.get("level") if saved.get("level") in levels.LEVELS else levels.DEFAULT


def _remember_level(owner: str, level: str, field: dict | None):
    per = dict(store.settings(owner).get("levels") or {})
    per.update({cid: level for cid in (field or {}).get("ids", [])})
    store.save_settings(owner, level=level, levels=per)


@route("POST", r"/api/search")
def api_search(req):
    body = req.body
    owner = req.owner()
    # A level the learner set for this search wins, and is remembered for its field. Without one, the search
    # uses the level saved for the field Jev places the question in, which may only be known once it runs.
    chose_level = body.get("level") not in (None, "")
    level = _parse_level(body) if chose_level else None
    field = _field(body)
    # The learner's provider names what to look up, so a search needs one, as a build does. It is made here, before
    # the search starts in its own thread, so a missing or unusable one is said at once.
    try:
        provider = core._provider(req)
    except ApiError as e:
        raise ApiError(e.status, SEARCH_NEEDS_PROVIDER if e.status == 400 else e.message) from None
    query = str(body.get("query", ""))
    try:
        query = search.clean(query)
        if level is None and (known := field or search.field_of(query, ask=False)):
            level = _saved_level(owner, known)
        if level and (hit := search.cached(query, level, field)):
            if chose_level:
                _remember_level(owner, level, hit.get("field"))
            return {"done": True, "result": hit}
        if not jev.available():
            raise search.SearchError(jev.MISSING)
    except search.SearchError as e:
        raise ApiError(422, str(e)) from None
    with _lock:
        for sid in [k for k, s in SEARCHES.items() if s["done"] and time.time() - s["created"] > 600]:
            SEARCHES.pop(sid)
        if sum(s["owner"] == owner and not s["done"] for s in SEARCHES.values()) >= SEARCHES_EACH:
            raise ApiError(429, "Several searches are still running. Wait a moment and try again.")
        if not metrics.take(owner, "search"):
            raise ApiError(429, f"You've used today's {metrics.limit('search')} searches. They reset at midnight UTC.")
        sid = uuid.uuid4().hex[:12]
        record = SEARCHES[sid] = {"owner": owner, "query": query, "done": False, "progress": None, "result": None, "error": "", "created": time.time()}
    metrics.count("search")

    def progress(snapshot):
        record["progress"] = snapshot

    def run():
        try:
            at = level
            if at is None:
                progress({"planning": "active", "services": {}, "found": {}, "to_check": 0, "checked": 0, "readable": 0})
                at = _saved_level(owner, search.field_of(query))
            record["result"] = search.search(query, at, provider, progress, field)
            if chose_level:
                _remember_level(owner, at, record["result"].get("field"))
        except search.SearchError as e:
            record["error"] = str(e)
        except Exception as e:  # keep the server alive and tell the learner honestly
            record["error"] = f"The search failed unexpectedly ({e.__class__.__name__}, error {logs.report('search', e)})."
        finally:
            record["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return api_search_status(req, sid)


@route("GET", r"/api/search/([a-f0-9]{12})")
def api_search_status(req, sid):
    record = SEARCHES.get(sid)
    if not record or record["owner"] != req.owner():
        raise ApiError(404, "That search has finished or expired. Search again.")
    return {"id": sid, "query": record["query"], "done": record["done"], "progress": record["progress"],
            "result": record["result"], "error": record["error"]}
