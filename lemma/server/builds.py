"""Bringing sources and building lessons from them: reading links and uploads, the durable build requests (outline,
review, build, cancel, retry, continue) and the caps on how many run at once."""

from __future__ import annotations

import base64
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from urllib.parse import urlsplit

from .. import categorize, checks, generate, ingest, jev, lesson as L, levels, metrics, search, store
from . import core
from .core import ApiError, Request, _library_key, _lock, _parse_level, route


PAPERS: dict[str, dict] = {}  # paper_id -> {text, title, url, kind, pages, owner}
KEEP_PAPERS = 5  # papers kept per person
READING_EACH, READING = 2, 6  # links and uploads being read at once, per account and in all, when hosted
_reading: dict[str | None, int] = {}
SOURCE_READERS = 4  # sources of one request read at the same time
MAX_RUNNING_EACH, MAX_RUNNING = 2, 8  # outlines and builds running at once, per account and in all, when hosted


@contextmanager
def _reading_slot(owner):
    """Hold one of the account's reading slots while a link or upload is read, so a few slow ones can't use up the server."""
    with _lock:
        if _reading.get(owner, 0) >= READING_EACH:
            raise ApiError(429, "You already have sources being read. Wait for them to finish, then try again.")
        if sum(_reading.values()) >= READING:
            raise ApiError(503, "OpenLemma is busy reading other people's sources. Please try again in a minute.")
        _reading[owner] = _reading.get(owner, 0) + 1
    try:
        yield
    finally:
        with _lock:
            _reading[owner] -= 1
            if not _reading[owner]:
                del _reading[owner]


@route("POST", r"/api/papers")
def api_papers(req):
    body = req.body
    owner = req.owner()
    if not metrics.take(owner, "read"):
        raise ApiError(429, f"You've read today's {metrics.limit('read')} sources. They reset at midnight UTC.")
    with _reading_slot(owner):
        paper = _read_paper(body)
    pid = uuid.uuid4().hex[:12]
    with _lock:
        PAPERS[pid] = {"text": paper.text, "title": paper.title, "url": paper.url, "kind": paper.kind, "pages": paper.pages, "owner": owner}
        mine = [k for k, v in PAPERS.items() if v["owner"] == owner]
        for k in mine[:-KEEP_PAPERS]:
            PAPERS.pop(k)
    return {"paper_id": pid, "title": paper.title, "kind": paper.kind, "pages": paper.pages, "chars": len(paper.text), "url": paper.url}


def _read_paper(body) -> ingest.Paper:
    try:
        if isinstance(body.get("urls"), list) and body["urls"]:
            paper = _first_readable([str(u) for u in body["urls"][:5]])
        elif body.get("url"):
            paper = ingest.from_url(str(body["url"]))
        elif body.get("data"):
            try:
                data = base64.b64decode(body["data"], validate=False)
            except ValueError:
                raise ApiError(400, "The uploaded file couldn't be decoded.") from None
            if len(data) > ingest.MAX_BYTES:
                raise ApiError(413, "That file is larger than 40 MB.")
            if len(data) > ingest.MAX_PAGE_BYTES and not data.startswith(b"%PDF-"):
                raise ApiError(413, "That file is larger than 10 MB. Only PDFs can be up to 40 MB.")
            paper = ingest.from_bytes(data, filename=str(body.get("filename", "")), content_type=str(body.get("content_type", "")))
        else:
            raise ApiError(400, "Paste a link or choose a file.")
    except ingest.IngestError as e:
        raise ApiError(422, str(e)) from None
    return paper


_first_readable = ingest.first_readable


def _paper(body, owner: str) -> dict:
    p = PAPERS.get(str(body.get("paper_id", "")))
    if not p or p["owner"] != owner:
        raise ApiError(404, "OpenLemma no longer has that source in memory. Please bring it again.")
    return p


