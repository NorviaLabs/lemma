"""Building lessons with Claude, through the Anthropic API: with the learner's own API key, or signed in with
their Claude Pro or Max subscription.

The subscription signs in the way Claude Code does: Lemma sends the learner to Claude's sign-in page with a
one-time challenge, the page shows them a code once they approve, they paste it back on their account page, and
Lemma swaps it for tokens that it keeps in the learner's account folder,
``$LEMMA_HOME/users/<account>/claude-auth.json`` (readable only by the server's user). Requests then carry the
token instead of a key, and count against the learner's plan.

The sign-in functions take the account (``owner``) whose sign-in they read: each account signs in and out on its
own, on the learner's own computer and hosted alike. ``None`` is nobody, as for a visitor who hasn't signed in
to OpenLemma.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import anthropic

from . import __version__, store
from .llm import Conversation, Provider, ProviderError, Reply, REQUEST_TIMEOUT

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 64000  # streamed, so a long concept has room without hitting request timeouts
# Models that take server-side fallbacks: a request their safety classifiers decline is re-run
# on the model Anthropic recommends for that kind of refusal, instead of failing the concept.
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
BASE_URL = None  # the SDK's default; tests point it at a stand-in

# The subscription sign-in: Claude Code's OAuth client, approved on claude.ai, with the code shown to the learner.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"  # Anthropic's page that shows the code to paste
SCOPES = "org:create_api_key user:profile user:inference"
OAUTH_BETA = "oauth-2025-04-20"  # requests with a token instead of a key must carry this
SIGN_IN_WAIT = 15 * 60  # seconds a started sign-in waits for its code

_lock = threading.Lock()
_logins: dict[str, dict] = {}  # per account, the sign-in in progress: {"verifier", "state", "url", "started"}, or {"error": str}


# ---------------------------------------------------------------- signing in with a subscription


def _auth_file(owner: str | None) -> Path | None:
    return store.account(owner) / "claude-auth.json" if owner else None


def _login(owner: str | None) -> dict:
    return _logins.setdefault(owner or "", {})


def load(owner: str | None) -> dict | None:
    path = _auth_file(owner)
    if path is None:
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _save(owner: str, tokens: dict, refresh: str = ""):
    account = tokens.get("account") if isinstance(tokens.get("account"), dict) else {}
    auth = {
        "access": tokens["access_token"],
        "refresh": tokens.get("refresh_token") or refresh,  # a refresh may keep the old refresh token
        "expires": time.time() + float(tokens.get("expires_in") or 3600),
        "email": account.get("email_address") or account.get("email") or "",
    }
    store.write_private(_auth_file(owner), json.dumps(auth))


def sign_out(owner: str | None):
    _login(owner).clear()
    if path := _auth_file(owner):
        path.unlink(missing_ok=True)


def status(owner: str | None) -> dict:
    """Like chatgpt.status: ``waiting`` while a sign-in has started and its code hasn't been pasted back yet."""
    auth = load(owner)
    login = _login(owner)
    if login.get("started", 0) and time.time() - login["started"] > SIGN_IN_WAIT:
        login.clear()
        login["error"] = "The sign-in expired. Start again from your account page."
    waiting = "verifier" in login
    return {"signed_in": bool(auth), "email": (auth or {}).get("email", ""), "error": login.get("error", ""), "waiting": waiting,
            "code": "", "url": login.get("url", "") if waiting else ""}


