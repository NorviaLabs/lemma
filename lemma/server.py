"""Lemma's web server. Locally it listens only on this computer; hosted, it serves signed-in accounts. It keeps no logs."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import secrets
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, quote, urlsplit

from . import __version__, auth, categorize, chatgpt, claudecode, export, generate, ingest, jev, logs, search, store
from . import lesson as L
from .llm import DEFAULT_PROVIDER, PROVIDERS, ProviderError, make_provider

MAX_BODY = 64 * 1024 * 1024
STATIC = resources.files("lemma").joinpath("static")
EXAMPLES = resources.files("lemma").joinpath("examples")

DEV = False  # set by `lemma --dev`: live-reload script and /api/dev/events
# Set by `make_server` when Lemma listens beyond this computer. A hosted Lemma serves other people,
# so it doesn't offer ChatGPT sign-in, which keeps one person's tokens on the server's disk, or the
# Claude subscription, which runs the Claude Code signed in on this computer.
HOSTED = False
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")
ALLOWED_HOSTS: tuple[str, ...] = LOCAL_HOSTS  # Host header names Lemma answers; `--allowed-hosts` adds more

PAPERS: dict[str, dict] = {}  # paper_id -> {text, title, url, kind, pages, owner}
SOURCES: dict[tuple, str] = {}  # (owner, lesson id) -> paper text, for lessons built in this session
KEEP_PAPERS, KEEP_SOURCES = 5, 200  # papers kept per person, and paper texts kept in all
SOURCE_READERS = 4  # sources of one request read at the same time
MAX_RUNNING_EACH, MAX_RUNNING = 2, 8  # outlines and builds running at once, per account and in all, when hosted
MAX_CONNECTIONS = 32  # requests handled at once; more wait to be accepted
LARGE_BODY = 1024 * 1024  # a request body this big is an upload, held in memory while it is read
_uploads = threading.BoundedSemaphore(2)  # uploads handled at once, so a burst of them can't exhaust memory
_lock = threading.Lock()
REQUEST = threading.local()  # the current request's headers; one thread per request


class ApiError(Exception):
    def __init__(self, status: int, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.status, self.message, self.problems = status, message, problems


# ---------------------------------------------------------------- helpers


def _credential():
    """The learner's provider, model and key. The browser keeps them and sends them with each request."""
    headers = getattr(REQUEST, "headers", None) or {}
    return (headers.get("X-Lemma-Provider") or DEFAULT_PROVIDER, headers.get("X-Lemma-Key") or "", headers.get("X-Lemma-Model") or "")


def _owner() -> str | None:
    """Whose papers, builds and library this request uses: nobody's locally, the signed-in account's when hosted."""
    if not HOSTED:
        return None
    user = getattr(REQUEST, "user", None)
    if not user:
        raise ApiError(401, "Sign in to find papers, build lessons and keep a library.")
    return user["id"]


def provider_from_request(pid: str | None = None):
    req_pid, key, model = _credential()
    if pid and pid != req_pid:
        raise ApiError(400, "Save this provider in Settings first.")
    if HOSTED and (req_pid or DEFAULT_PROVIDER) not in providers():
        raise ApiError(400, "This provider is only available when Lemma runs on your own computer.")
    try:
        return make_provider(req_pid, key, model)
    except ProviderError as e:
        raise ApiError(400, str(e)) from None


def providers() -> dict:
    """The providers this server offers: all of them locally, only keyed ones when hosted."""
    return {i: p for i, p in PROVIDERS.items() if p.key_url or not HOSTED}


def load_example() -> tuple[dict, str]:
    lesson = json.loads(EXAMPLES.joinpath("gallery/galton-1886.json").read_text(encoding="utf-8"))
    source = EXAMPLES.joinpath("galton-1886.txt").read_text(encoding="utf-8")
    return lesson, source


GALLERY = EXAMPLES.joinpath("gallery")


def gallery_index() -> list[dict]:
    return json.loads(GALLERY.joinpath("index.json").read_text(encoding="utf-8"))


