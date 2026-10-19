"""Lemma's web server, for signed-in accounts, the same on your own computer as hosted. It keeps no logs."""

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
from contextlib import contextmanager, nullcontext
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, quote, urlsplit

from . import __version__, auth, categorize, chatgpt, export, generate, ingest, jev, logs, metrics, search, store
from . import lesson as L
from .llm import DEFAULT_PROVIDER, PROVIDERS, ProviderError, make_provider

MAX_BODY = 56 * 1024 * 1024  # a 40 MB file, base64-encoded, plus a little
STATIC = resources.files("lemma").joinpath("static")
EXAMPLES = resources.files("lemma").joinpath("examples")

DEV = False  # set by `lemma --dev`: live-reload script and /api/dev/events
# The one difference between running on your own computer and hosting for others: the ChatGPT subscription, offered
# only by a server bound to this computer, since it keeps one person's ChatGPT tokens on the server's disk. Everything
# else behaves the same either way, so this is read only by providers(), _chatgpt_only() and make_server (which binds
# the address and port and allows live reload); tests/test_one_behaviour.py fails if it is read anywhere else.
ON_THIS_COMPUTER = True
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")
ALLOWED_HOSTS: tuple[str, ...] = LOCAL_HOSTS  # Host header names Lemma answers; `--allowed-hosts` adds more

PAPERS: dict[str, dict] = {}  # paper_id -> {text, title, url, kind, pages, owner}
SOURCES: dict[tuple, str] = {}  # (owner, lesson id) -> paper text, for lessons built in this session
RATE_LIMIT, RATE_WINDOW = 120, 600  # API writes per visitor address per 10 minutes, when hosted
KEEP_PAPERS, KEEP_SOURCES = 5, 200  # papers kept per person, and paper texts kept in all
READING_EACH, READING = 2, 6  # links and uploads being read at once, per account and in all, when hosted
_reading: dict[str | None, int] = {}
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


def _owner() -> str:
    """Whose papers, builds and library this request uses: the signed-in account's."""
    user = getattr(REQUEST, "user", None)
    if not user:
        raise ApiError(401, "Sign in to find papers, build lessons and keep a library.")
    return user["id"]


def provider_from_request(pid: str | None = None):
    req_pid, key, model = _credential()
    if pid and pid != req_pid:
        raise ApiError(400, "Save this provider in Settings first.")
    if req_pid not in PROVIDERS:  # e.g. one OpenLemma used to offer, still saved in the learner's browser
        raise ApiError(400, "OpenLemma doesn't offer this AI provider. Choose another in Settings.")
    if req_pid not in providers():
        raise ApiError(400, "This provider is only available when OpenLemma runs on your own computer.")
    try:
        return make_provider(req_pid, key, model)
    except ProviderError as e:
        raise ApiError(400, str(e)) from None


def providers() -> dict:
    """The providers this server offers: all of them, except the ChatGPT subscription when hosted for others."""
    return {i: p for i, p in PROVIDERS.items() if i != "chatgpt" or ON_THIS_COMPUTER}


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


NO_SOURCE = "OpenLemma no longer has this lesson's source text, so it can't confirm the quotes. Bring the source again to rebuild it."


def require_valid(lesson, source_text: str | None):
    problems = L.check_lesson(lesson, source_text)
    if problems:
        raise ApiError(422, f"This lesson didn't pass {len(problems)} quality check{'s' * (len(problems) != 1)}.", list(problems))


# ---------------------------------------------------------------- API


