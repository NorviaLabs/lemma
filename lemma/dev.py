"""Development mode: `lemma --dev`.

* A supervisor runs the real server in a child process and restarts it, on the same port,
  whenever a Python file in the package changes.
* The child streams changes to frontend files (static/, examples/) to the browser over
  Server-Sent Events. `static/dev-reload.js` swaps stylesheets in place and reloads the
  page for anything else, including after a server restart.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
CHILD_ENV = "LEMMA_DEV_CHILD"
POLL = 0.4

BOOT_ID = uuid.uuid4().hex  # changes on every server start, so the browser can tell it restarted


def snapshot(root: Path, suffixes: tuple[str, ...]) -> dict[str, float]:
    out = {}
    for p in root.rglob("*"):
        if p.suffix in suffixes and "__pycache__" not in p.parts and p.is_file():
            try:
                out[str(p)] = p.stat().st_mtime
            except OSError:
                pass
    return out


def changed(before: dict[str, float], after: dict[str, float]) -> list[str]:
    keys = set(before) | set(after)
    return sorted(k for k in keys if before.get(k) != after.get(k))


FRONTEND_SUFFIXES = (".js", ".css", ".html", ".json", ".txt", ".woff2")


def frontend_changes(keepalive: float = 15.0):
    """Yields lists of changed frontend files, relative to the package, forever.
    Yields an empty list after `keepalive` seconds without changes."""
    roots = [PACKAGE / "static", PACKAGE / "examples"]
    state = {}
    for r in roots:
        state.update(snapshot(r, FRONTEND_SUFFIXES))
    quiet = 0.0
    while True:
        time.sleep(POLL)
        quiet += POLL
        now = {}
        for r in roots:
            now.update(snapshot(r, FRONTEND_SUFFIXES))
        diff = changed(state, now)
        state = now
        if diff:
            quiet = 0.0
            yield [os.path.relpath(p, PACKAGE) for p in diff]
        elif quiet >= keepalive:
            quiet = 0.0
            yield []


# ---------------------------------------------------------------- supervisor


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


PORT_WAIT = 10  # seconds to wait for the port, while a Lemma that was just stopped lets it go


def wait_for_port(port: int, seconds: float) -> bool:
    """True once `port` can be bound on this computer, waiting up to `seconds`."""
    deadline = time.monotonic() + seconds
    while not _port_free(port):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def supervise(port: int, open_browser: bool):
    # Always this port, never the next free one: sign-in returns only to the registered address, and every restart
    # reuses it so the browser can reconnect.
    if not wait_for_port(port, PORT_WAIT):
        print(f"Port {port} is in use, so Lemma can't start in dev mode. Stop the Lemma (or other program) using it, or choose "
              f"another with --port (sign-in only works on the port its callback is registered for).", file=sys.stderr, flush=True)
        raise SystemExit(1)
    url = f"http://localhost:{port}/"
    env = dict(os.environ, **{CHILD_ENV: "1"})
    cmd = [sys.executable, "-m", "lemma", "--dev", "--no-browser", "--port", str(port)]
    print(f"Lemma (dev) at {url}: restarts on Python changes, live-reloads the frontend. Ctrl+C to stop.", flush=True)

    def start():
        for _ in range(50):  # the old process may still be releasing the port
            if _port_free(port):
                break
            time.sleep(0.1)
        return subprocess.Popen(cmd, env=env)

    child = start()
    if open_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    state = snapshot(PACKAGE, (".py",))
    try:
        while True:
            time.sleep(POLL)
            now = snapshot(PACKAGE, (".py",))
            diff = changed(state, now)
            state = now
            if diff:
                names = ", ".join(os.path.relpath(p, PACKAGE) for p in diff[:4])
                print(f"↻ {names} changed: restarting the server", flush=True)
                stop(child)
                child = start()
            elif child.poll() is not None:
                # Crashed (for example a syntax error). Wait for the next edit instead of looping.
                print("✗ The server stopped. Fix the error and save to restart.", flush=True)
                while not changed(state, snapshot(PACKAGE, (".py",))):
                    time.sleep(POLL)
                state = snapshot(PACKAGE, (".py",))
                print("↻ Change detected: starting the server again", flush=True)
                child = start()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stop(child)


def stop(child: subprocess.Popen):
    if child.poll() is None:
        child.terminate()  # the child stops its OpenCode server on SIGTERM
        try:
            child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def is_child() -> bool:
    return os.environ.get(CHILD_ENV) == "1"
