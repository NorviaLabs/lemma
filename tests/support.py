"""What every test needs, in one place: a temporary LEMMA_HOME, accounts and sessions, the shipped example lesson,
a running server with an HTTP client, and calling the API as someone.

Importing this sets LEMMA_HOME to a temporary folder (before any Lemma module is imported) and installs the Jev
stand-in, so tests never touch a real home or a real service.

* ``call(fn, *args, body=, query=, headers=)``: call an API handler straight from a test, with a ``server.Request``
  as its route would make, as whoever ``sign_in(uid)`` (or ``act_as(profile)``) signed in; ``call_as(user, fn, ...)``
  names the account (None: signed out) for one call.
* ``account(name, full_name)``: a real account with a session cookie, for HTTP requests.
* ``Site()``: a server on a free loopback port (``hosted=True`` for one answering a public domain name); its
  ``req()`` returns a ``Reply`` that unpacks as ``(status, body, response)``, with ``.raw``, ``.json`` and ``.header()``.
* ``temp_home(test)``: a fresh LEMMA_HOME for one test, put back afterwards.
* ``saved_lesson(owner, ...)`` and ``strings(lesson)``: lessons saved as a finished build saves them.
"""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

TMP_HOME = tempfile.mkdtemp(prefix="lemma-test-")
os.environ["LEMMA_HOME"] = TMP_HOME

import fakejev  # noqa: E402,F401  Jev is essential, so every search and build asks this stand-in
from lemma import auth, lesson as L, server, store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = json.loads((ROOT / "lemma/examples/gallery/galton-1886.json").read_text())
SOURCE = (ROOT / "lemma/examples/galton-1886.txt").read_text()
NORM = L.normalize_for_match(SOURCE)
LESSON_ID = "a1b2c3d4e5f6"
SITE = "tools.example.com"  # the public domain name a hosted Site answers

# Every person signs in, on their own computer as when hosted, so tests act as a signed-in account too. TESTER is
# the Google account "tester": API calls made straight from a test and HTTP requests that carry session_cookie()
# act as the same account.
TESTER = hashlib.sha256(b"google:tester").hexdigest()[:16]


# ---------------------------------------------------------------- accounts and calling the API


_signed_in: dict | None = None  # who call() acts as by default: see sign_in


def sign_in(uid: str = TESTER) -> dict:
    """Signs `uid` in for API handlers called straight from a test (call), as a browser session would."""
    return act_as({"id": uid, "provider": "google", "name": "Tester", "email": f"{uid}@example.com", "avatar": "", "created": 0})


def act_as(user: dict | None) -> dict | None:
    """Makes `user` (a profile, or None for someone signed out) the account call() acts as from now on."""
    global _signed_in
    _signed_in = user
    return user


def sign_out():
    act_as(None)


def reset_server():
    """Puts back what server.make_server sets, as for a server on this computer, and signs nobody in."""
    server.http.ON_THIS_COMPUTER, server.http.ALLOWED_HOSTS = True, server.http.LOCAL_HOSTS
    auth.LOCAL_URL = ""
    sign_out()


def session_cookie(name: str = "tester") -> str:
    """A Cookie header for HTTP requests, from a real session of the Google account `name`."""
    return account(name).cookie


@dataclass
class Account:
    profile: dict
    token: str

    @property
    def id(self) -> str:
        return self.profile["id"]

    @property
    def cookie(self) -> str:
        """The Cookie header a browser signed in as this account sends."""
        return f"{auth.SESSION_COOKIE}={self.token}"


def account(name: str, full_name: str | None = None) -> Account:
    """A real Google account (`name`, shown as `full_name`), signed in with a new session."""
    profile = auth.upsert_user("google", name, full_name or name, f"{name}@example.com", "")
    return Account(profile, auth.new_session(profile["id"]))


_SIGNED_IN = object()


def request(user=_SIGNED_IN, body: dict | None = None, query: dict | None = None, headers: dict | None = None) -> server.Request:
    """The Request a route would make: from `user` (by default whoever sign_in signed in), with the JSON body, the
    query (name -> [values], as parse_qs gives it) and the headers."""
    return server.Request(user=_signed_in if user is _SIGNED_IN else user, body=body or {}, query=query or {}, headers=headers or {})


def call(fn, *args, user=_SIGNED_IN, body: dict | None = None, query: dict | None = None, headers: dict | None = None):
    """Calls an API handler as its route would: fn(request, *args), the args being what the path's pattern captured."""
    return fn(request(user, body, query, headers), *args)


def call_as(user: dict | None, fn, *args, body: dict | None = None, query: dict | None = None, headers: dict | None = None):
    """call() as `user` (a profile, or None for someone signed out)."""
    return call(fn, *args, user=user, body=body, query=query, headers=headers)


