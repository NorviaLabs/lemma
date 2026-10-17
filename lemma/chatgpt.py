"""Building lessons with the learner's own ChatGPT Plus or Pro subscription.

This signs in the way the Codex CLI and personal coding harnesses do: OpenAI's sign-in page
sends the learner back to ``http://localhost:1455/auth/callback``, and Lemma swaps the code
for tokens that it keeps in ``~/.lemma/chatgpt-auth.json`` (readable only by the learner).
Requests go to the ChatGPT backend that Codex uses, and count against the learner's plan.

It is for one person using Lemma on their own computer, with their own subscription. A hosted
Lemma serving other people must not offer it: that is what OpenAI's "Sign in with ChatGPT"
program is for.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from . import __version__, store
from .llm import Conversation, Provider, ProviderError, Reply, REQUEST_TIMEOUT

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"  # the Codex CLI's
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CALLBACK_PORT = 1455  # the only redirect the sign-in page accepts for this client
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/auth/callback"
SCOPE = "openid profile email offline_access"
BACKEND = "https://chatgpt.com/backend-api/codex"
DEFAULT_MODEL = "gpt-6.1-sol"
SIGN_IN_WAIT = 600  # seconds the callback listener waits for the learner

_lock = threading.Lock()
_login: dict = {}  # the sign-in in progress: {"error": str} once it fails


def _auth_file():
    return store.home() / "chatgpt-auth.json"


def _claims(jwt: str) -> dict:
    try:
        payload = jwt.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


def load() -> dict | None:
    try:
        return json.loads(_auth_file().read_text())
    except (OSError, ValueError):
        return None


def _save(tokens: dict):
    access = tokens["access_token"]
    claims = _claims(tokens.get("id_token") or "") or _claims(access)
    auth = {
        "access": access,
        "refresh": tokens["refresh_token"],
        "expires": time.time() + float(tokens.get("expires_in") or 3600),
        "account_id": (_claims(access).get("https://api.openai.com/auth") or {}).get("chatgpt_account_id", ""),
        "email": claims.get("email", ""),
    }
    store.write_private(_auth_file(), json.dumps(auth))


def sign_out():
    _auth_file().unlink(missing_ok=True)


def status() -> dict:
    auth = load()
    return {"signed_in": bool(auth), "email": (auth or {}).get("email", ""), "error": _login.get("error", ""), "waiting": bool(_login.get("server"))}


def _token_request(fields: dict) -> dict:
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(fields).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": f"Lemma/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise ProviderError(f"ChatGPT sign-in failed ({e.code}). Sign in again in Settings.") from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as e:
        raise ProviderError(f"Couldn't reach OpenAI to sign in ({e}).") from None
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise ProviderError("OpenAI's sign-in reply was missing its tokens. Sign in again in Settings.")
    return tokens


def access_token() -> tuple[str, str]:
    """(access token, account id), refreshed first if it's about to expire."""
    with _lock:
        auth = load()
        if not auth:
            raise ProviderError("Sign in with your ChatGPT account in Settings to build lessons.")
        if auth["expires"] - time.time() < 120:
            _save(_token_request({"grant_type": "refresh_token", "refresh_token": auth["refresh"], "client_id": CLIENT_ID}))
            auth = load()
        return auth["access"], auth["account_id"]


# ---------------------------------------------------------------- signing in