def load_gallery(slug: str) -> tuple[dict, str | None]:
    """A finished lesson, read-only like the example, with its checked-in source: Galton's full text, or for the
    others the verified quotation excerpts its quotes are checked against before display."""
    entry = next((e for e in gallery_index() if e["slug"] == slug), None)
    if entry is None:
        raise ApiError(404, "That lesson isn't in the gallery.")
    lesson = json.loads(GALLERY.joinpath(f"{slug}.json").read_text(encoding="utf-8"))
    source_path = EXAMPLES.joinpath(entry["source_file"]) if entry.get("source_file") else None
    source = source_path.read_text(encoding="utf-8") if source_path else None
    lesson["example"] = True  # built in: it can't be saved or edited, only played and downloaded
    lesson["gallery"] = {k: entry[k] for k in ("slug", "field")}
    return lesson, source


def source_for(lesson_id: str, owner: str | None = None) -> str | None:
    if (owner, lesson_id) in SOURCES:
        return SOURCES[(owner, lesson_id)]
    try:
        return store.load_lesson(lesson_id, owner)[1]
    except (KeyError, OSError, ValueError):
        return None


def require_valid(lesson, source_text: str | None):
    problems = L.check_lesson(lesson, source_text)
    if problems:
        raise ApiError(422, f"This lesson didn't pass {len(problems)} quality check{'s' * (len(problems) != 1)}.", list(problems))


# ---------------------------------------------------------------- API


def api_status(_body):
    p = provider_from_request()
    ok, msg = p.available()
    return {
        "version": __version__,
        "provider": {"id": p.id, "name": p.name, "model": p.model, "label": p.label, "ok": ok, "message": msg},
        "providers": [{"id": i.id, "name": i.name, "default_model": i.default_model, "key_url": i.key_url, "sign_in": not i.key_url} for i in providers().values()],
        "library_count": len(store.list_lessons(_owner())) if not HOSTED or getattr(REQUEST, "user", None) else 0,
        "hosted": HOSTED,
        "user": getattr(REQUEST, "user", None),
        "sign_in": auth.providers() if HOSTED else [],
        "typesafe": jev.available(),  # search results and source text also go to TypeSafe, which the privacy notes must say
    }


def api_models(_body):
    """Models offered by the provider in the request headers, read live with the learner's key. Also checks the key."""
    p = provider_from_request()
    try:
        models = p.models()
    except ProviderError as e:
        raise ApiError(502, str(e)) from None
    return {"provider": p.id, "models": models, "current": p.model}


def _local_only():
    if HOSTED:
        raise ApiError(404, "Not found.")


def api_chatgpt(_body):
    _local_only()
    return chatgpt.status()


def api_chatgpt_login(_body):
    """Starts a ChatGPT sign-in; the browser opens the returned page."""
    _local_only()
    try:
        return {"url": chatgpt.start_sign_in()}
    except ProviderError as e:
        raise ApiError(409, str(e)) from None


def api_chatgpt_logout(_body):
    _local_only()
    chatgpt.sign_out()
    return chatgpt.status()


def api_claude_code(_body):
    """Whether this computer's Claude Code is signed in with a Claude subscription. It signs in in a terminal, not here."""
    _local_only()
    return claudecode.status(fresh=True)


def api_papers(body):
    owner = _owner()
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
            paper = ingest.from_bytes(data, filename=str(body.get("filename", "")), content_type=str(body.get("content_type", "")))
        else:
            raise ApiError(400, "Paste a link or choose a file.")
    except ingest.IngestError as e:
        raise ApiError(422, str(e)) from None
    pid = uuid.uuid4().hex[:12]
    with _lock:
        PAPERS[pid] = {"text": paper.text, "title": paper.title, "url": paper.url, "kind": paper.kind, "pages": paper.pages, "owner": owner}
        mine = [k for k, v in PAPERS.items() if v["owner"] == owner]
        for k in mine[:-KEEP_PAPERS]:
            PAPERS.pop(k)
    return {"paper_id": pid, "title": paper.title, "kind": paper.kind, "pages": paper.pages, "chars": len(paper.text), "url": paper.url}


_first_readable = ingest.first_readable


# Searches run in the background so the page can show each library answering and each source being checked.
SEARCHES: dict[str, dict] = {}
SEARCHES_EACH = 3  # searches one account can have running at once