def _new_job(owner: str, kind: str, job_id: str | None = None) -> generate.Job:
    """`owner`'s job, counted against the running caps and registered in the same step, so parallel requests can't
    both fit."""
    if not jev.available():  # every outline and build is checked by Jev; without it, nothing is started or paid for
        raise ApiError(503, jev.MISSING)
    with _lock:
        running = [j for j in list(generate.JOBS.values()) if j.status == "running"]
        if sum(j.owner == owner for j in running) >= MAX_RUNNING_EACH:
            raise ApiError(429, "You already have lessons building. Wait for one to finish, or cancel it.")
        if len(running) >= MAX_RUNNING:
            raise ApiError(503, "OpenLemma is busy building other people's lessons. Please try again in a few minutes.")
        if not metrics.take(owner, "job"):
            raise ApiError(429, f"You've used today's {metrics.limit('job')} outlines and builds. They reset at midnight UTC.")
        job = generate.Job(kind)
        job.owner = owner
        if job_id:
            job.id = job_id
        generate.JOBS[job.id] = job
    return job


def _forget(job: generate.Job):
    """Unregister a job that failed before its thread started, so it never counts as running."""
    with _lock:
        if generate.JOBS.get(job.id) is job:
            del generate.JOBS[job.id]


def _start(job: generate.Job, fn, *args):
    try:
        generate.start(job, fn, *args)
    except BaseException:
        _forget(job)
        raise


# Durable requests reuse the local thread runner; disk is the recovery boundary, not a queue.
_requests_lock = threading.RLock()


def _request_record(rid, owner):
    try:
        record = store.load_request(rid, owner)
    except (KeyError, OSError, ValueError):
        raise ApiError(404, "That lesson build wasn't found.") from None
    job = generate.JOBS.get(rid)
    if record["status"] == "running" and not (job and job.owner == owner):
        lesson = _saved_lesson(rid, owner)
        if lesson:  # saved just before the server stopped: the build had finished, it just hadn't said so yet
            record.update(status="done", error="", result=lesson)
            for step in record.get("steps") or []:
                if step.get("id") == "save":
                    step.update(state="done", detail="Saved to your library")
            store.BuiltConcepts(rid, owner).clear()  # the saved lesson has them all
        else:
            record.update(status="interrupted", error="The server stopped during this build." + (
                "" if _approved(record) else " Retry to start a new attempt."))  # with an approved outline, the page offers the choice
            _stop_steps(record)
        store.save_request(record, owner)
    return record


def _saved_lesson(rid, owner) -> dict | None:
    """The lesson a build saved, if it got that far. A build saves its lesson under its own id, as its very last step."""
    try:
        return store.load_lesson(rid, owner)[0]
    except (KeyError, OSError, ValueError):
        return None


STOPPED = ("error", "cancelled", "interrupted")
NOT_BUILT = {"interrupted": "Not built: the server stopped", "error": "Not built: the build stopped", "cancelled": "Not built: you cancelled the build"}


def _stop_steps(record):
    """A stopped build's steps that never finished say so, rather than looking as if they were still running."""
    if record.get("status") not in STOPPED:
        return
    for step in record.get("steps") or []:
        if step.get("state") in ("active", "waiting"):
            step.update(state="stopped", detail=NOT_BUILT[record["status"]], problems=[])


def _approved(record) -> bool:
    """Whether the build had its outline approved, unchanged since, so it can continue with it."""
    return bool(record.get("outline")) and record.get("approved") == generate.fingerprint(record["outline"])


def _resume(record, owner) -> dict | None:
    """For a stopped build with an approved outline, what continuing it would keep, so the learner can choose between
    continuing and starting over: {"kept", "total", "built_with"}. None when there's no such choice."""
    if record.get("status") not in STOPPED or not _approved(record) or not (record.get("paper") or {}).get("text"):
        return None
    try:
        stored = store.BuiltConcepts(record["id"], owner).load()
    except (KeyError, OSError):
        stored = {}
    summary = generate.saved_summary(stored, record["outline"], record["paper"]["text"], record["request"].get("level", levels.DEFAULT))
    return {**summary, "excluded": [x["title"] for x in record.get("excluded") or []]}  # what Start over would try again


def _public_request(record, owner):
    return {**{k: v for k, v in record.items() if k not in ("paper", "request", "approved")}, "resume": _resume(record, owner)}


def _categorize(record, paper):
    """Stores the lesson's category on its build record. Jev sorts every lesson, so a failure stops the build."""
    try:
        record["category"] = categorize.categorize(paper)
    except categorize.CategorizeError as e:
        raise generate.GenerationError(f"Couldn't sort this lesson into a subject just now ({e}). Retry in a moment.") from None


