"""What every part of the API shares: the request a handler is given (Request), the errors it raises (ApiError), the
routes (route, find_route), the learner's provider, the shipped example and gallery, and the quality checks a lesson
passes before anyone reads it."""

from __future__ import annotations

import dataclasses
import json
import os
import re
import threading
from importlib import resources
from typing import Any, Callable, NamedTuple

from .. import checks, levels, metrics, store
from ..llm import DEFAULT_PROVIDER, PROVIDERS, ProviderError, make_provider


STATIC = resources.files("lemma").joinpath("static")
EXAMPLES = resources.files("lemma").joinpath("examples")
_lock = threading.Lock()  # guards the papers, searches, reading slots and running jobs kept in memory


class ApiError(Exception):
    def __init__(self, status: int, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.status, self.message, self.problems = status, message, problems


@dataclasses.dataclass
class Request:
    """What an API handler is given: who is asking and what they sent. The HTTP handler makes one per request and
    passes it along; a test makes its own."""

    user: dict | None = None  # the signed-in account's profile, or None
    body: dict = dataclasses.field(default_factory=dict)  # a POST's JSON object; {} otherwise
    query: dict = dataclasses.field(default_factory=dict)  # the query string, as parse_qs gives it: name -> [values]
    headers: Any = dataclasses.field(default_factory=dict)  # the request's headers (anything with .get)
    token: str | None = None  # the session token from the cookie, if any

    def param(self, name: str, default: str | None = None) -> str | None:
        """The first value of a query parameter."""
        return (self.query.get(name) or [default])[0]

    def credential(self) -> tuple[str, str, str]:
        """The learner's provider, model and key. The browser keeps them and sends them with each request."""
        h = self.headers
        return (h.get("X-Lemma-Provider") or DEFAULT_PROVIDER, h.get("X-Lemma-Key") or "", h.get("X-Lemma-Model") or "")

    def owner(self) -> str:
        """Whose papers, builds and library this request uses: the signed-in account's."""
        if not self.user:
            raise ApiError(401, "Sign in to find sources, build lessons and keep a library.")
        return self.user["id"]

    def is_admin(self) -> bool:
        """Whether the signed-in account is one of LEMMA_ADMINS (comma-separated emails)."""
        admins = {e.strip().lower() for e in os.environ.get("LEMMA_ADMINS", "").split(",") if e.strip()}
        return bool(self.user) and self.user["email"].lower() in admins

    def admin(self) -> None:
        if not self.is_admin():
            raise ApiError(404, "Not found.")  # the same answer as an unknown address, so admin pages aren't advertised


class Route(NamedTuple):
    method: str
    pattern: str  # a regular expression for the whole path; its one group, if any, is the handler's argument
    fn: Callable
    shared: bool  # the same for every visitor, so browsers and Cloudflare may keep it for a while


ROUTES: list[Route] = []
_exact: dict[tuple[str, str], Route] = {}  # routes without a parameter, by (method, path)
_patterns: list[tuple[Route, re.Pattern]] = []


def route(method: str, pattern: str, shared: bool = False):
    """Registers an API handler, called as fn(request) or, with a group in the pattern, fn(request, group). A path
    without a parameter is matched exactly and wins over any pattern (so /api/gallery/community is never a slug)."""
    def add(fn):
        r = Route(method, pattern, fn, shared)
        ROUTES.append(r)
        if re.escape(pattern) == pattern:
            _exact[(method, pattern)] = r
        else:
            _patterns.append((r, re.compile(pattern)))
        return fn
    return add


def find_route(method: str, path: str) -> tuple[Route, tuple] | None:
    """The route for a request and its arguments, or None."""
    if r := _exact.get((method, path)):
        return r, ()
    for r, rx in _patterns:
        if r.method == method and (m := rx.fullmatch(path)):
            return r, m.groups()
    return None


def provider_from_request(req: Request, pid: str | None = None):
    req_pid, key, model = req.credential()
    if pid and pid != req_pid:
        raise ApiError(400, "Save this provider on your account page first.")
    if req_pid not in PROVIDERS:  # e.g. one OpenLemma used to offer, still saved in the learner's browser
        raise ApiError(400, "OpenLemma doesn't offer this AI provider. Choose another on your account page.")
    try:
        return make_provider(req_pid, key, model, req.user["id"] if req.user else None)  # a subscription builds with this account's sign-in
    except ProviderError as e:
        raise ApiError(400, str(e)) from None


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
    try:
        if store.lesson_files(lesson_id, owner) is None:
            return None
        return store.read_source(lesson_id, owner)
    except (KeyError, OSError, ValueError):
        return None


NO_SOURCE = "OpenLemma no longer has this lesson's source text, so it can't confirm the quotes. Bring the source again to rebuild it."


class _NotNow(Exception):
    """A check that couldn't run now (too slow, busy, or the account already checking): said, never remembered."""

    def __init__(self, error: ApiError):
        self.error = error


def require_valid(lesson, source_text: str | None):
    """Runs the lesson's checks, in a separate process with a time limit (checks.run_isolated), and refuses a lesson
    that fails them."""
    try:
        problems = checks.run_isolated(lesson, source_text)
    except checks.Refused as r:
        raise ApiError(r.status, r.message) from None
    if problems:
        raise ApiError(422, f"This lesson didn't pass {len(problems)} quality check{'s' * (len(problems) != 1)}.", list(problems))


def _run_checks(lesson, source, account: str | None = None) -> list[str]:
    """One run of the checks. For a lesson an account wrote (`account`), that account runs one check at a time, within
    its daily allowance; versions already checked never get here, so they cost nothing."""
    try:
        if account:
            with checks.account_slot(account):
                if not metrics.take(account, "check"):
                    raise ApiError(429, f"You've used today's {metrics.limit('check')} lesson checks. They reset at midnight UTC.")
                require_valid(lesson, source)
        else:
            require_valid(lesson, source)
    except checks.Refused as r:
        raise _NotNow(ApiError(r.status, r.message)) from None
    except ApiError as e:
        if e.status != 422 or not e.problems:
            raise _NotNow(e) from None
        return list(e.problems)
    return []


def ensure_checked(lesson_and_source, known_as: tuple | None = None, account: str | None = None):
    """Refuses a lesson that fails its checks. Each version is checked once, however many ask at once, and the result
    outlives a restart (checks.py). `lesson_and_source()` gives (lesson, source) only if they're needed: a lesson
    known by its unchanged files (`known_as`) needs neither. `account` is whoever wrote the lesson, when it was a
    person rather than OpenLemma: their checks take their turn and allowance."""
    try:
        found = checks.problems(lesson_and_source, lambda lesson, source: _run_checks(lesson, source, account), known_as)
    except _NotNow as n:
        raise n.error from None
    if found:
        raise ApiError(422, f"This lesson didn't pass {len(found)} quality check{'s' * (len(found) != 1)}.", list(found))


def _stamp(path) -> tuple | None:
    """A shipped file's size and time, so a lesson shipped with OpenLemma is known by its files too."""
    try:
        st = os.stat(str(path))
        return (st.st_mtime_ns, st.st_size)
    except (OSError, TypeError):
        return None


def _library_key(owner: str, lesson_id: str) -> tuple | None:
    files = store.lesson_files(lesson_id, owner)
    return ("library", owner, lesson_id, files) if files else None


def _provider(req: Request):
    p = provider_from_request(req)
    ok, msg = p.available()
    if not ok:
        raise ApiError(400, msg)
    return p


def _parse_level(body) -> str:
    level = levels.parse(body.get("level"))
    if level is None:
        raise ApiError(400, "Choose a level: " + ", ".join(name for name, _ in levels.LEVELS.values()) + ".")
    return level
