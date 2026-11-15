"""For the accounts named in LEMMA_ADMINS: daily counts, the feedback sent, and reviewing lessons asked to be listed in
the gallery. Anyone else gets the answer an unknown address gets."""

from __future__ import annotations

from .. import auth, feedback, metrics, shares, store
from .core import ApiError, route
from .sharing import _category, _for_readers, _live


@route("GET", r"/api/stats")
def api_stats(req):
    """Daily counts, for the accounts named in LEMMA_ADMINS."""
    req.admin()
    return metrics.report()


@route("GET", r"/api/feedback")
def api_feedback_list(req):
    """Every account's feedback, newest first, for LEMMA_ADMINS; `?status=new` or `done` keeps only those."""
    req.admin()
    status = req.param("status")
    if status is not None and status not in feedback.STATUSES:
        raise ApiError(400, "Status must be new or done.")
    return feedback.items(status)


@route("POST", r"/api/feedback/([a-f0-9]{12})/status")
def api_feedback_status(req, fid):
    req.admin()
    status = req.body.get("status")
    if status not in feedback.STATUSES:
        raise ApiError(400, "Status must be new or done.")
    if not feedback.set_status(fid, status):
        raise ApiError(404, "That feedback isn't there anymore.")
    return {"id": fid, "status": status}


@route("DELETE", r"/api/feedback/([a-f0-9]{12})")
def api_feedback_delete(req, fid):
    req.admin()
    if not feedback.delete(fid):
        raise ApiError(404, "That feedback isn't there anymore.")
    return {"ok": True}


REVIEW_STATES = ("waiting", "listed", "rejected")


@route("GET", r"/api/admin/listings")
def api_admin_listings(req):
    req.admin()
    status = req.param("status", "waiting")
    if status not in REVIEW_STATES:
        raise ApiError(400, "Choose waiting, listed or rejected.")
    items = []
    found = shares.listings(status)
    owners = auth.users(share["owner"] for share in found)
    for share in found:
        try:
            lesson = store.read_lesson(share["lesson_id"], share["owner"])
        except (KeyError, OSError, ValueError):
            continue
        owner = owners.get(share["owner"]) or {}
        items.append({"id": share["id"], "token": share["token"], "title": lesson.get("title", ""), "author": owner.get("name", ""),
                      "email": owner.get("email", ""), "field": _category(lesson), "concepts": len(lesson.get("concepts") or []),
                      "changed": share["changed"], "asked": share["asked"], "listed_at": share["listed_at"], "listing": share["listing"]})
    return items


@route("POST", r"/api/admin/listings/([a-f0-9]{12})")
def api_admin_listing(req, share_id):
    req.admin()
    action = req.body.get("action")
    if action not in shares.ACTIONS:
        raise ApiError(400, "Choose approve, reject, remove or checked.")
    pending = shares.by_id(share_id)
    if action == "approve" and pending and pending["active"]:
        _live(pending["token"])  # checked now, so the gallery never waits for it (and a lesson that fails isn't listed)
    try:
        share = shares.review(share_id, action)
    except ValueError as e:
        raise ApiError(409, str(e)) from None
    if share is None:
        raise ApiError(404, "That lesson isn't shared any more.")
    return {"id": share["id"], "listing": share["listing"], "changed": share["changed"]}


@route("GET", r"/api/admin/listings/([a-f0-9]{12})/lesson")
def api_admin_listing_lesson(req, share_id):
    """An admin's preview: the lesson as readers get it, without counting the admin as a reader."""
    req.admin()
    share = shares.by_id(share_id)
    if not share or not share["active"]:
        raise ApiError(404, "That lesson isn't shared any more.")
    share, lesson, _ = _live(share["token"])
    out = _for_readers(share, lesson, req.user["id"], named=False)
    out["shared"]["preview"] = True  # an admin reviewing it: not a reader, so told nothing meant for readers
    return out