def _source_context(job, provider, record, paper) -> dict:
    """For sources the learner brought: what they build on, in the shape a search sends with its sources."""
    job.step("subjects", "Working out what your sources build on", "active")
    sources = list(L.source_map(paper["text"]).values()) or [{"title": paper.get("title", ""), "text": paper["text"]}]
    category = record.get("category") or {}
    field = [c["id"] for c in (category.get("primary"), category.get("secondary")) if c and c.get("id") in categorize.CATEGORIES and c["id"] != "other"]
    try:
        found = search.source_subjects(provider, sources, record["request"].get("level", levels.DEFAULT), field)
    except search.SearchError as e:
        job.update("subjects", "failed", str(e))
        raise generate.GenerationError(str(e)) from None
    job.update("subjects", "done", f"{len(found['subjects'])} subjects found")
    return {"query": None, "about": "; ".join(x.get("title", "") for x in sources)[:400], "field": field or None, **found}


def _source_bundle(paper) -> list[dict]:
    """A build's sources, as a bundle. One source kept as plain text (a build from before bundles, or made from a single
    `paper_id`) becomes a bundle of that one, s1, so more can be added beside it."""
    sources = L.source_map(paper["text"])
    if sources:
        return list(sources.values())
    return [{"id": "s1", "title": paper.get("title") or "Source 1", "url": paper.get("url") or "", "authors": "", "year": None,
             "text": paper["text"]}]


