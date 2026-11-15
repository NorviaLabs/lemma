"""The HTTP server: one thread per request up to a limit, the static files, sign-in and sign-out, and dispatching API
requests to their handlers (see core.route). It keeps no logs."""

from __future__ import annotations

import gzip
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import socket
import threading
import time
from contextlib import nullcontext
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from .. import auth, logs, metrics, store
from .core import ApiError, Request, STATIC, find_route


MAX_BODY = 56 * 1024 * 1024  # a 40 MB file, base64-encoded, plus a little
DEV = False  # set by `lemma --dev`: live-reload script and /api/dev/events
# Whether the server is bound to loopback. Lemma behaves the same on your own computer as hosted for others; this
# only decides how it binds (the address and port, live reload, opening the browser), so it is read only by
# make_server and __main__.main; tests/test_one_behaviour.py fails if it is read anywhere else.
ON_THIS_COMPUTER = True
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")
ALLOWED_HOSTS: tuple[str, ...] = LOCAL_HOSTS  # Host header names Lemma answers; `--allowed-hosts` adds more
RATE_LIMIT, RATE_WINDOW = 120, 600  # API writes per visitor address per 10 minutes, when hosted
MAX_CONNECTIONS = 32  # requests handled at once; more wait to be accepted
LARGE_BODY = 1024 * 1024  # a request body this big is an upload, held in memory while it is read
_uploads = threading.BoundedSemaphore(2)  # uploads handled at once, so a burst of them can't exhaust memory


def trusted_proxy(address: str) -> bool:
    """Whether a connection from `address` may name the visitor it carries (CF-Connecting-IP): those listed in
    LEMMA_TRUSTED_PROXIES (addresses or networks, comma-separated), or by default this machine and private networks,
    where a Cloudflare tunnel runs. A visitor reaching the server directly from the internet is neither."""
    try:
        ip = ipaddress.ip_address(str(address).split("%")[0])
    except ValueError:
        return False
    listed = os.environ.get("LEMMA_TRUSTED_PROXIES", "").strip()
    if listed:
        nets = []
        for item in listed.split(","):
            try:
                nets.append(ipaddress.ip_network(item.strip(), strict=False))
            except ValueError:
                continue
        return any(ip in net for net in nets)
    return ip.is_loopback or ip.is_private


COMPRESS_FROM = 1024  # bytes: smaller answers aren't worth compressing
COMPRESS_LEVEL = 6
_static_cache: dict[str, tuple[tuple[int, int], bytes, bytes, str]] = {}


def _compressible(ctype: str) -> bool:
    return ctype.startswith(("text/", "application/json", "application/javascript", "image/svg+xml"))


