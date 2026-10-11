"""AI providers, run through command-line tools the learner already has installed.

* **OpenCode Go**, through the local OpenCode installation. Lemma starts its own private
  ``opencode serve`` process: bound to 127.0.0.1, protected by a random password, run with
  ``--pure`` (no plugins) in an empty working directory, and given a ``lemma`` agent that has
  no tools and denies every permission.
* **Codex**, through the local Codex CLI. Each turn is a one-off ``codex exec`` that is
  ephemeral (nothing saved to disk), ignores the user's Codex config and rules, runs in a
  read-only sandbox in an empty working directory with approvals set to never, and has the
  shell, code execution, web search, browser, computer use, apps, plugins, MCP, memories and
  image tools turned off.

In both cases the model can only read what Lemma sends and reply with text, and the tool
uses its own stored login, so Lemma never handles an API key.
"""

from __future__ import annotations

import atexit
import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PROVIDER_ID = "opencode-go"
DEFAULT_MODEL = "gpt-5.6-luna"
REQUEST_TIMEOUT = 1800  # a long concept can take many minutes

AGENT_CONFIG = {
    "agent": {
        "lemma": {
            "mode": "primary",
            "description": "Writes Lemma lessons. No tools.",
            "prompt": "You write lessons for Lemma. Follow the system instructions exactly and reply with text only.",
            "tools": {"*": False},
            "permission": {"*": "deny"},
        }
    },
    "share": "disabled",
    "autoupdate": False,
}


class ProviderError(Exception):
    pass


@dataclass
class Reply:
    text: str
    stop_reason: str  # "end_turn" | "max_tokens"


class Provider:
    """Interface. A conversation keeps the paper and earlier turns, so repairs can refer back."""

    binary: str | None = None

    def setup_state(self) -> dict:
        """{"installed": bool, "signed_in": bool}, for the first-run setup steps."""
        return {"installed": bool(self.binary), "signed_in": self.available()[0]}

    id = ""
    name = ""
    model = ""
    label = ""

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def conversation(self, system: str, document: str) -> "Conversation":
        raise NotImplementedError


class Conversation:
    def send(self, text: str, cancelled: threading.Event | None = None) -> Reply:
        raise NotImplementedError

    def close(self):
        pass


# ---------------------------------------------------------------- the local OpenCode server


def find_opencode(path: str | None = None) -> str | None:
    for cand in (path, os.environ.get("LEMMA_OPENCODE"), shutil.which("opencode"), "/opt/homebrew/bin/opencode", "/usr/local/bin/opencode", str(Path.home() / ".opencode/bin/opencode")):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def opencode_version(binary: str) -> str:
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15)
        return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _auth_file() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(base) / "opencode" / "auth.json"


def has_go_credentials() -> bool:
    """Whether OpenCode has OpenCode Go credentials. Reads only the provider names, never the secrets."""
    if os.environ.get("OPENCODE_API_KEY"):
        return True
    try:
        return PROVIDER_ID in json.loads(_auth_file().read_text())
    except (OSError, ValueError):
        return False