def _launch_request(req: Request, record, provider, build=False, reread=False):
    """Starts a build. ``build`` builds the approved outline; otherwise an outline is proposed. ``reread`` (a retry that
    proposes a new outline) first reads again the selected sources that couldn't be read before."""
    owner, credential = req.owner(), req.credential()[1]
    job = _new_job(owner, "request", record["id"])
    record.update(status="running", error="", result=None, lesson=None, steps=[])
    def persist(j):
        with _requests_lock:
            if generate.JOBS.get(j.id) is not j:
                return
            record.update(j.snapshot())
            _stop_steps(record)
            # Provider errors can echo an invalid key. Never persist echoed credentials.
            serialized = json.dumps(record, ensure_ascii=False)
            if credential:
                serialized = serialized.replace(credential, "[redacted]")
                serialized = serialized.replace(json.dumps(credential, ensure_ascii=False)[1:-1], "[redacted]")
            store.save_request(json.loads(serialized), owner)
    job.on_change = persist
    generate.JOBS[job.id] = job
    try:
        persist(job)  # Persist before any external work begins.
    except BaseException:
        _forget(job)
        raise

    def read(j, items, again=False):
        """Reads the selected sources `items` ([(i, source)]) at the same time: {i: Paper or IngestError}."""
        for i, source in items:
            j.step(f"s{i}", f"Reading source {i}{' again' if again else ''}: {source['title']}", "waiting")

        def one(item):
            i, source = item
            if j.cancelled.is_set():
                return None
            j.update(f"s{i}", "active")
            if source.get("upload"):  # read when it was uploaded, and kept with the request
                j.update(f"s{i}", "done", "Full text ready")
                return ingest.Paper(**source["upload"])
            try:
                fetched = _first_readable(source["urls"])
            except ingest.IngestError as e:
                j.update(f"s{i}", "failed", str(e))
                return e
            j.update(f"s{i}", "done", "Full text ready")
            return fetched

        with ThreadPoolExecutor(max_workers=SOURCE_READERS) as pool:
            results = dict(zip((i for i, _ in items), pool.map(one, items)))
        if j.cancelled.is_set():
            raise generate.GenerationError("Cancelled.")
        return results

    def bundled(i, source, fetched):
        return {"id": f"s{i}", "title": fetched.title or source["title"], "url": ingest.reader_link(fetched.url),
                "authors": source.get("authors", ""), "year": source.get("year"), "text": fetched.text}

    def excluded(i, source, error):
        return {"source": i, "title": source["title"], "reason": str(error)}

    def run(j):
        paper = record.get("paper")
        if not paper:
            requested = record["request"]["sources"]
            results = read(j, list(enumerate(requested, 1)))
            sources, record["excluded"] = [], []
            for i, source in enumerate(requested, 1):
                if isinstance(results[i], ingest.IngestError):
                    record["excluded"].append(excluded(i, source, results[i]))
                else:
                    sources.append(bundled(i, source, results[i]))
            record["warnings"] = [f"Excluded {x['title']}: {x['reason']}" for x in record["excluded"]]
            if not sources:
                raise generate.GenerationError("None of the selected sources could be read. Choose other sources.")
            paper = {"text": json.dumps({"lemma_sources": sources}, ensure_ascii=False),
                     "title": record["title"], "url": ""}
            record["paper"] = paper
            j.changed()  # saved now, so a restart before the next step doesn't read them all again
        elif reread and record.get("excluded"):  # a new outline: the sources that couldn't be read get another try
            requested = record["request"]["sources"]
            results = read(j, [(x["source"], requested[x["source"] - 1]) for x in record["excluded"]], again=True)
            bundle = _source_bundle(paper)
            still = []
            for x in record["excluded"]:
                i, source = x["source"], requested[x["source"] - 1]
                if isinstance(results[i], ingest.IngestError):
                    still.append(excluded(i, source, results[i]))
                else:
                    bundle.append(bundled(i, source, results[i]))
            if len(still) < len(record["excluded"]):  # the sources changed: so may their subject, and what they build on
                bundle.sort(key=lambda x: int(x["id"][1:]))  # in the order the learner chose them
                paper["text"] = json.dumps({"lemma_sources": bundle}, ensure_ascii=False)
                record.pop("category", None)
                if (record["request"].get("search") or {}).get("query") is None:
                    record["request"].pop("search", None)
            record["warnings"] = [f"Excluded {x['title']}: {x['reason']}" for x in still] + \
                [w for w in record["warnings"] if not w.startswith("Excluded ")]
            record["excluded"] = still
            j.changed()
        if record.get("pending"):  # suggested sources the learner added at outline review
            bundle = _source_bundle(paper)
            chosen = len((record["request"] or {}).get("sources") or [])  # ids s1…sN stay the selected sources', read or not
            for source in record["pending"]:
                sid = f"s{max([int(s['id'][1:]) for s in bundle] + [chosen]) + 1}"
                j.step(sid, f"Reading {source['title']}", "active")
                try:
                    fetched = _first_readable(source["urls"])
                except ingest.IngestError as e:
                    j.update(sid, "failed", str(e))
                    record["warnings"].append(f"Couldn't add {source['title']}: {e}")
                    continue
                j.update(sid, "done", "Full text ready")
                bundle.append({"id": sid, "title": source["title"], "url": ingest.reader_link(fetched.url), "authors": "", "year": None, "text": fetched.text})
            paper["text"] = json.dumps({"lemma_sources": bundle}, ensure_ascii=False)
            record["pending"] = []
            j.changed()
        # The category comes from the sources themselves, sorted out before anything is paid for.
        if not record.get("category"):
            _categorize(record, paper)
        if not build and not record["request"].get("search"):  # kept, so a retry doesn't pay for it again
            record["request"]["search"] = _source_context(j, provider, record, paper)
        if not build:
            outline = generate.make_outline(j, provider, paper["text"], record["request"].get("level", levels.DEFAULT),
                                            record["request"].get("search"))
            with j.lock:
                if not j.cancelled.is_set():
                    record["outline"] = outline
                    j.status = "awaiting_outline"
            return outline
        result = generate.build_lesson(j, provider, paper, record["outline"], record["request"].get("level", levels.DEFAULT), j.id,
                                       saved=store.BuiltConcepts(j.id, owner))
        result["category"] = record["category"]
        j.step("save", "Saving your lesson", "active")
        with _requests_lock:
            if j.cancelled.is_set():
                raise generate.GenerationError("Cancelled.")
            core.require_valid(result, paper["text"])
            store.save_lesson(result, paper["text"], owner)
            checks.remember({k: v for k, v in result.items() if k != "plan"}, paper["text"], [], _library_key(owner, result["id"]))
            store.BuiltConcepts(j.id, owner).clear()  # the saved lesson has them all now
            j.result = result
            with j.lock:
                j.status = "done"
            j.update("save", "done", "Saved to your library")
        return result
    _start(job, run)
    return {"id": job.id}


def _level(body, owner: str) -> str:
    """The learner's level from a request, remembered on the account for next time."""
    level = _parse_level(body)
    store.save_settings(owner, level=level)
    return level


