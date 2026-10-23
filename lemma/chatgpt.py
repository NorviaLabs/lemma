"""Building lessons with the learner's own ChatGPT Plus or Pro subscription.

This signs in the way the Codex CLI's device sign-in does: Lemma asks OpenAI for a one-time code, the learner
enters it on OpenAI's sign-in page, and Lemma, checking back meanwhile, swaps the result for tokens that it keeps
in ``~/.lemma/chatgpt-auth.json`` (readable only by the learner). Nothing listens on the learner's computer.
Requests go to the ChatGPT backend that Codex uses, and count against the learner's plan.

It is for one person using Lemma on their own computer, with their own subscription. A hosted
Lemma serving other people must not offer it: that is what OpenAI's "Sign in with ChatGPT"
program is for.
"""

from __future__ import annotations

import base64
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__, store
from .llm import Conversation, Provider, ProviderError, Reply, REQUEST_TIMEOUT

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"  # the Codex CLI's
AUTH = "https://auth.openai.com"
TOKEN_URL = AUTH + "/oauth/token"
DEVICE_CODE_URL = AUTH + "/api/accounts/deviceauth/usercode"
DEVICE_TOKEN_URL = AUTH + "/api/accounts/deviceauth/token"
VERIFY_URL = AUTH + "/codex/device"  # where the learner enters the code
DEVICE_REDIRECT_URI = AUTH + "/deviceauth/callback"
BACKEND = "https://chatgpt.com/backend-api/codex"
DEFAULT_MODEL = "gpt-6.1-sol"
SIGN_IN_WAIT = 15 * 60  # seconds a code lasts

_lock = threading.Lock()
_login: dict = {}  # the sign-in in progress: {"code", "url", "stop"}, or {"error": str} once it fails


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


def _save(tokens: dict, refresh: str = ""):
    access = tokens["access_token"]
    claims = _claims(tokens.get("id_token") or "") or _claims(access)
    auth = {
        "access": access,
        "refresh": tokens.get("refresh_token") or refresh,  # a refresh may keep the old refresh token
        "expires": time.time() + float(tokens.get("expires_in") or 3600),
        "account_id": (_claims(access).get("https://api.openai.com/auth") or {}).get("chatgpt_account_id", ""),
        "email": claims.get("email", ""),
    }
    store.write_private(_auth_file(), json.dumps(auth))


def sign_out():
    _cancel_sign_in()
    _auth_file().unlink(missing_ok=True)


def status() -> dict:
    auth = load()
    waiting = "stop" in _login
    return {"signed_in": bool(auth), "email": (auth or {}).get("email", ""), "error": _login.get("error", ""), "waiting": waiting,
            "code": _login.get("code", "") if waiting else "", "url": _login.get("url", "") if waiting else ""}


def _token_request(fields: dict) -> dict:
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(fields).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": f"Lemma/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise ProviderError(f"ChatGPT sign-in failed ({e.code}). Sign in again on your account page.") from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as e:
        raise ProviderError(f"Couldn't reach OpenAI to sign in ({e}).") from None
    if not tokens.get("access_token") or (fields["grant_type"] != "refresh_token" and not tokens.get("refresh_token")):
        raise ProviderError("OpenAI's sign-in reply was missing its tokens. Sign in again on your account page.")
    return tokens


def _device_request(url: str, body: dict) -> tuple[int, dict]:
    """(status, reply) for one of the device sign-in calls, which answer "not yet" with an error status."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": f"Lemma/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
        raise ProviderError(f"Couldn't reach OpenAI to sign in ({e}).") from None
    try:
        reply = json.loads(raw)
    except ValueError:
        reply = {}
    return status, reply if isinstance(reply, dict) else {}


def access_token() -> tuple[str, str]:
    """(access token, account id), refreshed first if it's about to expire."""
    with _lock:
        auth = load()
        if not auth:
            raise ProviderError("Sign in with your ChatGPT account on your account page to build lessons.")
        if auth["expires"] - time.time() < 120:
            _save(_token_request({"grant_type": "refresh_token", "refresh_token": auth["refresh"], "client_id": CLIENT_ID}), auth["refresh"])
            auth = load()
        return auth["access"], auth["account_id"]


# ---------------------------------------------------------------- signing in


def start_sign_in() -> dict:
    """Asks OpenAI for a code and checks back in the background until the learner has entered it.
    Returns the status, with the code and the page to enter it on."""
    got, reply = _device_request(DEVICE_CODE_URL, {"client_id": CLIENT_ID})
    if not 200 <= got < 300 or not reply.get("device_auth_id") or not reply.get("user_code"):
        raise ProviderError(f"OpenAI didn't start a sign-in ({got}). Try again in a moment.")
    try:
        interval = max(1.0, float(reply.get("interval") or 5))
    except ValueError:
        interval = 5.0
    _cancel_sign_in()
    stop = threading.Event()
    _login.clear()
    _login.update(code=reply["user_code"], url=VERIFY_URL, stop=stop)
    threading.Thread(target=_wait_for_code, args=(stop, reply["device_auth_id"], reply["user_code"], interval), daemon=True).start()
    return status()


def _wait_for_code(stop: threading.Event, device_id: str, code: str, interval: float):
    deadline = time.time() + SIGN_IN_WAIT
    error = "The sign-in code expired. Start again from your account page."
    while not stop.wait(interval):
        if time.time() > deadline:
            break
        try:
            status, reply = _device_request(DEVICE_TOKEN_URL, {"device_auth_id": device_id, "user_code": code})
        except ProviderError:
            continue  # a dropped connection: check again next time
        if status in (403, 404) or reply.get("error") == "authorization_pending":
            continue  # not entered yet
        if reply.get("error") == "slow_down":
            interval += 5
            continue
        if not 200 <= status < 300 or not reply.get("authorization_code"):
            error = f"ChatGPT sign-in failed ({status}). Start again from your account page."
            break
        try:
            _save(_token_request({"grant_type": "authorization_code", "code": reply["authorization_code"],
                                  "code_verifier": reply.get("code_verifier", ""), "redirect_uri": DEVICE_REDIRECT_URI, "client_id": CLIENT_ID}))
            error = ""
        except ProviderError as e:
            error = str(e)
        break
    else:
        return  # cancelled, by a new sign-in or signing out
    if _login.get("stop") is stop:
        _login.clear()
        if error:
            _login["error"] = error


def _cancel_sign_in():
    if stop := _login.pop("stop", None):
        stop.set()


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
            return False, "Sign in with your ChatGPT account on your account page to build lessons."
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
            return f"ChatGPT turned down your sign-in. Sign in again on your account page. ({msg or status})"
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
