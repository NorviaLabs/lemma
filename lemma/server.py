"""Lemma's local web server. It listens only on this computer and keeps no logs."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import socket
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import urlsplit

from . import __version__, chatgpt, export, generate, ingest, search, store
from . import lesson as L
from .llm import DEFAULT_PROVIDER, PROVIDERS, ProviderError, make_provider

MAX_BODY = 64 * 1024 * 1024
STATIC = resources.files("lemma").joinpath("static")
EXAMPLES = resources.files("lemma").joinpath("examples")

DEV = False  # set by `lemma --dev`: live-reload script and /api/dev/events

PAPERS: dict[str, dict] = {}  # paper_id -> {text, title, url, kind, pages}
SOURCES: dict[str, str] = {}  # lesson id -> paper text, for lessons built in this session
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


def provider_from_request(pid: str | None = None):
    req_pid, key, model = _credential()
    if pid and pid != req_pid:
        raise ApiError(400, "Save this provider in Settings first.")
    try:
        return make_provider(req_pid, key, model)
    except ProviderError as e:
        raise ApiError(400, str(e)) from None


def load_example() -> tuple[dict, str]:
    lesson = json.loads(EXAMPLES.joinpath("galton-1886.json").read_text(encoding="utf-8"))
    source = EXAMPLES.joinpath("galton-1886.txt").read_text(encoding="utf-8")
    return lesson, source


def source_for(lesson_id: str) -> str | None:
    if lesson_id in SOURCES:
        return SOURCES[lesson_id]
    try:
        return store.load_lesson(lesson_id)[1]
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
        "providers": [{"id": i.id, "name": i.name, "default_model": i.default_model, "key_url": i.key_url, "sign_in": not i.key_url} for i in PROVIDERS.values()],
        "library_count": len(store.list_lessons()),
    }


def api_models(_body):
    """Models offered by the provider in the request headers, read live with the learner's key. Also checks the key."""
    p = provider_from_request()
    try:
        models = p.models()
    except ProviderError as e:
        raise ApiError(502, str(e)) from None
    return {"provider": p.id, "models": models, "current": p.model}


def api_chatgpt(_body):
    return chatgpt.status()


def api_chatgpt_login(_body):
    """Starts a ChatGPT sign-in; the browser opens the returned page."""
    try:
        return {"url": chatgpt.start_sign_in()}
    except ProviderError as e:
        raise ApiError(409, str(e)) from None


def api_chatgpt_logout(_body):
    chatgpt.sign_out()
    return chatgpt.status()


def api_papers(body):
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
        PAPERS[pid] = {"text": paper.text, "title": paper.title, "url": paper.url, "kind": paper.kind, "pages": paper.pages}
        while len(PAPERS) > 20:
            PAPERS.pop(next(iter(PAPERS)))
    return {"paper_id": pid, "title": paper.title, "kind": paper.kind, "pages": paper.pages, "chars": len(paper.text), "url": paper.url}


FULL_TEXT = 4000  # characters; a shorter page is usually just an abstract


def _first_readable(urls: list[str]):
    """Several copies of one search result: the first full text Lemma can read, else the first copy's reason."""
    first, short = None, False
    for u in urls:
        try:
            paper = ingest.from_url(u)
        except ingest.IngestError as e:
            first = first or e
            continue
        if len(paper.text) >= FULL_TEXT:
            return paper
        short = True
    if short or not first:
        raise ingest.IngestError("Lemma could only find a short summary of this one, not the full text. Try another result, or download it and upload the PDF.")
    raise first


def api_search(body):
    try:
        return search.search(str(body.get("query", "")))
    except search.SearchError as e:
        raise ApiError(422, str(e)) from None


def _paper(body) -> dict:
    p = PAPERS.get(str(body.get("paper_id", "")))
    if not p:
        raise ApiError(404, "Lemma no longer has that paper in memory. Please bring it again.")
    return p


def _provider():
    p = provider_from_request()
    ok, msg = p.available()
    if not ok:
        raise ApiError(400, msg)
    return p


def api_outline(body):
    paper = _paper(body)
    job = generate.Job("outline")
    generate.start(job, generate.make_outline, _provider(), paper["text"], str(body.get("audience", ""))[:300])
    return {"id": job.id}


def api_build(body):
    paper = _paper(body)
    outline = body.get("outline")
    problems = generate.check_outline(outline, paper["text"])
    if problems:
        raise ApiError(400, "The outline isn't valid: " + "; ".join(problems[:3]))
    provider = _provider()
    job = generate.Job("build")
    lesson_id = uuid.uuid4().hex[:12]
    SOURCES[lesson_id] = paper["text"]
    generate.start(job, generate.build_lesson, provider, paper, outline, str(body.get("audience", ""))[:300], lesson_id)
    return {"id": job.id, "lesson_id": lesson_id}