def _web_link(u) -> bool:
    return isinstance(u, str) and len(u) <= 2048 and urlsplit(u).scheme in ("http", "https") and bool(urlsplit(u).hostname)


def _search_context(body) -> dict | None:
    """The search a lesson was asked for from, as the browser sends it with the chosen sources: the question, its
    field, the subjects search rated and what no source covered. Only the learner's own provider reads it."""
    raw = body.get("search")
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("query"), str) or not raw["query"].strip():
        raise ApiError(400, "Invalid search.")
    text = lambda v: re.sub(r"\s+", " ", v).strip()[:200] if isinstance(v, str) else ""
    field = [f for f in raw.get("field") or [] if f in categorize.CATEGORIES and f != "other"][:2] if isinstance(raw.get("field"), list) else []
    subjects = []
    for x in raw.get("subjects") or [] if isinstance(raw.get("subjects"), list) else []:
        if isinstance(x, dict) and text(x.get("title")) and x.get("relation") in generate.RELATION_WORDS \
                and isinstance(x.get("need"), (int, float)) and 1 <= x["need"] <= 5:
            subject = {"title": text(x["title"]), "need": float(x["need"]), "relation": x["relation"]}
            if _web_link(x.get("url")):  # its article, which outline review can offer to add
                subject["url"] = x["url"]
            subjects.append(subject)
    missing = raw.get("not_covered") if isinstance(raw.get("not_covered"), list) else []
    return {"query": text(raw["query"]), "field": field or None, "subjects": subjects[:12],
            "not_covered": [t for t in map(text, missing) if t][:10]}


@route("POST", r"/api/requests")
def api_request_create(req):
    body = req.body
    with _requests_lock:
        owner, provider = req.owner(), core._provider(req)
        request = {"level": _level(body, owner)}
        if search := _search_context(body):
            request["search"] = search
        paper = None
        if body.get("paper_id"):
            paper = dict(_paper(body, owner))
            paper.pop("owner", None)
        else:
            sources = body.get("sources")
            if not isinstance(sources, list) or not 1 <= len(sources) <= 10:
                raise ApiError(400, "Select between 1 and 10 sources.")
            request["sources"] = []
            for s in sources:
                if not isinstance(s, dict):
                    raise ApiError(400, "Invalid source.")
                if s.get("paper_id"):
                    p = _paper(s, owner)
                    request["sources"].append({"urls": [], "title": p["title"][:300], "upload": {k: p[k] for k in ("text", "title", "kind", "url")}})
                    continue
                urls = s.get("urls") or [s.get("url")]
                if not isinstance(urls, list) or not 1 <= len(urls) <= 5 or not all(map(_web_link, urls)):
                    raise ApiError(400, "Each source needs valid HTTP or HTTPS links.")
                request["sources"].append({"urls": urls, "title": str(s.get("title") or urls[0])[:300],
                                           "authors": str(s.get("authors", ""))[:300], "year": s.get("year") if isinstance(s.get("year"), int) else None})
        record = {"id": uuid.uuid4().hex[:12], "title": str(body.get("topic") or (paper or {}).get("title") or "Combined lesson")[:200],
                  "request": request, "paper": paper, "warnings": []}
        return _launch_request(req, record, provider)


@route("GET", r"/api/requests")
def api_requests(req):
    owner = req.owner()
    with _requests_lock:
        return [{**{k: r.get(k) for k in ("id", "title", "status", "created")}, "resume": _resume(r, owner)}
                for saved in store.list_requests(owner) for r in [_request_record(saved["id"], owner)]]


@route("GET", r"/api/requests/([a-f0-9]{12})")
def api_request(req, rid):
    with _requests_lock:
        owner = req.owner()
        record = _request_record(rid, owner)
        job = generate.JOBS.get(rid)
        if record["status"] == "running" and job and job.owner == owner:
            # Progress ticks while a reply streams live only in memory; they aren't worth a disk write each.
            snap = job.snapshot()
            record = {**record, **{k: snap[k] for k in ("steps", "lesson", "eta_seconds")}}
        return {**_public_request(record, owner), "now": time.time()}


