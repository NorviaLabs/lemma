"""An account's own library: saving, listing, opening, deleting and downloading its lessons."""

from __future__ import annotations

from .. import checks, export, generate, shares, store
from .builds import _requests_lock
from .core import ApiError, NO_SOURCE, _library_key, ensure_checked, load_example, load_gallery, route, source_for
from .gallery import _example_key, _gallery_key
from .sharing import _export_shared


@route("POST", r"/api/lessons")
def api_save(req):
    body = req.body
    lesson = body.get("lesson")
    if not isinstance(lesson, dict):
        raise ApiError(400, "No lesson to save.")
    if lesson.get("example"):
        raise ApiError(400, "The example lesson is built in and can't be saved or edited.")
    lid = str(lesson.get("id") or "")
    if not store.ID_RE.match(lid):
        raise ApiError(400, "This lesson has no valid id.")
    owner = req.owner()
    source = source_for(lid, owner) or None
    if source is None:
        raise ApiError(409, NO_SOURCE)
    lesson = {k: v for k, v in lesson.items() if k not in ("plan", "shared")}
    ensure_checked(lambda: (lesson, source), account=owner)  # a version saved before, or exported, was checked already
    store.save_lesson(lesson, source, owner)
    review = shares.edited(owner, lid)  # readers by link see it at once; a listed lesson leaves the gallery until approved again
    checks.remember(lesson, source, [], _library_key(owner, lid))  # just checked: known by its new files, so no reader waits
    return {"ok": True, "id": lid, "review": review}


@route("GET", r"/api/lessons")
def api_lessons(req):
    owner = req.owner()
    shared = shares.for_owner(owner)
    return [{**row, "shared": {"listing": shared[row["id"]]["listing"], "readers": shared[row["id"]]["reader_count"]} if row["id"] in shared else None}
            for row in store.list_lessons(owner)]


@route("GET", r"/api/lessons/([A-Za-z0-9_-]{1,64})")
def api_lesson(req, lesson_id):
    try:
        return store.load_lesson(lesson_id, req.owner())[0]
    except (KeyError, OSError, ValueError):
        raise ApiError(404, "That lesson isn't in your library.") from None


@route("DELETE", r"/api/lessons/([A-Za-z0-9_-]{1,64})")
def api_lesson_delete(req, lesson_id):
    owner = req.owner()
    try:
        with _requests_lock:
            job = generate.JOBS.get(lesson_id)
            if job and job.owner == owner and job.status == "running":
                raise ApiError(409, "This lesson is still building. Cancel the build first, then delete it.")
            store.delete_lesson(lesson_id, owner)
            shares.delete_for_lesson(owner, lesson_id)  # its link stops working, and its readers go with it
            generate.JOBS.pop(lesson_id, None)
            store.request_path(lesson_id, owner).unlink(missing_ok=True)
            store.BuiltConcepts(lesson_id, owner).clear()
    except KeyError:
        raise ApiError(404, "That lesson isn't in your library.") from None
    return {"ok": True}


@route("POST", r"/api/export")
def api_export(req):
    body = req.body
    if "shared" in body:
        return _export_shared(req, body.get("shared"))
    lesson = body.get("lesson")
    if not isinstance(lesson, dict):
        raise ApiError(400, "No lesson to export.")
    # Shipped lessons are exported as shipped, never as sent, so anyone may download them without
    # the server checking a model a stranger wrote.
    known_as = None
    if isinstance(lesson.get("gallery"), dict):
        slug = str(lesson["gallery"].get("slug", ""))
        lesson, source = load_gallery(slug)
        known_as = _gallery_key(slug)
    elif lesson.get("example"):
        lesson, source = load_example()
        known_as = _example_key()
    else:
        source = source_for(str(lesson.get("id", "")), req.owner())
        if not source:
            raise ApiError(409, NO_SOURCE)
    lesson = {k: v for k, v in lesson.items() if k not in ("plan", "shared")}
    ensure_checked(lambda: (lesson, source), known_as, account=None if known_as else req.owner())  # a lesson sent by a person: theirs to pay for
    return export.lesson_html(lesson)
