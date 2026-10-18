"""Building lessons with the learner's own Claude Pro or Max subscription, through Claude Code.

Lemma doesn't sign in to Claude itself: Anthropic allows a subscription only in its own apps,
with sign-in through its own flow. Instead it runs the learner's installed, unmodified Claude
Code (``claude``), signed in with ``claude auth login``, in headless mode. Each conversation is
one ``claude -p`` process with every tool, setting, plugin and MCP server turned off, so the
model only reads what Lemma sends and replies with text. Turns go in and replies come out as
JSON lines, and nothing is saved to Claude Code's session history.

It is for one person using Lemma on their own computer. A hosted Lemma doesn't offer it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time

from .llm import Conversation, Provider, ProviderError, Reply

CLAUDE = "claude"  # the command; tests point it at a stand-in
DEFAULT_MODEL = "claude-opus-5-5"
MODELS = [("claude-opus-5-5", "Claude Opus 5.5"), ("claude-fable-5-1", "Claude Fable 5.1"),
          ("claude-sonnet-5-5", "Claude Sonnet 5.5"), ("claude-haiku-5-5", "Claude Haiku 5.5")]
SIGN_IN = "In a terminal, run `claude auth login` and sign in with your Claude account, then check again here."
STATUS_FOR = 20  # seconds a sign-in check is reused, since each one starts Claude Code

_checked: dict = {}  # {"at": time, "status": dict}
_lock = threading.Lock()


def _env() -> dict:
    # Without these, Claude Code would bill an API key instead of the plan, or think it runs inside another session.
    return {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE")}


def status(fresh: bool = False) -> dict:
    """Whether Claude Code is installed and signed in with a Claude subscription."""
    with _lock:
        if not fresh and _checked and time.time() - _checked["at"] < STATUS_FOR:
            return _checked["status"]
        out = {"installed": bool(shutil.which(CLAUDE)), "signed_in": False, "email": "", "plan": "", "error": ""}
        if not out["installed"]:
            out["error"] = "Claude Code isn't installed. Install it from https://claude.com/claude-code, then sign in."
        else:
            try:
                run = subprocess.run([CLAUDE, "auth", "status", "--json"], capture_output=True, text=True, timeout=30, env=_env())
                info = json.loads(run.stdout or "{}")
            except (OSError, subprocess.TimeoutExpired, ValueError):
                info = {}
            if info.get("loggedIn") and info.get("authMethod") == "claude.ai":
                out.update(signed_in=True, email=info.get("email") or "", plan=info.get("subscriptionType") or "")
            elif info.get("loggedIn"):
                out["error"] = "Claude Code is signed in with an API key, not a Claude subscription. " + SIGN_IN
            else:
                out["error"] = "Claude Code isn't signed in. " + SIGN_IN
        _checked.update(at=time.time(), status=out)
        return out


class ClaudeCodeProvider(Provider):
    id = "claude-code"
    name = "Claude subscription"

    def __init__(self, model: str = ""):
        self.model = model or DEFAULT_MODEL

    @property
    def label(self) -> str:
        return f"Claude ({self.model}) with your subscription, through Claude Code"

    def available(self) -> tuple[bool, str]:
        st = status()
        return (True, "") if st["signed_in"] else (False, st["error"])

    def models(self) -> list[dict]:
        ok, msg = self.available()
        if not ok:
            raise ProviderError(msg)
        return [{"id": m, "name": n, "context": 0} for m, n in MODELS]

    def conversation(self, system, document):
        ok, msg = self.available()
        if not ok:
            raise ProviderError(msg)
        return ClaudeCodeConversation(self, system, document)


class ClaudeCodeConversation(Conversation):
    """One Claude Code process holds the conversation, so a repair needs only its own message."""

    def __init__(self, provider: ClaudeCodeProvider, system: str, document: str):
        self.p = provider
        self.document = document
        self.proc: subprocess.Popen | None = None
        self.dir = tempfile.mkdtemp(prefix="lemma-claude-")  # an empty folder, so no project instructions are read
        self.args = [CLAUDE, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                     "--include-partial-messages", "--tools", "", "--strict-mcp-config", "--safe-mode", "--disable-slash-commands",
                     "--no-session-persistence", "--model", provider.model, "--effort", "high", "--system-prompt", system]

    def send(self, text, cancelled=None, on_progress=None):
        first = self.proc is None
        if first:
            try:
                self.proc = subprocess.Popen(self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                             text=True, encoding="utf-8", cwd=self.dir, env=_env())
            except OSError as e:
                raise ProviderError(f"Couldn't start Claude Code ({e}).") from None
        content = [{"type": "text", "text": self.document}, {"type": "text", "text": text}] if first else text
        result: dict = {}
        written = [0]

        def read():
            try:
                self.proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n")
                self.proc.stdin.flush()
                for line in self.proc.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "result":
                        result["event"] = event
                        return
                    delta = (event.get("event") or {}).get("delta") or {} if event.get("type") == "stream_event" else {}
                    if on_progress and delta.get("type") == "text_delta":
                        written[0] += len(delta.get("text") or "")
                        on_progress("writing", written[0])
                    elif on_progress and delta.get("type") == "thinking_delta":
                        on_progress("thinking", written[0])
            except (OSError, ValueError):
                pass  # the process ended; reported below

        t = threading.Thread(target=read, daemon=True)
        t.start()
        while t.is_alive():
            t.join(0.5)
            if cancelled is not None and cancelled.is_set():
                self.close()
                raise ProviderError("Cancelled.")
        event = result.get("event")
        if event is None:
            self.close()
            raise ProviderError("Claude Code stopped before it replied. Check that `claude` works in a terminal.")
        if event.get("is_error") or event.get("subtype") != "success":
            raise ProviderError(explain(str(event.get("result") or event.get("subtype") or "unknown error"), self.p.model))
        if event.get("stop_reason") == "refusal":
            raise ProviderError("Claude declined to write this part of the lesson. Try another model in Settings.")
        return Reply(text=event.get("result") or "", stop_reason="max_tokens" if event.get("stop_reason") == "max_tokens" else "end_turn")

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        shutil.rmtree(self.dir, ignore_errors=True)


def explain(msg: str, model: str) -> str:
    low = msg.lower()
    if "login" in low or "log in" in low or "auth" in low:
        _checked.clear()
        return f"Claude Code isn't signed in. {SIGN_IN} ({msg})"
    if "limit" in low:
        return f"You've reached your Claude plan's usage limit: {msg}"
    if "too long" in low or "context" in low:
        return f"This paper is too long for {model}. Choose another model in Settings."
    return f"Claude Code returned an error: {msg}"