@route("POST", r"/api/requests/([a-f0-9]{12})/cancel")
def api_request_cancel(req, rid):
    with _requests_lock:
        owner = req.owner()
        record = _request_record(rid, owner)
        job = generate.JOBS.get(rid)
        if record["status"] == "running" and job:
            job.cancelled.set()
            with job.lock:
                if job.status == "awaiting_outline":
                    job.status = "cancelled"
        elif record["status"] == "awaiting_outline":
            if job and job.owner == owner:
                with job.lock:
                    job.status = "cancelled"
                job.cancelled.set()
            record["status"] = "cancelled"
            store.save_request(record, owner)
        return {"ok": True}


CHOOSE = "Choose whether to continue this build or start over."


@route("POST", r"/api/requests/([a-f0-9]{12})/retry")
def api_request_retry(req, rid):
    """Retries a stopped build. One with an approved outline needs the learner's choice, ``mode``: "continue" builds
    that outline, reusing the concepts already finished; "start_over" deletes them and proposes a new outline from
    the same sources. Any other stopped build proposes a new outline, as a start over does."""
    mode = req.body.get("mode")
    with _requests_lock:
        owner = req.owner()
        record = _request_record(rid, owner)
        if record["status"] not in STOPPED:
            raise ApiError(409, "Only a stopped build can be retried.")
        if mode not in (None, "continue", "start_over"):
            raise ApiError(400, CHOOSE)
        choice = _approved(record)
        if choice and mode is None:
            raise ApiError(400, CHOOSE)
        provider = core._provider(req)  # before anything is deleted: a retry that can't start loses nothing
        if mode == "continue":
            if not choice:
                raise ApiError(409, "This build has no approved outline to continue. Start over instead.")
            return _launch_request(req, record, provider, build=True)
        record.pop("outline", None)
        record.pop("approved", None)
        started = _launch_request(req, record, provider, reread=True)
        # Only once the new attempt has started. Deleted now, not left for the versions to tell apart: a new outline
        # could be the same as the old one, and starting over means nothing is reused.
        store.BuiltConcepts(rid, owner).clear()
        return started


@route("POST", r"/api/requests/([a-f0-9]{12})/outline")
def api_request_outline(req, rid):
    body = req.body
    with _requests_lock:
        owner = req.owner()
        record = _request_record(rid, owner)
        if record["status"] != "awaiting_outline":
            raise ApiError(409, "This build is not waiting for outline review.")
        outline = generate.order_outline(body.get("outline"))
        problems = generate.check_outline(outline, record["paper"]["text"])
        if problems:
            raise ApiError(400, "The outline isn't valid: " + "; ".join(problems[:3]))
        record["outline"] = outline
        record["approved"] = generate.fingerprint(outline)  # the version its concepts are built from
        return _launch_request(req, record, core._provider(req), build=True)


@route("POST", r"/api/requests/([a-f0-9]{12})/add")
def api_request_add(req, rid):
    """Adds the sources outline review suggested that the learner chose (assumed subjects' own articles) and remakes
    the outline with them, once for all of them."""
    body = req.body
    with _requests_lock:
        owner = req.owner()
        record = _request_record(rid, owner)
        if record["status"] != "awaiting_outline":
            raise ApiError(409, "This build is not waiting for outline review.")
        titles = body.get("titles")
        if not isinstance(titles, list) or not titles or not all(isinstance(t, str) for t in titles):
            raise ApiError(400, "Choose at least one source to add.")
        titles = list(dict.fromkeys(titles))
        suggested = {s["title"]: s for s in (record.get("outline") or {}).get("subjects") or [] if s.get("url") and not s.get("source")}
        if any(t not in suggested for t in titles):
            raise ApiError(400, "That isn't one of the suggested sources.")
        if max(len(L.source_map(record["paper"]["text"])), 1) + len(titles) > 10:  # one source kept as plain text counts too
            raise ApiError(400, "A lesson takes at most 10 sources.")
        record["pending"] = [{"urls": [suggested[t]["url"]], "title": t} for t in titles]
        record.pop("outline", None)
        return _launch_request(req, record, core._provider(req))


@route("DELETE", r"/api/requests/([a-f0-9]{12})")
def api_request_delete(req, rid):
    with _requests_lock:
        owner = req.owner()
        record = _request_record(rid, owner)
        if record["status"] == "running":
            raise ApiError(409, "Cancel the build before deleting it.")
        store.request_path(rid, owner).unlink(missing_ok=True)
        store.BuiltConcepts(rid, owner).clear()
        generate.JOBS.pop(rid, None)
        return {"ok": True}