def api_search(body):
    owner = _owner()
    query = str(body.get("query", ""))
    try:
        if hit := search.cached(query):
            return {"done": True, "result": hit}
        query = search.clean(query)
        if not jev.available():
            raise search.SearchError(jev.MISSING)
    except search.SearchError as e:
        raise ApiError(422, str(e)) from None
    with _lock:
        for sid in [k for k, s in SEARCHES.items() if s["done"] and time.time() - s["created"] > 600]:
            SEARCHES.pop(sid)
        if sum(s["owner"] == owner and not s["done"] for s in SEARCHES.values()) >= SEARCHES_EACH:
            raise ApiError(429, "Several searches are still running. Wait a moment and try again.")
        sid = uuid.uuid4().hex[:12]
        record = SEARCHES[sid] = {"owner": owner, "query": query, "done": False, "progress": None, "result": None, "error": "", "created": time.time()}

    def progress(snapshot):
        record["progress"] = snapshot

    def run():
        try:
            record["result"] = search.search(query, progress)
        except search.SearchError as e:
            record["error"] = str(e)
        except Exception as e:  # keep the server alive and tell the learner honestly
            record["error"] = f"The search failed unexpectedly ({e.__class__.__name__}, error {logs.report('search', e)})."
        finally:
            record["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return api_search_status(sid)


def api_search_status(sid):
    record = SEARCHES.get(sid)
    if not record or record["owner"] != _owner():
        raise ApiError(404, "That search has finished or expired. Search again.")
    return {"id": sid, "query": record["query"], "done": record["done"], "progress": record["progress"],
            "result": record["result"], "error": record["error"]}


def _paper(body) -> dict:
    p = PAPERS.get(str(body.get("paper_id", "")))
    if not p or p["owner"] != _owner():
        raise ApiError(404, "Lemma no longer has that paper in memory. Please bring it again.")
    return p


def _provider():
    p = provider_from_request()
    ok, msg = p.available()
    if not ok:
        raise ApiError(400, msg)
    return p


def _new_job(kind: str) -> generate.Job:
    owner = _owner()
    if not jev.available():  # every outline and build is checked by Jev; without it, nothing is started or paid for
        raise ApiError(503, jev.MISSING)
    if HOSTED:
        running = [j for j in list(generate.JOBS.values()) if j.status == "running"]
        if sum(j.owner == owner for j in running) >= MAX_RUNNING_EACH:
            raise ApiError(429, "You already have lessons building. Wait for one to finish, or cancel it.")
        if len(running) >= MAX_RUNNING:
            raise ApiError(503, "Lemma is busy building other people's lessons. Please try again in a few minutes.")
    job = generate.Job(kind)
    job.owner = owner
    return job


def _job(job_id: str) -> generate.Job | None:
    job = generate.JOBS.get(job_id)
    return job if job and job.owner == _owner() else None


def api_outline(body):
    paper = _paper(body)
    job = _new_job("outline")
    generate.start(job, generate.make_outline, _provider(), paper["text"], str(body.get("audience", ""))[:300])
    return {"id": job.id}


def api_build(body):
    paper = _paper(body)
    outline = generate.order_outline(body.get("outline"))
    problems = generate.check_outline(outline, paper["text"])
    if problems:
        raise ApiError(400, "The outline isn't valid: " + "; ".join(problems[:3]))
    provider = _provider()
    job = _new_job("build")
    lesson_id = uuid.uuid4().hex[:12]
    with _lock:
        SOURCES[(job.owner, lesson_id)] = paper["text"]
        while len(SOURCES) > KEEP_SOURCES:
            SOURCES.pop(next(iter(SOURCES)))
    generate.start(job, generate.build_lesson, provider, paper, outline, str(body.get("audience", ""))[:300], lesson_id)
    return {"id": job.id, "lesson_id": lesson_id}


def api_job(job_id):
    job = _job(job_id)
    if not job:
        raise ApiError(404, "That job has finished or expired.")
    return job.snapshot()


def api_job_cancel(job_id):
    job = _job(job_id)
    if job:
        job.cancelled.set()
    return {"ok": True}


# Durable requests reuse the local thread runner; disk is the recovery boundary, not a queue.
_requests_lock = threading.RLock()


def _request_record(rid, owner):
    try:
        record = store.load_request(rid, owner)
    except (KeyError, OSError, ValueError):
        raise ApiError(404, "That lesson build wasn't found.") from None
    job = generate.JOBS.get(rid)
    if record["status"] == "running" and not (job and job.owner == owner):
        record.update(status="interrupted", error="The server stopped during this build. Retry to start a new attempt.")
        store.save_request(record, owner)
    return record


def _public_request(record):
    return {k: v for k, v in record.items() if k not in ("paper", "request")}


def _categorize(record, paper):
    """Stores the lesson's category on its build record. Jev sorts every lesson, so a failure stops the build."""
    try:
        record["category"] = categorize.categorize(paper)
    except categorize.CategorizeError as e:
        raise generate.GenerationError(f"Couldn't sort this lesson into a subject with Jev ({e}). Retry in a moment.") from None


def _launch_request(record, provider, owner, build=False):
    credential = _credential()[1]
    job = _new_job("request")
    job.id = record["id"]
    record.update(status="running", error="", result=None, lesson=None, steps=[])
    def persist(j):
        with _requests_lock:
            if generate.JOBS.get(j.id) is not j:
                return
            record.update(j.snapshot())
            # Provider errors can echo an invalid key. Never persist echoed credentials.
            serialized = json.dumps(record, ensure_ascii=False)
            if credential:
                serialized = serialized.replace(credential, "[redacted]")
                serialized = serialized.replace(json.dumps(credential, ensure_ascii=False)[1:-1], "[redacted]")
            store.save_request(json.loads(serialized), owner)
    job.on_change = persist
    generate.JOBS[job.id] = job
    persist(job)  # Persist before any external work begins.

    def run(j):
        paper = record.get("paper")
        if not paper:
            requested = record["request"]["sources"]
            for i, source in enumerate(requested, 1):
                j.step(f"s{i}", f"Reading source {i}: {source['title']}", "waiting")

            def read(i, source):  # the sources are read at the same time
                if j.cancelled.is_set():
                    return None
                j.update(f"s{i}", "active")
                try:
                    fetched = _first_readable(source["urls"])
                except ingest.IngestError as e:
                    j.update(f"s{i}", "failed", str(e))
                    return e
                j.update(f"s{i}", "done", "Full text ready")
                return fetched

            with ThreadPoolExecutor(max_workers=SOURCE_READERS) as pool:
                read_all = list(pool.map(read, range(1, len(requested) + 1), requested))
            if j.cancelled.is_set():
                raise generate.GenerationError("Cancelled.")
            sources = []
            record["warnings"] = []
            for i, (source, fetched) in enumerate(zip(requested, read_all), 1):
                if isinstance(fetched, ingest.IngestError):
                    record["warnings"].append(f"Excluded {source['title']}: {fetched}")
                    continue
                sources.append({"id": f"s{i}", "title": fetched.title or source["title"], "url": ingest.reader_link(fetched.url),
                                "authors": source.get("authors", ""), "year": source.get("year"), "text": fetched.text})
            if not sources:
                raise generate.GenerationError("None of the selected sources could be read. Choose other sources.")
            paper = {"text": json.dumps({"lemma_sources": sources}, ensure_ascii=False),
                     "title": record["title"], "url": ""}
            record["paper"] = paper
        # The category comes from the sources themselves, sorted out before anything is paid for.
        if not record.get("category"):
            _categorize(record, paper)
        if not build:
            outline = generate.make_outline(j, provider, paper["text"], record["request"]["audience"])
            with j.lock:
                if not j.cancelled.is_set():
                    record["outline"] = outline
                    j.status = "awaiting_outline"
            return outline
        result = generate.build_lesson(j, provider, paper, record["outline"], record["request"]["audience"], j.id)
        result["category"] = record["category"]
        j.step("save", "Saving your lesson", "active")
        with _requests_lock:
            if j.cancelled.is_set():
                raise generate.GenerationError("Cancelled.")
            require_valid(result, paper["text"])
            store.save_lesson(result, paper["text"], owner)
            j.result = result
            with j.lock:
                j.status = "done"
            j.update("save", "done", "Saved to your library")
        return result
    generate.start(job, run)
    return {"id": job.id}


def api_request_create(body):
    with _requests_lock:
        owner, provider = _owner(), _provider()
        request = {"audience": str(body.get("audience", ""))[:300]}
        paper = None
        if body.get("paper_id"):
            paper = dict(_paper(body))
            paper.pop("owner", None)
        else:
            sources = body.get("sources")
            if not isinstance(sources, list) or not 1 <= len(sources) <= 10:
                raise ApiError(400, "Select between 1 and 10 sources.")
            request["sources"] = []
            for s in sources:
                if not isinstance(s, dict):
                    raise ApiError(400, "Invalid source.")
                urls = s.get("urls") or [s.get("url")]
                if not isinstance(urls, list) or not 1 <= len(urls) <= 5 or any(not isinstance(u, str) or len(u) > 2048 or urlsplit(u).scheme not in ("http", "https") or not urlsplit(u).hostname for u in urls):
                    raise ApiError(400, "Each source needs valid HTTP or HTTPS links.")
                request["sources"].append({"urls": urls, "title": str(s.get("title") or urls[0])[:300],
                                           "authors": str(s.get("authors", ""))[:300], "year": s.get("year") if isinstance(s.get("year"), int) else None})
        record = {"id": uuid.uuid4().hex[:12], "title": str(body.get("topic") or (paper or {}).get("title") or "Combined lesson")[:200],
                  "request": request, "paper": paper, "warnings": []}
        return _launch_request(record, provider, owner)


def api_requests(_body):
    owner = _owner()
    with _requests_lock:
        return [{k: r.get(k) for k in ("id", "title", "status", "created")} for saved in store.list_requests(owner)
                for r in [_request_record(saved["id"], owner)]]


def api_request(rid):
    with _requests_lock:
        owner = _owner()
        record = _request_record(rid, owner)
        job = generate.JOBS.get(rid)
        if record["status"] == "running" and job and job.owner == owner:
            # Progress ticks while a reply streams live only in memory; they aren't worth a disk write each.
            snap = job.snapshot()
            record = {**record, **{k: snap[k] for k in ("steps", "lesson", "eta_seconds")}}
        return {**_public_request(record), "now": time.time()}


def api_request_cancel(rid):
    with _requests_lock:
        owner = _owner()
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


def api_request_retry(rid):
    with _requests_lock:
        owner = _owner()
        record = _request_record(rid, owner)
        if record["status"] not in ("error", "cancelled", "interrupted"):
            raise ApiError(409, "Only a stopped build can be retried.")
        record.pop("outline", None)
        return _launch_request(record, _provider(), owner)


def api_request_outline(rid):
    # The HTTP dispatcher supplies bodies only to non-capture handlers.
    body = getattr(REQUEST, "body", {})
    with _requests_lock:
        owner = _owner()
        record = _request_record(rid, owner)
        if record["status"] != "awaiting_outline":
            raise ApiError(409, "This build is not waiting for outline review.")
        outline = generate.order_outline(body.get("outline"))
        problems = generate.check_outline(outline, record["paper"]["text"])
        if problems:
            raise ApiError(400, "The outline isn't valid: " + "; ".join(problems[:3]))
        record["outline"] = outline
        return _launch_request(record, _provider(), owner, build=True)


def api_request_delete(rid):
    with _requests_lock:
        owner = _owner()
        record = _request_record(rid, owner)
        if record["status"] == "running":
            raise ApiError(409, "Cancel the build before deleting it.")
        store.request_path(rid, owner).unlink(missing_ok=True)
        generate.JOBS.pop(rid, None)
        return {"ok": True}


def api_example(_body):
    lesson, source = load_example()
    require_valid(lesson, source)  # never show a lesson that fails its checks, even ours
    return lesson


def api_gallery(_body):
    items = []
    for entry in gallery_index():
        lesson, _ = load_gallery(entry["slug"])
        cover = next(c for c in lesson["concepts"] if c["id"] == entry["cover"])
        items.append({**lesson["gallery"], "title": lesson["title"], "source": lesson["source"],
                      "concepts": [c["title"] for c in lesson["concepts"]],
                      "cover": {"title": cover["title"], "idea": cover["idea"], "model": cover.get("model"),
                                "activity": next((a for a in cover.get("activities", []) if a["kind"] in ("sort", "construction", "inheritance")), None),
                                "values": entry.get("cover_values", {})}})
    return items


def api_gallery_lesson(slug):
    lesson, source = load_gallery(slug)
    require_valid(lesson, source)
    return lesson


def api_save(body):
    lesson = body.get("lesson")
    if not isinstance(lesson, dict):
        raise ApiError(400, "No lesson to save.")
    if lesson.get("example"):
        raise ApiError(400, "The example lesson is built in and can't be saved or edited.")
    lid = str(lesson.get("id") or "")
    if not store.ID_RE.match(lid):
        raise ApiError(400, "This lesson has no valid id.")
    owner = _owner()
    source = source_for(lid, owner) or None
    if source is None:
        raise ApiError(409, "Lemma no longer has this lesson's paper text, so it can't confirm the quotes. Bring the paper again to rebuild it.")
    lesson = {k: v for k, v in lesson.items() if k != "plan"}
    require_valid(lesson, source)
    store.save_lesson(lesson, source, owner)
    return {"ok": True, "id": lid}


def api_lessons(_body):
    return store.list_lessons(_owner())


def api_lesson(lesson_id):
    try:
        return store.load_lesson(lesson_id, _owner())[0]
    except (KeyError, OSError, ValueError):
        raise ApiError(404, "That lesson isn't in your library.") from None


def api_lesson_delete(lesson_id):
    try:
        with _requests_lock:
            store.delete_lesson(lesson_id, _owner())
            generate.JOBS.pop(lesson_id, None)
            store.request_path(lesson_id, _owner()).unlink(missing_ok=True)
    except KeyError:
        raise ApiError(404, "That lesson isn't in your library.") from None
    return {"ok": True}


def api_export(body):
    lesson = body.get("lesson")
    if not isinstance(lesson, dict):
        raise ApiError(400, "No lesson to export.")
    if isinstance(lesson.get("gallery"), dict):
        lesson, source = load_gallery(str(lesson["gallery"].get("slug", "")))  # the lesson as shipped, not as sent
    elif lesson.get("example"):
        source = load_example()[1]
    else:
        source = source_for(str(lesson.get("id", "")), _owner()) or None
    lesson = {k: v for k, v in lesson.items() if k != "plan"}
    require_valid(lesson, source)
    return export.lesson_html(lesson)


ROUTES = [
    ("POST", r"/api/requests", api_request_create, False),
    ("GET", r"/api/requests", api_requests, False),
    ("GET", r"/api/requests/([a-f0-9]{12})", api_request, True),
    ("POST", r"/api/requests/([a-f0-9]{12})/cancel", api_request_cancel, True),
    ("POST", r"/api/requests/([a-f0-9]{12})/retry", api_request_retry, True),
    ("POST", r"/api/requests/([a-f0-9]{12})/outline", api_request_outline, True),
    ("DELETE", r"/api/requests/([a-f0-9]{12})", api_request_delete, True),
    ("GET", r"/api/status", api_status, False),
    ("GET", r"/api/models", api_models, False),
    ("GET", r"/api/chatgpt", api_chatgpt, False),
    ("POST", r"/api/chatgpt/login", api_chatgpt_login, False),
    ("POST", r"/api/chatgpt/logout", api_chatgpt_logout, False),
    ("GET", r"/api/claude-code", api_claude_code, False),
    ("POST", r"/api/papers", api_papers, False),
    ("POST", r"/api/search", api_search, False),
    ("GET", r"/api/search/([a-f0-9]{12})", api_search_status, True),
    ("POST", r"/api/outline", api_outline, False),
    ("POST", r"/api/build", api_build, False),
    ("GET", r"/api/jobs/([a-f0-9]{12})", api_job, True),
    ("POST", r"/api/jobs/([a-f0-9]{12})/cancel", api_job_cancel, True),
    ("GET", r"/api/example", api_example, False),
    ("GET", r"/api/gallery", api_gallery, False),
    ("GET", r"/api/gallery/([a-z0-9-]{1,64})", api_gallery_lesson, True),
    ("GET", r"/api/lessons", api_lessons, False),
    ("POST", r"/api/lessons", api_save, False),
    ("GET", r"/api/lessons/([A-Za-z0-9_-]{1,64})", api_lesson, True),
    ("DELETE", r"/api/lessons/([A-Za-z0-9_-]{1,64})", api_lesson_delete, True),
    ("POST", r"/api/export", api_export, False),
]


# ---------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "Lemma"
    sys_version = ""
    timeout = 60  # seconds a connection may sit silent before it is closed

    def log_message(self, format, *args):  # Lemma keeps no usage logs
        pass

    def _allowed_host(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        return name in ALLOWED_HOSTS

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urlsplit(origin).netloc.lower() == (self.headers.get("Host") or "").lower()

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if "Cache-Control" not in (extra or {}):
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _dispatch(self, method: str):
        if not self._allowed_host():
            return self._send(403, b"Forbidden", "text/plain")
        REQUEST.headers = self.headers
        REQUEST.token = self._cookie(auth.SESSION_COOKIE) if HOSTED else None
        REQUEST.user = auth.user_for(REQUEST.token) if REQUEST.token else None
        url = urlsplit(self.path)
        path = url.path
        base = urlsplit(auth.public_url()).path  # e.g. /lemma, when Lemma is served under a path
        if base and path == base:
            self.send_response(301)
            self.send_header("Location", base + "/")
            self.send_header("Content-Length", "0")
            return self.end_headers()
        if base and path.startswith(base + "/"):
            path = path[len(base):]
        if HOSTED and method == "GET" and path.startswith("/auth/"):
            return self._sign_in(path, parse_qs(url.query))
        if DEV and method == "GET" and path == "/api/dev/events":
            return self._dev_events()
        if method == "GET" and not path.startswith("/api/"):
            return self._static(path)
        if method != "GET" and not self._same_origin():
            return self._json(403, {"error": "Cross-origin requests are not allowed."})
        if HOSTED and method == "POST" and path == "/api/logout":
            return self._sign_out()  # not in ROUTES: it clears the session cookie
        with _uploads if int(self.headers.get("Content-Length") or 0) > LARGE_BODY else nullcontext():
            return self._route(method, path)

    def _route(self, method: str, path: str):
        for m, pattern, fn, has_arg in ROUTES:
            if m != method:
                continue
            match = re.fullmatch(pattern, path)
            if not match:
                continue
            try:
                if has_arg:
                    REQUEST.body = self._body() if method == "POST" else {}
                    result = fn(match.group(1))
                else:
                    result = fn(self._body() if method == "POST" else {})
            except ApiError as e:
                return self._json(e.status, {"error": e.message, "problems": e.problems})
            except Exception as e:
                return self._json(500, {"error": f"Something went wrong inside Lemma (error {logs.report(f'{method} {pattern}', e)})."})
            if isinstance(result, str):
                return self._send(200, result.encode("utf-8"), "text/html; charset=utf-8", {"Content-Disposition": "attachment; filename=lesson.html"})
            return self._json(200, result)
        return self._json(404, {"error": "Not found."})

    # ---------------------------------------------------------- accounts (hosted only; see auth.py)

    def _cookie(self, name: str) -> str | None:
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie") or "")
        except Exception:
            return None
        return jar[name].value if name in jar else None

    def _set_cookie(self, name: str, value: str, max_age: int) -> str:
        secure = "; Secure" if auth.public_url().startswith("https://") else ""
        return f"{name}={value}; Path={auth.cookie_path()}; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}"

    def _redirect(self, where: str, cookies: list[str]):
        self.send_response(302)
        self.send_header("Location", auth.public_url() + where)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        for c in cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()

    def _sign_in(self, path: str, query: dict):
        """/auth/<provider>/start sends the browser to the provider; /auth/<provider>/callback signs it in."""
        m = re.fullmatch(r"/auth/(google|github)/(start|callback)", path)
        if not m:
            return self._send(404, b"Not found", "text/plain")
        pid, step = m.groups()
        clear_state = self._set_cookie(auth.STATE_COOKIE, "", 0)
        try:
            if step == "start":
                state = secrets.token_urlsafe(24)
                url = auth.sign_in_url(pid, state)
                self.send_response(302)
                self.send_header("Location", url)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.send_header("Set-Cookie", self._set_cookie(auth.STATE_COOKIE, state, 600))
                return self.end_headers()
            if query.get("error"):
                return self._redirect("/#/signin", [clear_state])  # the person cancelled at the provider
            state, expected = (query.get("state") or [""])[0], self._cookie(auth.STATE_COOKIE) or ""
            if not expected or not secrets.compare_digest(state, expected):
                raise auth.AuthError("That sign-in link had expired. Please try again.")
            user = auth.finish_sign_in(pid, (query.get("code") or [""])[0])
            token = auth.new_session(user["id"])
            return self._redirect("/#/", [clear_state, self._set_cookie(auth.SESSION_COOKIE, token, auth.SESSION_DAYS * 86400)])
        except auth.AuthError as e:
            return self._redirect("/#/signin?error=" + quote(str(e)), [clear_state])

    def _sign_out(self):
        auth.end_session(REQUEST.token)
        body = b'{"ok": true}'
        self._send(200, body, "application/json; charset=utf-8", {"Set-Cookie": self._set_cookie(auth.SESSION_COOKIE, "", 0)})

    def _dev_events(self):
        """Server-Sent Events for live reload: `hello` with this server's boot id, then `change` lists."""
        from . import dev

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(f"retry: 500\nevent: hello\ndata: {dev.BOOT_ID}\n\n".encode())
            self.wfile.flush()
            for files in dev.frontend_changes():
                msg = f"event: change\ndata: {json.dumps(files)}\n\n" if files else ": keep-alive\n\n"
                self.wfile.write(msg.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ApiError(413, "That upload is too large.")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise ApiError(400, "The request wasn't valid JSON.") from None
        if not isinstance(body, dict):
            raise ApiError(400, "The request must be a JSON object.")
        return body

    def _static(self, path: str):
        if path in ("/", "/index.html"):
            name = "index.html"
        elif path == "/privacy":
            name = "privacy.html"
        elif path.startswith("/static/"):
            name = path[len("/static/"):]
        else:
            return self._send(404, b"Not found", "text/plain")
        if not re.fullmatch(r"(fonts/)?[A-Za-z0-9_-][A-Za-z0-9_.-]*", name):
            return self._send(404, b"Not found", "text/plain")
        f = STATIC.joinpath(name)
        if not f.is_file():
            return self._send(404, b"Not found", "text/plain")
        ctype = "font/woff2" if name.endswith(".woff2") else mimetypes.guess_type(name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "text/javascript"):
            ctype += "; charset=utf-8"
        avatars = " https://lh3.googleusercontent.com https://avatars.githubusercontent.com" if HOSTED else ""  # account pictures
        csp = f"default-src 'self'; img-src 'self' data:{avatars}; font-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        extra = {"Content-Security-Policy": csp} if name.endswith(".html") else {}
        if name.startswith("fonts/"):
            extra["Cache-Control"] = "public, max-age=31536000, immutable"
        body = f.read_bytes()
        if DEV and name == "index.html":
            body = body.replace(b"</body>", b'<script src="static/dev-reload.js"></script>\n</body>')
        self._send(200, body, ctype, extra)

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")


def _free_port(preferred: int, host: str = "127.0.0.1") -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 20)):
        with socket.socket() as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


class Server(ThreadingHTTPServer):
    """One thread per request, but at most MAX_CONNECTIONS at once: the rest wait in the listen queue."""

    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        self._slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def make_server(port: int = 8765, exact: bool = False, host: str = "127.0.0.1", allowed_hosts: tuple[str, ...] = ()) -> Server:
    """`exact` binds the given port or fails; otherwise the next free port is used.

    Listening on any address but loopback makes this a hosted Lemma: it answers only the
    `allowed_hosts` (the public domain names it is reached by), binds exactly `port` and drops the subscription providers.
    """
    global HOSTED, ALLOWED_HOSTS
    HOSTED = host not in ("127.0.0.1", "localhost", "::1")
    if HOSTED and not allowed_hosts:
        raise ValueError("A hosted Lemma needs --allowed-hosts: the domain names it is reached by.")
    ALLOWED_HOSTS = LOCAL_HOSTS + tuple(h.strip().lower() for h in allowed_hosts if h.strip())
    return Server((host, port if exact or HOSTED else _free_port(port, host)), Handler)  # a host expects its own port
