"""AI providers, called over HTTP with the learner's own credential.

Lemma runs on a server, so it can't lean on tools installed on the learner's computer. Each
provider is an OpenAI-compatible chat completions API; the learner supplies a key for it, the
browser keeps that key and sends it with each request, and the server only holds it in memory
for as long as a request or build needs it. The model gets no tools: it reads what Lemma sends
and replies with text.

* **OpenCode Go**, at ``https://opencode.ai/zen/go/v1``, with an OpenCode Go key.
* **OpenAI**, at ``https://api.openai.com/v1``, with an OpenAI API key.
* **Claude**, through the Anthropic API with a Claude API key (see ``claude.py``).
* **ChatGPT**, with the learner's ChatGPT subscription instead of a key (see ``chatgpt.py``).
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__

REQUEST_TIMEOUT = 1800  # a long concept can take many minutes


class ProviderError(Exception):
    pass


@dataclass
class Reply:
    text: str
    stop_reason: str  # "end_turn" | "max_tokens"


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    name: str
    base: str
    default_model: str
    key_url: str  # where a learner gets a key; empty for a provider they sign in to


PROVIDERS = {
    p.id: p
    for p in (
        ProviderInfo("opencode-go", "OpenCode Go", "https://opencode.ai/zen/go/v1", "gpt-5.6-luna", "https://opencode.ai/auth"),
        ProviderInfo("openai", "OpenAI", "https://api.openai.com/v1", "gpt-6.1-sol", "https://platform.openai.com/api-keys"),
        ProviderInfo("claude", "Claude", "https://api.anthropic.com", "claude-opus-5-5", "https://platform.claude.com/settings/keys"),
        # Signs in with a ChatGPT subscription instead of a key; see chatgpt.py. Only for Lemma on the learner's own computer.
        ProviderInfo("chatgpt", "ChatGPT", "https://chatgpt.com/backend-api/codex", "gpt-6.1-sol", ""),
    )
}
DEFAULT_PROVIDER = "opencode-go"

# OpenAI lists every model it has; these can't write a lesson.
NOT_CHAT = ("embedding", "tts", "whisper", "dall-e", "image", "audio", "realtime", "moderation", "transcribe", "search", "sora")


class Provider:
    """Interface. A conversation keeps the paper and earlier turns, so repairs can refer back."""

    id = ""
    name = ""
    model = ""
    label = ""

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def conversation(self, system: str, document: str) -> "Conversation":
        raise NotImplementedError


class Conversation:
    def send(self, text: str, cancelled: threading.Event | None = None, on_progress=None) -> Reply:
        """``on_progress(phase, chars)`` is called while the reply streams in: ``phase`` is "thinking" or
        "writing", and ``chars`` how much of the reply has been written so far."""
        raise NotImplementedError

    def close(self):
        pass


class HTTPProvider(Provider):
    def __init__(self, info: ProviderInfo, key: str, model: str = ""):
        self.info = info
        self.id, self.name = info.id, info.name
        self.key = key.strip()
        self.model = model or info.default_model

    @property
    def label(self) -> str:
        return f"{self.name} ({self.model})"

    def available(self) -> tuple[bool, str]:
        if not self.key:
            return False, f"Add your {self.name} key in Settings to build lessons."
        return True, ""

    def request(self, method: str, path: str, body=None, timeout: float = 60, on_line=None):
        """The parsed JSON reply; or, for an event stream when ``on_line`` is given, None after passing it each line."""
        ok, msg = self.available()
        if not ok:
            raise ProviderError(msg)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.info.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key,
                                              "User-Agent": f"Lemma/{__version__}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if on_line and resp.headers.get_content_type() == "text/event-stream":
                    for raw in resp:
                        on_line(raw.decode("utf-8", "replace").rstrip("\r\n"))
                    return None
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            raise ProviderError(self._explain(e.code, e.read().decode("utf-8", "replace"))) from None
        except urllib.error.URLError as e:
            raise ProviderError(f"Couldn't reach {self.name} ({e.reason}).") from None
        except (TimeoutError, socket.timeout):
            raise ProviderError(f"{self.name} took too long to reply.") from None
        except ValueError:
            raise ProviderError(f"{self.name} sent a reply Lemma couldn't read.") from None

    def _explain(self, status: int, raw: str) -> str:
        try:
            err = json.loads(raw).get("error") or {}
            msg = err.get("message") if isinstance(err, dict) else str(err)
            code = err.get("code", "") if isinstance(err, dict) else ""
        except (ValueError, AttributeError):
            msg, code = raw[:300], ""
        if status in (401, 403):
            return f"{self.name} rejected the key. Check it in Settings. ({msg or status})"
        if code == "context_length_exceeded":
            return f"This paper is too long for {self.model}. Choose a model with a larger context in Settings."
        if status == 429:
            return f"{self.name} says you've hit a rate or usage limit: {msg or 'try again later'}"
        return f"{self.name} returned an error ({status}): {msg or 'no details'}"

    def models(self) -> list[dict]:
        data = self.request("GET", "/models") or {}
        out = []
        for m in data.get("data", []):
            mid = m.get("id")
            if not mid or (self.id == "openai" and any(w in mid for w in NOT_CHAT)):
                continue
            out.append({"id": mid, "name": m.get("name") or mid, "context": m.get("context_length") or m.get("context_window") or 0})
        return sorted(out, key=lambda m: m["name"].lower())

    def conversation(self, system, document):
        return HTTPConversation(self, system, document)


class HTTPConversation(Conversation):
    """The APIs keep no state, so each turn re-sends the paper and the conversation so far."""

    def __init__(self, provider: HTTPProvider, system: str, document: str):
        self.p = provider
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": document}]

    def send(self, text, cancelled=None, on_progress=None):
        messages = self.messages + [{"role": "user", "content": text}]
        result: dict = {}
        parts: list[str] = []
        streamed = {"finish": None, "error": "", "written": 0}

        def line(raw):  # one line of the reply's event stream
            if not raw.startswith("data:") or raw[5:].strip() == "[DONE]":
                return
            try:
                event = json.loads(raw[5:])
            except ValueError:
                return
            if event.get("error"):
                err = event["error"]
                streamed["error"] = err.get("message") if isinstance(err, dict) else str(err)
                return
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    parts.append(delta["content"])
                    streamed["written"] += len(delta["content"])
                    if on_progress:
                        on_progress("writing", streamed["written"])
                elif (delta.get("reasoning_content") or delta.get("reasoning")) and on_progress:
                    on_progress("thinking", streamed["written"])
                streamed["finish"] = choice.get("finish_reason") or streamed["finish"]

        def call():
            try:
                result["res"] = self.p.request("POST", "/chat/completions", {"model": self.p.model, "messages": messages, "stream": True},
                                               timeout=REQUEST_TIMEOUT, on_line=line)
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
        if streamed["error"]:
            raise ProviderError(f"{self.p.name} returned an error: {streamed['error']}")
        if result.get("res") is None:  # streamed
            reply, finish = "".join(parts), streamed["finish"]
        else:  # a provider that answered in one piece despite the request to stream
            choice = (result["res"].get("choices") or [{}])[0]
            reply, finish = (choice.get("message") or {}).get("content") or "", choice.get("finish_reason")
        self.messages = messages + [{"role": "assistant", "content": reply}]
        return Reply(text=reply, stop_reason="max_tokens" if finish == "length" else "end_turn")


def make_provider(provider_id: str | None, key: str = "", model: str = "") -> Provider:
    info = PROVIDERS.get(provider_id or DEFAULT_PROVIDER)
    if info is None:
        raise ProviderError("Unknown AI provider.")
    if info.id == "claude":
        from .claude import ClaudeProvider

        return ClaudeProvider(key, model)
    if info.id == "chatgpt":
        from .chatgpt import ChatGPTProvider

        return ChatGPTProvider(model)
    return HTTPProvider(info, key, model)