def _static_file(f) -> tuple[bytes, bytes, str]:
    """A static file's bytes, compressed bytes and ETag, made once per version of the file."""
    st = os.stat(str(f))
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _static_cache.get(str(f))
    if hit and hit[0] == stamp:
        return hit[1], hit[2], hit[3]
    body = f.read_bytes()
    packed = gzip.compress(body, 9)
    etag = '"' + hashlib.sha256(body).hexdigest()[:20] + '"'
    _static_cache[str(f)] = (stamp, body, packed, etag)
    return body, packed, etag


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
        # Cloudflare's tunnel names the visitor's address; anyone else could name any address, so only a trusted
        # proxy (the tunnel, on this machine or its private network) is believed.
        peer = self.client_address[0]
        return (self.headers.get("CF-Connecting-IP") or peer) if trusted_proxy(peer) else peer

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urlsplit(origin).netloc.lower() == (self.headers.get("Host") or "").lower()

    def end_headers(self):
        if auth.public_url().startswith("https://"):
            self.send_header("Strict-Transport-Security", "max-age=31536000")  # on every response, however it was sent
        super().end_headers()

    def _accepts_gzip(self) -> bool:
        return "gzip" in (self.headers.get("Accept-Encoding") or "").lower()

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None, packed: bytes | None = None):
        """Sends a response, compressed for a browser that accepts gzip when it's text worth compressing. `packed` is
        the body already compressed (static files keep theirs)."""
        if _compressible(ctype) and len(body) >= COMPRESS_FROM:
            extra = {**(extra or {}), "Vary": "Accept-Encoding"}
            if self._accepts_gzip():
                body = packed if packed is not None else gzip.compress(body, COMPRESS_LEVEL)
                extra["Content-Encoding"] = "gzip"
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

    def _json(self, status: int, obj, extra: dict | None = None):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", extra)

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
        token = self._cookie(auth.SESSION_COOKIE)
        url = urlsplit(self.path)
        path = url.path
        req = Request(user=auth.user_for(token) if token else None, query=parse_qs(url.query), headers=self.headers, token=token)
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
            return self._sign_out(req)  # not a route: it clears the session cookie
        n = self._length()
        if n is None:
            return self._json(400, {"error": "The request's Content-Length isn't a valid size."})
        if n > MAX_BODY:
            return self._json(413, {"error": "That upload is too large."})
        with _uploads if n > LARGE_BODY else nullcontext():
            return self._route(method, path, req)

    def _route(self, method: str, path: str, req: Request):
        found = find_route(method, path)
        if found is None:
            return self._json(404, {"error": "Not found."})
        r, args = found
        try:
            req.body = self._body() if method == "POST" else {}
            result = r.fn(req, *args)
        except metrics.SiteSpent as e:
            return self._json(429, {"error": str(e)})
        except ApiError as e:
            return self._json(e.status, {"error": e.message, "problems": e.problems})
        except Exception as e:
            eid = logs.report(f"{method} {r.pattern}", e)
            return self._json(500, {"error": "Something went wrong inside OpenLemma. Try again; if it keeps happening, "
                                             f"email contact@openlemma.org with error id {eid}."})
        if isinstance(result, str):
            return self._send(200, result.encode("utf-8"), "text/html; charset=utf-8", {"Content-Disposition": "attachment; filename=lesson.html"})
        return self._json(200, result, {"Cache-Control": "public, max-age=300"} if r.shared else None)

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

    def _sign_out(self, req: Request):
        auth.end_session(req.token)
        body = b'{"ok": true}'
        self._send(200, body, "application/json; charset=utf-8", {"Set-Cookie": self._set_cookie(auth.SESSION_COOKIE, "", 0)})

    def _dev_events(self):
        """Server-Sent Events for live reload: `hello` with this server's boot id, then `change` lists."""
        from .. import dev

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
        elif path in ("/privacy", "/terms", "/faq"):
            name = path[1:] + ".html"
        elif path.startswith("/static/"):
            name = path[len("/static/"):]
        else:
            return self._send(404, b"Not found", "text/plain")
        if not re.fullmatch(r"((fonts|app)/)?[A-Za-z0-9_-][A-Za-z0-9_.-]*", name):  # the app's modules are in app/
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
        if DEV and name == "index.html":
            body = f.read_bytes().replace(b"</body>", b'<script src="static/dev-reload.js"></script>\n</body>')
            return self._send(200, body, ctype, extra)
        body, packed, etag = _static_file(f)
        if not name.endswith(".html") and "Cache-Control" not in extra:
            # Scripts and styles: kept by the browser, but checked on every visit (a 304 when unchanged), so a deploy
            # shows at once. Pages stay uncached.
            extra.update({"Cache-Control": "no-cache", "ETag": etag})
            if etag in [t.strip() for t in (self.headers.get("If-None-Match") or "").split(",")]:
                self.send_response(304)
                for k, v in {"ETag": etag, "Cache-Control": "no-cache", "Vary": "Accept-Encoding"}.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", "0")
                return self.end_headers()
        self._send(200, body, ctype, extra, packed=packed)

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
        except Exception:  # the thread never started, so its slot is still taken
            self._slots.release()
            raise
        # A stop (KeyboardInterrupt) is let through untouched: it can land once the thread already runs and will give
        # the slot back itself, and releasing it here too would raise an error that socketserver swallows, with the stop.

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def make_server(port: int = 8765, exact: bool = False, host: str = "127.0.0.1", allowed_hosts: tuple[str, ...] = ()) -> Server:
    """`exact` binds the given port or fails; otherwise the next free port is used.

    Listening on any address but loopback hosts Lemma for others: it answers only the `allowed_hosts` (the public
    domain names it is reached by) and binds exactly `port`.
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