def api_job(job_id):
    job = generate.JOBS.get(job_id)
    if not job:
        raise ApiError(404, "That job has finished or expired.")
    return job.snapshot()


def api_job_cancel(job_id):
    job = generate.JOBS.get(job_id)
    if job:
        job.cancelled.set()
    return {"ok": True}


def api_example(_body):
    lesson, source = load_example()
    require_valid(lesson, source)  # never show a lesson that fails its checks, even ours
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
    source = source_for(lid) or None
    if source is None:
        raise ApiError(409, "Lemma no longer has this lesson's paper text, so it can't confirm the quotes. Bring the paper again to rebuild it.")
    lesson = {k: v for k, v in lesson.items() if k != "plan"}
    require_valid(lesson, source)
    store.save_lesson(lesson, source)
    return {"ok": True, "id": lid}


def api_lessons(_body):
    return store.list_lessons()


def api_lesson(lesson_id):
    try:
        return store.load_lesson(lesson_id)[0]
    except (KeyError, OSError, ValueError):
        raise ApiError(404, "That lesson isn't in your library.") from None


def api_lesson_delete(lesson_id):
    try:
        store.delete_lesson(lesson_id)
    except KeyError:
        raise ApiError(404, "That lesson isn't in your library.") from None
    return {"ok": True}


def api_export(body):
    lesson = body.get("lesson")
    if not isinstance(lesson, dict):
        raise ApiError(400, "No lesson to export.")
    if lesson.get("example"):
        source = load_example()[1]
    else:
        source = source_for(str(lesson.get("id", ""))) or None
    lesson = {k: v for k, v in lesson.items() if k != "plan"}
    require_valid(lesson, source)
    return export.lesson_html(lesson)


ROUTES = [
    ("GET", r"/api/status", api_status, False),
    ("GET", r"/api/models", api_models, False),
    ("GET", r"/api/chatgpt", api_chatgpt, False),
    ("POST", r"/api/chatgpt/login", api_chatgpt_login, False),
    ("POST", r"/api/chatgpt/logout", api_chatgpt_logout, False),
    ("POST", r"/api/papers", api_papers, False),
    ("POST", r"/api/search", api_search, False),
    ("POST", r"/api/outline", api_outline, False),
    ("POST", r"/api/build", api_build, False),
    ("GET", r"/api/jobs/([a-f0-9]{12})", api_job, True),
    ("POST", r"/api/jobs/([a-f0-9]{12})/cancel", api_job_cancel, True),
    ("GET", r"/api/example", api_example, False),
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

    def log_message(self, format, *args):  # Lemma keeps no usage logs
        pass

    def _allowed_host(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        return name in ("localhost", "127.0.0.1", "[::1]")

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
        path = urlsplit(self.path).path
        if DEV and method == "GET" and path == "/api/dev/events":
            return self._dev_events()
        if method == "GET" and not path.startswith("/api/"):
            return self._static(path)
        if method != "GET" and not self._same_origin():
            return self._json(403, {"error": "Cross-origin requests are not allowed."})
        for m, pattern, fn, has_arg in ROUTES:
            if m != method:
                continue
            match = re.fullmatch(pattern, path)
            if not match:
                continue
            try:
                if has_arg:
                    result = fn(match.group(1))
                else:
                    result = fn(self._body() if method == "POST" else {})
            except ApiError as e:
                return self._json(e.status, {"error": e.message, "problems": e.problems})
            except Exception as e:
                return self._json(500, {"error": f"Something went wrong inside Lemma ({e.__class__.__name__}: {e})."})
            if isinstance(result, str):
                return self._send(200, result.encode("utf-8"), "text/html; charset=utf-8", {"Content-Disposition": "attachment; filename=lesson.html"})
            return self._json(200, result)
        return self._json(404, {"error": "Not found."})

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
        csp = "default-src 'self'; img-src 'self' data:; font-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        extra = {"Content-Security-Policy": csp} if name == "index.html" else {}
        if name.startswith("fonts/"):
            extra["Cache-Control"] = "public, max-age=31536000, immutable"
        body = f.read_bytes()
        if DEV and name == "index.html":
            body = body.replace(b"</body>", b'<script src="/static/dev-reload.js"></script>\n</body>')
        self._send(200, body, ctype, extra)

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")


def _free_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 20)):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_server(port: int = 8765, exact: bool = False) -> ThreadingHTTPServer:
    """`exact` binds the given port or fails; otherwise the next free port is used."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port if exact else _free_port(port)), Handler)
    httpd.daemon_threads = True
    return httpd