def refused(test, status: int, fn, *args, **kw) -> str:
    """Asserts that calling `fn` (as call_as does) is refused with `status`; returns the message."""
    with test.assertRaises(server.ApiError) as e:
        call_as(kw.pop("user", None), fn, *args, **kw)
    test.assertEqual(e.exception.status, status, e.exception.message)
    return e.exception.message


# ---------------------------------------------------------------- homes and lessons


def temp_home(test, prefix: str = "lemma-test-") -> str:
    """A fresh LEMMA_HOME for one test, put back when it ends."""
    home = tempfile.mkdtemp(prefix=prefix)
    env = patch.dict(os.environ, {"LEMMA_HOME": home})
    env.start()
    test.addCleanup(env.stop)
    return home


def strings(x):
    """Every piece of text in a lesson: a source that grounds all its quotes, for a gallery lesson shipped without one."""
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


def saved_lesson(owner: str, lesson_id: str = LESSON_ID, lesson: dict | None = None, source: str | None = SOURCE, **fields) -> dict:
    """A lesson saved to `owner`'s library as a finished build saves it (the example unless `lesson` is given), with
    `fields` changed. A lesson without a `source` gets one made of its own text, so its quotes are grounded."""
    out = copy.deepcopy(lesson if lesson is not None else EXAMPLE)
    for k in ("example", "gallery"):
        out.pop(k, None)
    out.update(id=lesson_id, **fields)
    store.save_lesson(out, source if source is not None else "\n\n".join(strings(out)), owner)
    return out


# ---------------------------------------------------------------- a running server


class Reply(tuple):
    """An HTTP answer: unpacks as (status, body, response), where body is the decoded JSON when it is JSON, or the
    raw bytes; also .status, .body, .raw, .json and .header(name)."""

    def __new__(cls, status: int, raw: bytes, response):
        try:
            body = json.loads(raw) if raw[:1] in (b"{", b"[") or raw.strip() in (b"null", b"true", b"false") else raw
        except ValueError:
            body = raw
        self = super().__new__(cls, (status, body, response))
        self.raw = raw
        return self

    status = property(lambda self: self[0])
    body = property(lambda self: self[1])
    response = property(lambda self: self[2])

    @property
    def json(self):
        return json.loads(self.raw)

    def header(self, name: str) -> str | None:
        return self.response.getheader(name)


class Site:
    """A Lemma server on a free loopback port, for the length of a `with` block.

    By default it is a server on this computer (as `lemma` runs), answering localhost. `hosted=True` makes one that
    answers a public domain name (SITE) only, as `lemma --host 0.0.0.0 --allowed-hosts` does; `env` is set while it
    runs (such as LEMMA_PUBLIC_URL), and the server's globals are put back afterwards. `cookie` is sent with every
    request unless a request gives its own."""

    def __init__(self, hosted: bool = False, env: dict | None = None, hosts=(SITE,), cookie: str | None = None, exact: bool = True):
        self.hosted, self.env, self.hosts, self.cookie, self.exact = hosted, env or {}, hosts, cookie, exact

    def __enter__(self):
        self.old_env = {k: os.environ.get(k) for k in self.env}
        self.old_dev = server.http.DEV
        os.environ.update(self.env)
        if self.hosted:
            self.httpd = server.make_server(0, host="0.0.0.0", allowed_hosts=self.hosts)
        else:
            self.httpd = server.make_server(0, exact=self.exact)
        self.port = self.httpd.server_address[1]
        self.host = SITE if self.hosted else f"localhost:{self.port}"
        self.origin = f"https://{SITE}" if self.hosted else f"http://{self.host}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.http.DEV = self.old_dev
        reset_server()
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def req(self, method: str, path: str, body=None, cookie: str | None = None, cookies: dict | None = None,
            headers: dict | None = None, origin: bool = True, timeout: float = 20) -> Reply:
        """Sends a request as a browser on this site would. A dict or list body is sent as JSON, bytes as they are.
        `cookie` is a Cookie header (default: the Site's), `cookies` a {name: value} jar instead; `origin=False`
        leaves out the Origin header."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        h = {"Host": self.host}
        if origin:
            h["Origin"] = self.origin
        jar = "; ".join(f"{k}={v}" for k, v in cookies.items()) if cookies else (cookie if cookie is not None else self.cookie)
        if jar:
            h["Cookie"] = jar
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        c.request(method, path, data, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return Reply(r.status, raw, r)


def set_cookies(response) -> dict:
    """{name: (value, attributes)} from every Set-Cookie header of a response."""
    out = {}
    for line in response.msg.get_all("Set-Cookie") or []:
        pair, _, attrs = line.partition(";")
        name, _, value = pair.partition("=")
        out[name.strip()] = (value, attrs)
    return out