def _token_request(fields: dict) -> dict:
    req = urllib.request.Request(TOKEN_URL, data=json.dumps(fields).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": f"Lemma/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise ProviderError(f"Claude sign-in failed ({e.code}). Sign in again on your account page.") from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as e:
        raise ProviderError(f"Couldn't reach Anthropic to sign in ({e}).") from None
    if not isinstance(tokens, dict) or not tokens.get("access_token") or (fields["grant_type"] != "refresh_token" and not tokens.get("refresh_token")):
        raise ProviderError("Anthropic's sign-in reply was missing its tokens. Sign in again on your account page.")
    return tokens


def start_sign_in(owner: str | None) -> dict:
    """Makes a one-time challenge and the page to approve it on. Returns the status, with that page's address;
    the learner pastes the code the page shows them into finish_sign_in."""
    if not owner:
        raise ProviderError("Sign in to OpenLemma first.")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    query = {"code": "true", "client_id": CLIENT_ID, "response_type": "code", "redirect_uri": REDIRECT_URI, "scope": SCOPES,
             "code_challenge": challenge, "code_challenge_method": "S256", "state": state}
    login = _login(owner)
    login.clear()
    login.update(verifier=verifier, state=state, url=AUTHORIZE_URL + "?" + urllib.parse.urlencode(query), started=time.time())
    return status(owner)


def finish_sign_in(owner: str | None, pasted: str) -> dict:
    """Swaps the code the learner pasted (``code#state`` as Claude shows it, or the code alone) for tokens."""
    login = _login(owner)
    if "verifier" not in login:
        raise ProviderError("Start the sign-in from your account page first.")
    code, _, state = pasted.strip().partition("#")
    if not code:
        raise ProviderError("Paste the code Claude showed you after you approved the sign-in.")
    if state and state != login["state"]:
        raise ProviderError("That code is from a different sign-in. Start again from your account page.")
    try:
        tokens = _token_request({"grant_type": "authorization_code", "code": code, "state": login["state"], "client_id": CLIENT_ID,
                                 "redirect_uri": REDIRECT_URI, "code_verifier": login["verifier"]})
    except ProviderError as e:
        login.clear()
        login["error"] = str(e)
        raise
    _save(owner, tokens)
    login.clear()
    return status(owner)


def access_token(owner: str | None) -> tuple[str, float]:
    """(access token, when it expires), refreshed first if it's about to expire."""
    with _lock:
        auth = load(owner)
        if not auth:
            raise ProviderError("Sign in with your Claude account on your account page to build lessons.")
        if auth["expires"] - time.time() < 120:
            _save(owner, _token_request({"grant_type": "refresh_token", "refresh_token": auth["refresh"], "client_id": CLIENT_ID}), auth["refresh"])
            auth = load(owner)
        return auth["access"], auth["expires"]


# ---------------------------------------------------------------- providers


class ClaudeProvider(Provider):
    id = "claude"
    name = "Claude"
    sign_in = False  # a key, not a subscription

    def __init__(self, key: str, model: str = ""):
        self.key = key.strip()
        self.model = model or DEFAULT_MODEL
        self._client: anthropic.Anthropic | None = None
        self._effort: bool | None = None

    @property
    def label(self) -> str:
        return f"{self.name} ({self.model})"

    def available(self) -> tuple[bool, str]:
        if not self.key:
            return False, "Add your Claude key on your account page to build lessons."
        return True, ""

    def client(self) -> anthropic.Anthropic:
        ok, msg = self.available()
        if not ok:
            raise ProviderError(msg)
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.key, base_url=BASE_URL, timeout=REQUEST_TIMEOUT, max_retries=0)
        return self._client

    def models(self) -> list[dict]:
        with errors(self):
            listed = list(self.client().models.list())
        # Lemma asks for adaptive thinking, so older models without it are left out.
        return [{"id": m.id, "name": m.display_name or m.id, "context": m.max_input_tokens or 0}
                for m in listed if supports(m, "thinking", "types", "adaptive")]

    def takes_effort(self) -> bool:
        if self._effort is None:
            with errors(self):
                self._effort = supports(self.client().models.retrieve(self.model), "effort", "high")
        return self._effort

    def conversation(self, system, document):
        return ClaudeConversation(self, system, document)

    def request(self, system: str, messages: list, max_tokens: int = MAX_TOKENS) -> dict:
        """The parameters of every request, so a warm-up renders the same prefix as the real requests it serves."""
        params = dict(model=self.model, max_tokens=max_tokens, system=system, messages=messages, thinking={"type": "adaptive"})
        if self.takes_effort():
            params["output_config"] = {"effort": "high"}  # lessons are judged on quality; Opus 5.5 defaults to medium
        if self.model in FALLBACK_MODELS:
            params.update(betas=[FALLBACK_BETA], fallbacks="default")
        return params


    def warm(self, system, document):
        """Writes the system prompt and paper to the cache with one prefill-only request (max_tokens 0, so no output
        is billed), so concepts drafted in parallel read one copy instead of each writing its own. Returns the usage."""
        params = self.request(system, opening(document), max_tokens=0)  # not streamed: max_tokens 0 rejects streaming
        client = self.client()
        with errors(self):
            create = client.beta.messages.create if "betas" in params else client.messages.create
            return create(**params).usage


class ClaudeSubscriptionProvider(ClaudeProvider):
    """Claude with the learner's subscription: the same requests, carrying their sign-in's token instead of a key."""

    id = "claude-subscription"
    name = "Claude subscription"
    sign_in = True

    def __init__(self, model: str = "", owner: str | None = None):
        super().__init__("", model)
        self.owner = owner  # whose sign-in builds with
        self._expires = 0.0

    @property
    def label(self) -> str:
        return f"Claude ({self.model}) with your subscription"

    def available(self) -> tuple[bool, str]:
        if not load(self.owner):
            return False, "Sign in with your Claude account on your account page to build lessons."
        return True, ""

    def client(self) -> anthropic.Anthropic:
        if self._client is None or self._expires - time.time() < 120:  # a long build outlives a token: refresh between requests
            token, self._expires = access_token(self.owner)
            self._client = anthropic.Anthropic(auth_token=token, base_url=BASE_URL, timeout=REQUEST_TIMEOUT, max_retries=0,
                                               default_headers={"anthropic-beta": OAUTH_BETA})
        return self._client

    def request(self, system, messages, max_tokens=MAX_TOKENS):
        params = super().request(system, messages, max_tokens)
        if "betas" in params:  # a request's own betas replace the client's header, so the sign-in beta goes with them
            params["betas"] = [OAUTH_BETA, *params["betas"]]
        return params