class OpenCodeServer:
    def __init__(self, binary: str, workdir: Path):
        self.binary = binary
        self.workdir = workdir
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.password = ""
        self.lock = threading.Lock()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def ensure(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return
            self.workdir.mkdir(parents=True, exist_ok=True)
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                self.port = s.getsockname()[1]
            self.password = secrets.token_urlsafe(24)
            env = dict(os.environ)
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(AGENT_CONFIG)
            env["OPENCODE_SERVER_PASSWORD"] = self.password
            env.pop("OPENCODE_SERVER_USERNAME", None)
            try:
                self.proc = subprocess.Popen(
                    [self.binary, "serve", "--pure", "--hostname", "127.0.0.1", "--port", str(self.port)],
                    cwd=self.workdir, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as e:
                raise ProviderError(f"Couldn't start OpenCode ({e}).") from None
            deadline = time.time() + 30
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    raise ProviderError("OpenCode exited while starting. Try running `opencode serve` in a terminal to see why.")
                try:
                    self.request("GET", "/agent", timeout=2, _starting=True)
                    return
                except (OSError, ProviderError):
                    time.sleep(0.3)
            self.stop()
            raise ProviderError("OpenCode didn't start within 30 seconds.")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def request(self, method: str, path: str, body=None, timeout: float = 60, _starting: bool = False):
        if not _starting:
            self.ensure()
        data = json.dumps(body).encode() if body is not None else None
        auth = base64.b64encode(f"opencode:{self.password}".encode()).decode()
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json", "Authorization": "Basic " + auth})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise ProviderError(f"OpenCode answered {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            if _starting:
                raise OSError(str(e.reason)) from None
            raise ProviderError(f"Couldn't reach the local OpenCode server ({e.reason}).") from None
        except (TimeoutError, socket.timeout):
            raise ProviderError("OpenCode took too long to reply.") from None
        return json.loads(raw) if raw.strip() else None


_server: OpenCodeServer | None = None
_server_lock = threading.Lock()


def server_for(binary: str) -> OpenCodeServer:
    global _server
    from . import store

    with _server_lock:
        if _server is None or _server.binary != binary:
            if _server:
                _server.stop()
            _server = OpenCodeServer(binary, store.home() / "opencode-workdir")
        return _server


def shutdown():
    if _server:
        _server.stop()


atexit.register(shutdown)


# ---------------------------------------------------------------- provider


class OpenCodeGoProvider(Provider):
    id = PROVIDER_ID
    name = "OpenCode Go"

    def __init__(self, model: str = DEFAULT_MODEL, opencode_path: str | None = None):
        self.model = model or DEFAULT_MODEL
        self.binary = find_opencode(opencode_path)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.model}) via your local OpenCode"

    def available(self) -> tuple[bool, str]:
        if not self.binary:
            return False, "OpenCode isn't installed or wasn't found. Install it from opencode.ai, or set its path in Settings."
        if not has_go_credentials():
            return False, "OpenCode has no OpenCode Go credentials. Run `opencode providers login` and choose OpenCode Go."
        return True, ""

    def setup_state(self) -> dict:
        return {"installed": bool(self.binary), "signed_in": bool(self.binary) and has_go_credentials()}

    def server(self) -> OpenCodeServer:
        ok, msg = self.available()
        if not ok:
            raise ProviderError(msg)
        return server_for(self.binary)

    def models(self) -> list[dict]:
        data = self.server().request("GET", "/config/providers")
        for p in data.get("providers", []):
            if p.get("id") == PROVIDER_ID:
                out = []
                for mid, m in p.get("models", {}).items():
                    if m.get("status", "active") not in ("active", "beta"):
                        continue
                    out.append({"id": mid, "name": m.get("name") or mid, "context": (m.get("limit") or {}).get("context", 0)})
                return sorted(out, key=lambda m: m["name"].lower())
        raise ProviderError("OpenCode doesn't list OpenCode Go. Run `opencode providers login` and choose OpenCode Go.")

    def conversation(self, system, document):
        return OpenCodeConversation(self, system, document)


class OpenCodeConversation(Conversation):
    def __init__(self, provider: OpenCodeGoProvider, system: str, document: str):
        self.p = provider
        self.system = system
        self.document = document
        self.session: str | None = None

    def send(self, text, cancelled=None):
        srv = self.p.server()
        parts = [{"type": "text", "text": text}]
        if self.session is None:
            self.session = srv.request("POST", "/session", {"title": "Lemma lesson"})["id"]
            parts.insert(0, {"type": "text", "text": self.document})
        body = {
            "agent": "lemma",
            "model": {"providerID": PROVIDER_ID, "modelID": self.p.model},
            "system": self.system,
            "tools": {"*": False},
            "parts": parts,
        }
        result: dict = {}

        def call():
            try:
                result["res"] = srv.request("POST", f"/session/{self.session}/message", body, timeout=REQUEST_TIMEOUT)
            except ProviderError as e:
                result["err"] = e

        t = threading.Thread(target=call, daemon=True)
        t.start()
        while t.is_alive():
            t.join(0.5)
            if cancelled is not None and cancelled.is_set():
                try:
                    srv.request("POST", f"/session/{self.session}/abort", {}, timeout=10)
                except ProviderError:
                    pass
                t.join(10)
                raise ProviderError("Cancelled.")
        if "err" in result:
            raise result["err"]
        res = result.get("res") or {}
        info = res.get("info") or {}
        err = info.get("error")
        if err:
            msg = (err.get("data") or {}).get("message") or err.get("name") or "unknown error"
            if "auth" in str(err.get("name", "")).lower():
                msg = "OpenCode Go rejected the credentials. Run `opencode providers login` again. (" + msg + ")"
            raise ProviderError(f"OpenCode Go returned an error: {msg}")
        reply = "".join(p.get("text", "") for p in res.get("parts", []) if p.get("type") == "text" and not p.get("synthetic"))
        finish = info.get("finish") or ""
        return Reply(text=reply, stop_reason="max_tokens" if finish in ("length", "max_tokens") else "end_turn")

    def close(self):
        # Don't leave the paper in OpenCode's session history.
        if self.session:
            try:
                self.p.server().request("DELETE", f"/session/{self.session}", timeout=10)
            except ProviderError:
                pass
            self.session = None


# ---------------------------------------------------------------- Codex

CODEX_ID = "codex"
CODEX_DEFAULT_MODEL = "gpt-6.1-sol"

# Codex features that give the model tools. All off: Lemma only wants text back.
CODEX_DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "code_mode_host", "multi_agent", "image_generation", "apps",
    "browser_use", "browser_use_external", "computer_use", "in_app_browser", "memories", "plugins",
    "remote_plugin", "skill_search", "tool_suggest", "view_image", "hooks", "sleep_tool", "goals",
)
CODEX_CONFIG = (
    'web_search="disabled"',
    'approval_policy="never"',
    "skills.include_instructions=false",
    "include_permissions_instructions=false",
    "include_environment_context=false",
    "include_collaboration_mode_instructions=false",
)