def start_sign_in() -> str:
    """Listens for OpenAI's redirect and returns the sign-in page to open."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path != "/auth/callback":
                return self._page(404, "Not found.")
            if q.get("state") != state:
                return self._page(400, "This sign-in link has expired. Start again from Lemma's Settings.")
            if q.get("error"):
                _login["error"] = q.get("error_description") or q["error"]
                self._page(400, "Sign-in was cancelled. You can close this tab and try again from Lemma.")
            else:
                try:
                    _save(_token_request({"grant_type": "authorization_code", "code": q.get("code", ""), "redirect_uri": REDIRECT_URI,
                                          "client_id": CLIENT_ID, "code_verifier": verifier}))
                    self._page(200, "Signed in. You can close this tab and go back to Lemma.")
                except ProviderError as e:
                    _login["error"] = str(e)
                    self._page(400, str(e))
            threading.Thread(target=_stop_listening, daemon=True).start()

        def _page(self, status, text):
            body = f"<!doctype html><meta charset=utf-8><title>Lemma</title><p style='font:18px system-ui;margin:3em'>{text}</p>".encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    _stop_listening()
    try:
        server = HTTPServer(("127.0.0.1", CALLBACK_PORT), Callback)
    except OSError:
        raise ProviderError(f"Port {CALLBACK_PORT} is busy, perhaps with a Codex sign-in. Finish or close it, then try again.") from None
    _login.clear()
    _login["server"] = server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    timer = threading.Timer(SIGN_IN_WAIT, _stop_listening, args=(server,))
    timer.daemon = True  # don't hold Lemma open when it's stopped
    timer.start()
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI, "scope": SCOPE,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "id_token_add_organizations": "true", "codex_cli_simplified_flow": "true", "originator": "codex_cli_rs",
    })


def _stop_listening(only=None):
    server = _login.get("server")
    if server and (only is None or only is server):
        _login.pop("server", None)
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------- provider


class ChatGPTProvider(Provider):
    id = "chatgpt"
    name = "ChatGPT"

    def __init__(self, model: str = ""):
        self.model = model or DEFAULT_MODEL

    @property
    def label(self) -> str:
        return f"{self.name} ({self.model}) with your subscription"

    def available(self) -> tuple[bool, str]:
        if not load():
            return False, "Sign in with your ChatGPT account in Settings to build lessons."
        return True, ""

    def request(self, method: str, path: str, body=None, timeout: float = 60, on_line=None):
        """Returns the raw response body, passing each line to ``on_line`` as it arrives when given."""
        token, account = access_token()
        headers = {"Authorization": "Bearer " + token, "chatgpt-account-id": account, "OpenAI-Beta": "responses=experimental",
                   "originator": "codex_cli_rs", "User-Agent": f"Lemma/{__version__}", "Content-Type": "application/json"}
        if body is not None:
            headers["Accept"] = "text/event-stream"
        req = urllib.request.Request(BACKEND + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if not on_line:
                    return resp.read().decode("utf-8", "replace")
                lines = []
                for raw in resp:
                    lines.append(raw.decode("utf-8", "replace").rstrip("\r\n"))
                    on_line(lines[-1])
                return "\n".join(lines)
        except urllib.error.HTTPError as e:
            raise ProviderError(self._explain(e.code, e.read().decode("utf-8", "replace"))) from None
        except urllib.error.URLError as e:
            raise ProviderError(f"Couldn't reach ChatGPT ({e.reason}).") from None
        except (TimeoutError, socket.timeout):
            raise ProviderError("ChatGPT took too long to reply.") from None

    def _explain(self, status: int, raw: str) -> str:
        try:
            data = json.loads(raw)
            err = data.get("error") or data.get("detail") or data
            msg = err.get("message") if isinstance(err, dict) else str(err)
        except (ValueError, AttributeError):
            msg = raw[:300]
        if status in (401, 403):
            return f"ChatGPT turned down your sign-in. Sign in again in Settings. ({msg or status})"
        if status == 429:
            return f"You've reached your ChatGPT plan's usage limit: {msg or 'try again later'}"
        return f"ChatGPT returned an error ({status}): {msg or 'no details'}"

    def models(self) -> list[dict]:
        try:
            data = json.loads(self.request("GET", "/models?client_version=1.0.0"))
        except (ProviderError, ValueError):
            return [{"id": self.model, "name": self.model, "context": 0}]  # the list is a convenience; the default still works
        out = [{"id": m["slug"], "name": m.get("display_name") or m["slug"], "context": m.get("context_window") or 0}
               for m in data.get("models", []) if m.get("slug") and m.get("visibility", "list") == "list"]
        return out or [{"id": self.model, "name": self.model, "context": 0}]

    def conversation(self, system, document):
        return ChatGPTConversation(self, system, document)


class ChatGPTConversation(Conversation):
    """The backend keeps nothing (store=false), so each turn re-sends the paper and the conversation so far."""

    def __init__(self, provider: ChatGPTProvider, system: str, document: str):
        self.p = provider
        self.system = system
        self.input = [{"role": "user", "content": [{"type": "input_text", "text": document}]}]

    def send(self, text, cancelled=None, on_progress=None):
        turn = self.input + [{"role": "user", "content": [{"type": "input_text", "text": text}]}]
        body = {"model": self.p.model, "instructions": self.system, "input": turn, "store": False, "stream": True}
        result: dict = {}
        written = [0]

        def line(raw):  # report progress as the stream arrives; the whole stream is parsed at the end
            if not on_progress or not raw.startswith("data:"):
                return
            try:
                event = json.loads(raw[5:])
            except ValueError:
                return
            kind = event.get("type") or ""
            if kind == "response.output_text.delta":
                written[0] += len(event.get("delta") or "")
                on_progress("writing", written[0])
            elif kind.startswith("response.reasoning") and kind.endswith(".delta"):
                on_progress("thinking", written[0])

        def call():
            try:
                result["res"] = self.p.request("POST", "/responses", body, timeout=REQUEST_TIMEOUT, on_line=line)
            except ProviderError as e:
                result["err"] = e

        t = threading.Thread(target=call, daemon=True)
        t.start()
        while t.is_alive():
            t.join(0.5)
            if cancelled is not None and cancelled.is_set():
                raise ProviderError("Cancelled.")  # the request finishes in the background and is dropped
        if "err" in result:
            raise result["err"]
        reply, stop = parse_stream(result.get("res", ""))
        self.input = turn + [{"role": "assistant", "content": [{"type": "output_text", "text": reply}]}]
        return Reply(text=reply, stop_reason=stop)


def parse_stream(sse: str) -> tuple[str, str]:
    """(reply text, stop reason) from a Responses API event stream."""
    for line in sse.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:])
        except ValueError:
            continue
        kind = event.get("type")
        if kind in ("response.failed", "error"):
            err = (event.get("response") or {}).get("error") or event.get("error") or event
            raise ProviderError(f"ChatGPT returned an error: {err.get('message') or 'unknown error'}")
        if kind in ("response.completed", "response.done", "response.incomplete"):
            response = event.get("response") or {}
            text = "".join(c.get("text", "") for item in response.get("output", []) if item.get("type") == "message"
                           for c in item.get("content", []) if c.get("type") == "output_text")
            cut = (response.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
            return text, "max_tokens" if cut else "end_turn"
    raise ProviderError("ChatGPT's reply ended before it finished.")