def supports(model, *path: str) -> bool:
    """Whether a model's capabilities say yes at the end of `path`, e.g. ("effort", "high")."""
    node = model.capabilities
    try:
        for name in path:
            node = getattr(node, name)
        return bool(node.supported)
    except AttributeError:  # not listed: assume not
        return False


def opening(document: str) -> list:
    """The first message of every conversation: the paper, with a cache breakpoint at its end. Every concept shares
    the system prompt and paper but ends in its own task, so without this marker each request would cache only its
    own whole prompt and none would read another's."""
    return [{"role": "user", "content": [{"type": "text", "text": document, "cache_control": {"type": "ephemeral"}}]}]


class ClaudeConversation(Conversation):
    """The API keeps nothing, so each turn re-sends the paper and the conversation so far.
    The cache makes the repeated paper cheap, and replies go back exactly as Claude sent them."""

    def __init__(self, provider: ClaudeProvider, system: str, document: str):
        self.p = provider
        self.system = system
        self.messages: list = opening(document)

    def send(self, text, cancelled=None, on_progress=None):
        messages = self.messages + [{"role": "user", "content": text}]
        # The paper's breakpoint is shared by every concept; the automatic one caches this conversation's own turns for its repairs.
        params = self.p.request(self.system, messages) | {"cache_control": {"type": "ephemeral"}}
        client = self.p.client()
        with errors(self.p):
            stream_fn = client.beta.messages.stream if "betas" in params else client.messages.stream
            written = 0
            with stream_fn(**params) as stream:
                for event in stream:
                    if cancelled is not None and cancelled.is_set():
                        raise ProviderError("Cancelled.")  # leaving the block closes the stream
                    if on_progress and event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            written += len(event.delta.text)
                            on_progress("writing", written)
                        elif event.delta.type == "thinking_delta":
                            on_progress("thinking", written)
                final = stream.get_final_message()
        if final.stop_reason == "refusal":
            raise ProviderError("Claude declined to write this part of the lesson. Try another model on your account page.")
        reply = "".join(b.text for b in final.content if b.type == "text")
        self.messages = messages + [{"role": "assistant", "content": final.content}]
        return Reply(text=reply, stop_reason="max_tokens" if final.stop_reason == "max_tokens" else "end_turn")


class errors:
    """Turns the SDK's errors into messages for the learner."""

    def __init__(self, provider: ClaudeProvider):
        self.p = provider

    def __enter__(self):
        return self

    def __exit__(self, kind, e, tb):
        if e is None or isinstance(e, ProviderError):
            return False
        if isinstance(e, anthropic.APIStatusError):
            body = e.body if isinstance(e.body, dict) else {}
            e.message = (body.get("error") or {}).get("message") or e.message  # just the API's own words
        if isinstance(e, anthropic.AuthenticationError):
            if self.p.sign_in:
                raise ProviderError(f"Claude turned down your sign-in. Sign in again on your account page. ({e.message})") from None
            raise ProviderError(f"Claude didn't accept this key. Paste it again on your account page. ({e.message})") from None
        if isinstance(e, anthropic.PermissionDeniedError):
            raise ProviderError(f"This Claude key can't use {self.p.model}. ({e.message})") from None
        if isinstance(e, anthropic.NotFoundError):
            raise ProviderError(f"Claude doesn't offer {self.p.model}. Choose another model on your account page.") from None
        if isinstance(e, anthropic.RateLimitError):
            raise ProviderError(f"Claude says you've hit a rate or usage limit: {e.message}") from None
        if isinstance(e, anthropic.BadRequestError):
            if "too long" in e.message.lower() or "context" in e.message.lower():
                raise ProviderError(f"This source is too long for {self.p.model}. Choose a model that reads more text at once on your account page.") from None
            raise ProviderError(f"Claude couldn't take this request: {e.message}") from None
        if isinstance(e, anthropic.APIStatusError):
            raise ProviderError(f"Claude returned an error ({e.status_code}): {e.message}") from None
        if isinstance(e, anthropic.APITimeoutError):
            raise ProviderError("Claude took too long to reply.") from None
        if isinstance(e, anthropic.APIConnectionError):
            raise ProviderError("Couldn't reach Claude. Check your internet connection.") from None
        return False