def find_codex(path: str | None = None) -> str | None:
    for cand in (path, os.environ.get("LEMMA_CODEX"), shutil.which("codex"), str(Path.home() / ".local/bin/codex"), "/opt/homebrew/bin/codex", "/usr/local/bin/codex"):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


_codex_login: dict[str, tuple[float, bool]] = {}


def codex_logged_in(binary: str) -> bool:
    """`codex login status`, cached for a minute."""
    cached = _codex_login.get(binary)
    if cached and time.time() - cached[0] < 60:
        return cached[1]
    try:
        out = subprocess.run([binary, "login", "status"], capture_output=True, text=True, timeout=20)
        ok = out.returncode == 0 and "logged in" in (out.stdout + out.stderr).lower() and "not logged in" not in (out.stdout + out.stderr).lower()
    except (OSError, subprocess.SubprocessError):
        ok = False
    _codex_login[binary] = (time.time(), ok)
    return ok


def _toml_string(text: str) -> str:
    # A JSON string literal is also a valid TOML basic string.
    return json.dumps(text)


class CodexProvider(Provider):
    id = CODEX_ID
    name = "Codex"

    def __init__(self, model: str = CODEX_DEFAULT_MODEL, codex_path: str | None = None):
        self.model = model or CODEX_DEFAULT_MODEL
        self.binary = find_codex(codex_path)
        self._context = 0

    @property
    def label(self) -> str:
        return f"{self.name} ({self.model}) via your local Codex"

    def available(self) -> tuple[bool, str]:
        if not self.binary:
            return False, "Codex isn't installed or wasn't found. Install the Codex CLI, or set its path in Settings."
        if not codex_logged_in(self.binary):
            return False, "Codex isn't signed in. Run `codex login`."
        return True, ""

    def setup_state(self) -> dict:
        return {"installed": bool(self.binary), "signed_in": bool(self.binary) and codex_logged_in(self.binary)}

    def models(self) -> list[dict]:
        ok, msg = self.available()
        if not ok:
            raise ProviderError(msg)
        try:
            out = subprocess.run([self.binary, "debug", "models"], capture_output=True, text=True, timeout=60)
            data = json.loads(out.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            raise ProviderError("Couldn't read the model list from Codex.") from None
        models = []
        for m in data.get("models", []):
            if m.get("visibility", "list") != "list" or not m.get("slug"):
                continue
            models.append({"id": m["slug"], "name": m.get("display_name") or m["slug"], "context": m.get("context_window") or 0})
        return models

    def context_window(self) -> int:
        if not self._context:
            try:
                self._context = next((m["context"] for m in self.models() if m["id"] == self.model), 0)
            except ProviderError:
                self._context = 0
        return self._context

    def conversation(self, system, document):
        return CodexConversation(self, system, document)


class CodexConversation(Conversation):
    """Codex runs are one-offs with nothing saved, so each repair re-sends the conversation so far."""

    def __init__(self, provider: CodexProvider, system: str, document: str):
        self.p = provider
        self.system = system
        self.document = document
        self.turns: list[tuple[str, str]] = []  # (lemma message, model reply)

    def _prompt(self, text: str) -> str:
        parts = [self.document, ""]
        for i, (asked, replied) in enumerate(self.turns):
            parts += [f"=== Message {i + 1} from Lemma ===", asked, "", f"=== Your reply {i + 1} ===", replied, ""]
        parts += [f"=== Message {len(self.turns) + 1} from Lemma ===" if self.turns else "=== Task ===", text]
        return "\n".join(parts)

    def send(self, text, cancelled=None):
        ok, msg = self.p.available()
        if not ok:
            raise ProviderError(msg)
        prompt = self._prompt(text)
        ctx = self.p.context_window()
        est = (len(prompt) + len(self.system)) // 3  # a cautious characters-per-token estimate
        if ctx and est > ctx * 0.85:
            raise ProviderError(f"This paper is too long for {self.p.model} (about {est // 1000}k tokens; the model takes {ctx // 1000}k). Choose a model with a larger context in Settings, or use OpenCode Go.")
        from . import store

        workdir = store.home() / "codex-workdir"
        workdir.mkdir(parents=True, exist_ok=True)
        args = [self.p.binary, "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
                "--sandbox", "read-only", "--color", "never", "-C", str(workdir), "-m", self.p.model]
        for f in CODEX_DISABLED_FEATURES:
            args += ["--disable", f]
        for c in CODEX_CONFIG:
            args += ["-c", c]
        args += ["-c", "developer_instructions=" + _toml_string(self.system), "-"]
        try:
            proc = subprocess.Popen(args, cwd=workdir, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        except OSError as e:
            raise ProviderError(f"Couldn't start Codex ({e}).") from None
        out: dict = {}

        def talk():
            try:
                out["stdout"], out["stderr"] = proc.communicate(prompt, timeout=REQUEST_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                out["timeout"] = True
            except Exception as e:  # broken pipe etc.
                out["error"] = e

        t = threading.Thread(target=talk, daemon=True)
        t.start()
        while t.is_alive():
            t.join(0.5)
            if cancelled is not None and cancelled.is_set():
                proc.kill()
                t.join(5)
                raise ProviderError("Cancelled.")
        if out.get("timeout"):
            raise ProviderError("Codex took too long to reply.")
        if "error" in out:
            raise ProviderError(f"Codex stopped unexpectedly ({out['error']}).")
        reply, failure = parse_codex_events(out.get("stdout", ""))
        if failure:
            raise ProviderError(f"Codex returned an error: {failure}")
        if proc.returncode != 0 and not reply:
            tail = (out.get("stderr") or "").strip().splitlines()[-1:] or ["no details"]
            raise ProviderError(f"Codex exited with an error: {tail[0][:300]}")
        self.turns.append((text, reply))
        return Reply(text=reply, stop_reason="end_turn")


def parse_codex_events(stdout: str) -> tuple[str, str]:
    """Returns (last agent message, failure message) from `codex exec --json` output."""
    reply, failure = "", ""
    for line in stdout.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        kind = e.get("type")
        if kind == "item.completed" and (e.get("item") or {}).get("type") == "agent_message":
            reply = e["item"].get("text", "")
        elif kind == "turn.failed":
            failure = ((e.get("error") or {}).get("message")) or "the turn failed"
        elif kind == "error":
            failure = e.get("message") or "unknown error"
    return reply, failure


# ---------------------------------------------------------------- choosing a provider

PROVIDERS = {PROVIDER_ID: "OpenCode Go", CODEX_ID: "Codex"}


def make_provider(settings: dict, provider_id: str | None = None) -> Provider:
    pid = provider_id or settings.get("provider") or PROVIDER_ID
    models = settings.get("models") or {}
    paths = settings.get("paths") or {}
    if pid == CODEX_ID:
        return CodexProvider(model=models.get(CODEX_ID) or CODEX_DEFAULT_MODEL, codex_path=paths.get(CODEX_ID))
    # Older settings files kept the OpenCode model and path at the top level.
    return OpenCodeGoProvider(model=models.get(PROVIDER_ID) or settings.get("model") or DEFAULT_MODEL,
                              opencode_path=paths.get(PROVIDER_ID) or settings.get("opencode_path"))


def forget_cached_logins():
    """Forget cached sign-in checks, so the setup screen sees a login that just happened."""
    _codex_login.clear()


def find_binary(provider_id: str, path: str | None) -> str | None:
    return find_codex(path) if provider_id == CODEX_ID else find_opencode(path)