def api_status(_body):
    try:
        p = provider_from_request()
    except ApiError:  # a saved provider this server doesn't offer: report the default, unconnected, so Settings can offer the rest
        p = make_provider(DEFAULT_PROVIDER)
    ok, msg = p.available()
    return {
        "version": __version__,
        "provider": {"id": p.id, "name": p.name, "model": p.model, "label": p.label, "ok": ok, "message": msg},
        "providers": [{"id": i.id, "name": i.name, "default_model": i.default_model, "key_url": i.key_url, "sign_in": not i.key_url} for i in providers().values()],
        "library_count": len(store.list_lessons(_owner())) if getattr(REQUEST, "user", None) else 0,
        "user": getattr(REQUEST, "user", None),
        "sign_in": auth.providers(),
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


def _chatgpt_only():
    if not ON_THIS_COMPUTER:
        raise ApiError(404, "Not found.")


def api_chatgpt(_body):
    _chatgpt_only()
    return chatgpt.status()


def api_chatgpt_login(_body):
    """Starts a ChatGPT sign-in; the browser opens the returned page."""
    _chatgpt_only()
    try:
        return {"url": chatgpt.start_sign_in()}
    except ProviderError as e:
        raise ApiError(409, str(e)) from None


def api_chatgpt_logout(_body):
    _chatgpt_only()
    chatgpt.sign_out()
    return chatgpt.status()


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


def api_papers(body):
    owner = _owner()
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
        if not metrics.take(owner, "search"):
            raise ApiError(429, f"You've used today's {metrics.limit('search')} searches. They reset at midnight UTC.")
        sid = uuid.uuid4().hex[:12]
        record = SEARCHES[sid] = {"owner": owner, "query": query, "done": False, "progress": None, "result": None, "error": "", "created": time.time()}
    metrics.count("search")

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
        raise ApiError(404, "OpenLemma no longer has that source in memory. Please bring it again.")
    return p


def _provider():
    p = provider_from_request()
    ok, msg = p.available()
    if not ok:
        raise ApiError(400, msg)
    return p


def _new_job(kind: str, job_id: str | None = None) -> generate.Job:
    """A job, counted against the running caps and registered in the same step, so parallel requests can't both fit."""
    owner = _owner()
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


def _job(job_id: str) -> generate.Job | None:
    job = generate.JOBS.get(job_id)
    return job if job and job.owner == _owner() else None


def api_outline(body):
    paper = _paper(body)
    provider = _provider()
    job = _new_job("outline")
    _start(job, generate.make_outline, provider, paper["text"], str(body.get("audience", ""))[:300])
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
    _start(job, generate.build_lesson, provider, paper, outline, str(body.get("audience", ""))[:300], lesson_id)
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
    job = _new_job("request", record["id"])
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
    try:
        persist(job)  # Persist before any external work begins.
    except BaseException:
        _forget(job)
        raise

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
    _start(job, run)
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
                if s.get("paper_id"):
                    p = _paper(s)
                    request["sources"].append({"urls": [], "title": p["title"][:300], "upload": {k: p[k] for k in ("text", "title", "kind", "url")}})
                    continue
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


def api_event(body):
    """An anonymous count from the browser, such as a goal reached; only the event's name is kept."""
    if body.get("name") in metrics.BROWSER_EVENTS:
        metrics.count(body["name"])
    return {}


def api_stats(_body):
    """Daily counts, for the accounts named in LEMMA_ADMINS (comma-separated emails) on a hosted Lemma."""
    user = getattr(REQUEST, "user", None)
    admins = {e.strip().lower() for e in os.environ.get("LEMMA_ADMINS", "").split(",") if e.strip()}
    if not user or user["email"].lower() not in admins:
        raise ApiError(404, "Not found.")
    return metrics.report()


def api_example(_body):
    lesson, source = load_example()
    require_valid(lesson, source)  # never show a lesson that fails its checks, even ours
    return lesson


def card_quote(quote: str | None, most: int = 32) -> str | None:
    """A verbatim run of whole sentences from a quote, short enough to set large on a gallery card. Sentences
    under five words (headings such as "Reply to Objection 1.") are skipped; a long sentence is cut with an ellipsis."""
    if not quote:
        return quote
    sentences = [s for s in re.split(r"(?<=[.!?;])\s+", quote.strip()) if len(s.split()) >= 5] or [quote.strip()]
    words = []
    for s in sentences:
        if words and len(words) + len(s.split()) > most:
            break
        words += s.split()
    return " ".join(words[:most]).rstrip(",;:") + ("…" if len(words) > most else "")


def short_authors(authors: str | None) -> str:
    """Authors as a card credits them: a single author in full, two by surname, more as "First et al."
    Notes in brackets (translators, commentary) are dropped, and where a part names who wrote the words
    ("opinion delivered by Chief Justice Earl Warren"), that person is credited."""
    text = re.sub(r"\s*\([^)]*\)", "", authors or "").strip()
    parts = [p.strip() for p in text.split(";") if p.strip()]
    by = [p.rsplit(" by ", 1)[1] for p in parts if " by " in p]
    text = by[-1] if by else (parts[0] if parts else "")
    etal = bool(re.search(r"\bet al\.?", text))
    names = [n for n in re.split(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*", re.sub(r",?\s*\bet al\.?", "", text)) if n.strip()]
    if not names:
        return ""
    if len(names) == 1 and not etal:
        return names[0]
    def surname(name):  # the last word that isn't initials, with a particle such as "von" kept; capitals tamed
        words = name.split()
        keep = [i for i, w in enumerate(words) if not re.fullmatch(r"[A-Z]{1,3}\.?|(?:[A-Z]\.-?)+[A-Z]?\.?", w)]
        i = keep[-1] if keep else 0
        word = words[i].title() if words[i].isupper() else words[i]
        return f"{words[i - 1]} {word}" if i > 0 and words[i - 1] in ("von", "van", "de", "der", "da", "di", "le", "la") else word
    return f"{surname(names[0])} and {surname(names[1])}" if len(names) == 2 and not etal else f"{surname(names[0])} et al."


def quote_author(lesson: dict, block: dict) -> str:
    """Who wrote a quote: its own source in a combined lesson, otherwise the lesson's source."""
    source = next((s for s in lesson.get("sources") or [] if s.get("id") == block.get("source_id")), None)
    return short_authors((source or {}).get("authors") or lesson["source"].get("authors"))


def gallery_cover(lesson: dict) -> dict:
    """The concept a gallery card shows: the first with a model to draw; without models, the one with the
    shortest quote, which the card sets as a poster."""
    with_model = [c for c in lesson["concepts"] if c.get("model")]
    return with_model[0] if with_model else min(lesson["concepts"], key=lambda c: len(c["understand"].get("quote") or "x" * 9999))


def api_gallery(_body):
    items = []
    for entry in gallery_index():
        lesson, _ = load_gallery(entry["slug"])
        cover = next((c for c in lesson["concepts"] if c["id"] == entry.get("cover")), None) or gallery_cover(lesson)
        items.append({**lesson["gallery"], "title": lesson["title"], "source": lesson["source"],
                      "concepts": [c["title"] for c in lesson["concepts"]],
                      "cover": {"title": cover["title"], "idea": cover["idea"], "model": cover.get("model"),
                                "quote": card_quote(cover["understand"].get("quote")), "quote_author": quote_author(lesson, cover["understand"]),
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
        raise ApiError(409, NO_SOURCE)
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
            job = generate.JOBS.get(lesson_id)
            if job and job.owner == _owner() and job.status == "running":
                raise ApiError(409, "This lesson is still building. Cancel the build first, then delete it.")
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
    # Shipped lessons are exported as shipped, never as sent, so anyone may download them without
    # the server checking a model a stranger wrote.
    if isinstance(lesson.get("gallery"), dict):
        lesson, source = load_gallery(str(lesson["gallery"].get("slug", "")))
    elif lesson.get("example"):
        lesson, source = load_example()
    else:
        source = source_for(str(lesson.get("id", "")), _owner())
        if not source:
            raise ApiError(409, NO_SOURCE)
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
    ("POST", r"/api/papers", api_papers, False),
    ("POST", r"/api/search", api_search, False),
    ("GET", r"/api/search/([a-f0-9]{12})", api_search_status, True),
    ("POST", r"/api/outline", api_outline, False),
    ("POST", r"/api/build", api_build, False),
    ("GET", r"/api/jobs/([a-f0-9]{12})", api_job, True),
    ("POST", r"/api/jobs/([a-f0-9]{12})/cancel", api_job_cancel, True),
    ("POST", r"/api/event", api_event, False),
    ("GET", r"/api/stats", api_stats, False),
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

    def _host_name(self) -> str:
        host = (self.headers.get("Host") or "").lower()
        return host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"

    def _allowed_host(self) -> bool:
        return self._host_name() in ALLOWED_HOSTS

    def _visitor(self) -> str:
        # Cloudflare's tunnel is the only way into a hosted server, and it names the visitor's address.
        return self.headers.get("CF-Connecting-IP") or self.client_address[0]

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urlsplit(origin).netloc.lower() == (self.headers.get("Host") or "").lower()

    def end_headers(self):
        if auth.public_url().startswith("https://"):
            self.send_header("Strict-Transport-Security", "max-age=31536000")  # on every response, however it was sent
        super().end_headers()

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
        home = urlsplit(auth.public_url())
        # Another name it answers, such as www, moves to the public address, so sign-in cookies stay on one host;
        # so does a plain-HTTP visit, which Cloudflare's tunnel (the only way in) reports.
        moved = home.hostname and self._host_name() not in (home.hostname, *LOCAL_HOSTS)
        insecure = home.scheme == "https" and self.headers.get("X-Forwarded-Proto", "").lower() == "http"
        if moved or insecure:
            self.send_response(301)
            path = self.path if self.path.startswith("/") else "/"  # never a host taken from the request line
            self.send_header("Location", f"{home.scheme}://{home.netloc}{path}")
            self.send_header("Content-Length", "0")
            return self.end_headers()
        REQUEST.headers = self.headers
        REQUEST.token = self._cookie(auth.SESSION_COOKIE)
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
        if method == "GET" and path.startswith("/auth/"):
            return self._sign_in(path, parse_qs(url.query))
        if DEV and method == "GET" and path == "/api/dev/events":
            return self._dev_events()
        if method == "GET" and not path.startswith("/api/"):
            return self._static(path)
        if method != "GET" and not self._same_origin():
            return self._json(403, {"error": "Cross-origin requests are not allowed."})
        if method != "GET" and not self.server.allow(self._visitor()):
            self.send_response(429)
            body = json.dumps({"error": "Too many requests from your network. Wait a few minutes and try again."}).encode()
            for k, v in (("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body))), ("Retry-After", str(RATE_WINDOW))):
                self.send_header(k, v)
            self.end_headers()
            return self.wfile.write(body)
        if method == "POST" and path == "/api/logout":
            return self._sign_out()  # not in ROUTES: it clears the session cookie
        n = self._length()
        if n is None:
            return self._json(400, {"error": "The request's Content-Length isn't a valid size."})
        if n > MAX_BODY:
            return self._json(413, {"error": "That upload is too large."})
        with _uploads if n > LARGE_BODY else nullcontext():
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
                return self._json(500, {"error": f"Something went wrong inside OpenLemma (error {logs.report(f'{method} {pattern}', e)})."})
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
            store.adopt_unowned(user["id"])  # lessons saved before accounts existed go to the first account to sign in
            token = auth.new_session(user["id"])
            metrics.count("sign_in")
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

    def _length(self) -> int | None:
        """The request body's size, or None when Content-Length isn't a whole number of bytes."""
        value = (self.headers.get("Content-Length") or "0").strip()
        return int(value) if value.isdigit() else None

    def _body(self) -> dict:
        n = self._length() or 0  # _dispatch already refused a bad or oversized length
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
        elif path in ("/privacy", "/terms"):
            name = path[1:] + ".html"
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
        avatars = " https://lh3.googleusercontent.com https://avatars.githubusercontent.com"  # account pictures
        # Cloudflare Web Analytics, which Cloudflare adds to a hosted Lemma's pages: cookieless page-view counts.
        beacon, rum = " https://static.cloudflareinsights.com", " https://cloudflareinsights.com"
        live = " http://localhost:8400" if DEV else ""  # impeccable live mode, only under `lemma --dev`
        csp = f"default-src 'self'; script-src 'self'{beacon}{live}; img-src 'self' data:{avatars}; font-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'{rum}{live}; frame-ancestors 'none'; base-uri 'none'"
        extra = {"Content-Security-Policy": csp} if name.endswith(".html") else {}
        if name.startswith(("fonts/", "film-")):  # both are versioned by name, so they never change in place
            extra["Cache-Control"] = "public, max-age=31536000, immutable"
        if ctype.startswith("video/"):
            return self._send_ranged(f, ctype, extra)
        body = f.read_bytes()
        if DEV and name == "index.html":
            body = body.replace(b"</body>", b'<script src="static/dev-reload.js"></script>\n</body>')
        self._send(200, body, ctype, extra)

    def _send_ranged(self, f, ctype: str, extra: dict):
        """Serve a video in byte ranges: Safari and iOS won't play a <video> from a server that doesn't."""
        data = f.read_bytes()
        size = len(data)
        extra = dict(extra, **{"Accept-Ranges": "bytes"})
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", (self.headers.get("Range") or "").strip())
        if not m or m.groups() == ("", ""):
            return self._send(200, data, ctype, extra)
        first, last = m.groups()
        if first:
            start, end = int(first), min(int(last), size - 1) if last else size - 1
        else:  # "bytes=-N": the last N bytes
            start, end = max(0, size - int(last)), size - 1
        if start >= size or start > end:
            return self._send(416, b"", ctype, dict(extra, **{"Content-Range": f"bytes */{size}"}))
        self._send(206, data[start:end + 1], ctype, dict(extra, **{"Content-Range": f"bytes {start}-{end}/{size}"}))

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
        self._writes: dict[str, list[float]] = {}  # visitor address -> times of recent API writes
        self._writes_lock = threading.Lock()
        super().__init__(*args, **kwargs)

    def allow(self, visitor: str) -> bool:
        """Count one API write from `visitor`; False once RATE_LIMIT were made within RATE_WINDOW seconds."""
        now = time.time()
        with self._writes_lock:
            if len(self._writes) > 10_000:  # forget quiet addresses so the table can't grow without end
                self._writes = {k: v for k, v in self._writes.items() if v and v[-1] > now - RATE_WINDOW}
            recent = [t for t in self._writes.get(visitor, ()) if t > now - RATE_WINDOW]
            if len(recent) >= RATE_LIMIT:
                self._writes[visitor] = recent
                return False
            self._writes[visitor] = recent + [now]
            return True

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

    Listening on any address but loopback hosts Lemma for others: it answers only the `allowed_hosts` (the public
    domain names it is reached by), binds exactly `port`, and doesn't offer the ChatGPT subscription.
    """
    global ON_THIS_COMPUTER, ALLOWED_HOSTS, DEV
    ON_THIS_COMPUTER = host in ("127.0.0.1", "localhost", "::1")
    DEV = DEV and ON_THIS_COMPUTER  # dev mode loosens the CSP and adds /api/dev/events, so only on this computer
    if not ON_THIS_COMPUTER and not allowed_hosts:
        raise ValueError("A hosted Lemma needs --allowed-hosts: the domain names it is reached by.")
    metrics.check()  # a mistyped daily cap stops Lemma here, rather than quietly lifting the cap
    ALLOWED_HOSTS = LOCAL_HOSTS + tuple(h.strip().lower() for h in allowed_hosts if h.strip())
    httpd = Server((host, port if exact or not ON_THIS_COMPUTER else _free_port(port, host)), Handler)  # a host expects its own port
    auth.LOCAL_URL = f"http://localhost:{httpd.server_address[1]}" if ON_THIS_COMPUTER else ""  # where sign-ins return
    return httpd
