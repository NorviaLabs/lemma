"""Starting Lemma from the command line, and the development supervisor behind `lemma --dev`.

No browser is opened and no public address is bound: the browser call is replaced, and the hosted starts
either fail before listening or run with the listening server replaced.
"""

from __future__ import annotations

import contextlib
import http.client
import io
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_lemma  # noqa: F401  a temporary LEMMA_HOME and the Jev stand-in
from lemma import __main__ as cli
from lemma import __version__, dev, metrics, server

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(*args, env=None):
    full = dict(os.environ, LEMMA_HOME=tempfile.mkdtemp(prefix="lemma-cli-"), PYTHONUNBUFFERED="1")
    full.pop(dev.CHILD_ENV, None)
    full.update(env or {})
    return subprocess.Popen([sys.executable, "-m", "lemma", *args], cwd=ROOT, env=full,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


class CommandLine(unittest.TestCase):
    def test_lemma_serves_this_computer_until_it_is_stopped(self):
        port = free_port()
        proc = start("--no-browser", "--port", str(port), env={"TYPESAFE_API_KEY": ""})
        try:
            first = proc.stdout.readline()
            self.assertEqual(first.strip(), f"Lemma is running at http://localhost:{port}/  (only reachable from this computer; press Ctrl+C to stop)")
            self.assertTrue(proc.stdout.readline().startswith("Search and lesson building are off: "))
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", "/api/status", headers={"Host": f"localhost:{port}"})
            self.assertEqual(c.getresponse().status, 200)
            c.close()
            proc.send_signal(signal.SIGTERM)  # `kill` stops it like Ctrl+C
            out, err = proc.communicate(timeout=10)
        finally:
            proc.kill() if proc.poll() is None else None
        self.assertEqual((proc.returncode, out.strip()), (0, "Stopped."))

    def test_a_hosted_lemma_needs_its_domain_names(self):
        proc = start("--host", "0.0.0.0", "--port", str(free_port()))
        out, err = proc.communicate(timeout=20)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("A hosted Lemma needs --allowed-hosts", err)

    def test_version(self):
        proc = start("--version")
        out, _ = proc.communicate(timeout=20)
        self.assertEqual((proc.returncode, out.strip()), (0, f"Lemma {__version__}"))


class FakeHTTPD:
    def __init__(self, port):
        self.server_address = ("127.0.0.1", port)
        self.closed = False

    def serve_forever(self):
        raise KeyboardInterrupt  # stopped as soon as it starts

    def server_close(self):
        self.closed = True


class InProcess(unittest.TestCase):
    """main() with the listening part replaced, to see what it tells people and what it opens."""

    def setUp(self):
        self.was = (server.DEV, signal.getsignal(signal.SIGTERM))

    def tearDown(self):
        server.DEV, sigterm = self.was
        signal.signal(signal.SIGTERM, sigterm)
        test_lemma.reset_server()

    def run_main(self, *argv, hosted=False):
        httpd = FakeHTTPD(8999)
        opened = threading.Event()
        urls = []

        def fake_make_server(port, exact, host, allowed_hosts):
            server.ON_THIS_COMPUTER = not hosted
            self.made = (port, exact, host, allowed_hosts)
            return httpd

        out = io.StringIO()
        with patch.object(cli, "make_server", fake_make_server), patch.object(cli.webbrowser, "open", lambda url: (urls.append(url), opened.set())), \
                patch.dict(os.environ, {dev.CHILD_ENV: ""}), contextlib.redirect_stdout(out):
            cli.main(list(argv))
            if "--no-browser" not in argv and not hosted:
                self.assertTrue(opened.wait(5), "the browser was not opened")
        self.assertTrue(httpd.closed)
        return out.getvalue(), urls

    def test_a_local_start_opens_the_browser_at_its_address(self):
        out, urls = self.run_main("--port", "8999")
        self.assertEqual(urls, ["http://localhost:8999/"])
        self.assertIn("Lemma is running at http://localhost:8999/", out)
        self.assertTrue(out.rstrip().endswith("Stopped."))

    def test_a_hosted_start_names_its_domains_and_opens_no_browser(self):
        out, urls = self.run_main("--host", "0.0.0.0", "--allowed-hosts", "tools.example.com, ,www.example.com", hosted=True)
        self.assertEqual(self.made, (8765, False, "0.0.0.0", ("tools.example.com", "www.example.com")))
        self.assertIn("Lemma is hosted on 0.0.0.0:8999 for tools.example.com, www.example.com", out)
        self.assertEqual(urls, [])

    def test_dev_mode_hands_over_to_the_supervisor(self):
        with patch.object(cli.dev, "supervise", return_value="supervised") as supervise, patch.dict(os.environ, {dev.CHILD_ENV: ""}):
            self.assertEqual(cli.main(["--dev", "--no-browser", "--port", "9100"]), "supervised")
        supervise.assert_called_once_with(9100, open_browser=False)

    def test_the_dev_child_serves_on_its_exact_port_quietly(self):
        with patch.dict(os.environ, {dev.CHILD_ENV: "1"}):
            httpd = FakeHTTPD(9100)
            out = io.StringIO()
            with patch.object(cli, "make_server", side_effect=lambda port, exact, host, allowed_hosts: (setattr(self, "exact", exact), httpd)[1]), \
                    contextlib.redirect_stdout(out):
                cli.main(["--dev", "--no-browser", "--port", "9100"])
        self.assertTrue(self.exact)
        self.assertTrue(server.DEV)
        self.assertNotIn("Lemma is running", out.getvalue())
        self.assertNotIn("Stopped.", out.getvalue())


class FakeChild:
    """A stand-in for the dev server process: it runs until told to stop, or until the test makes it crash."""

    started: list = []

    def __init__(self, cmd, env):
        self.cmd, self.env, self.returncode = cmd, env, None
        self.signals = []
        FakeChild.started.append(self)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.signals.append("TERM")
        self.returncode = -15

    def kill(self):
        self.signals.append("KILL")
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class Supervisor(unittest.TestCase):
    def setUp(self):
        self.pkg = Path(tempfile.mkdtemp(prefix="lemma-pkg-"))
        (self.pkg / "server.py").write_text("x = 1\n")
        FakeChild.started = []

    def touch(self, name):
        path = self.pkg / name
        path.write_text(path.read_text() + "# edit\n" if path.exists() else "")
        later = time.time() + len(FakeChild.started) + 10
        os.utime(path, (later, later))

    def supervise(self, script):
        """Runs dev.supervise, doing script[i]() at its i-th poll, then Ctrl+C."""
        ticks = iter(script)

        def tick(_seconds):
            step = next(ticks, None)
            if step is None:
                raise KeyboardInterrupt
            step()

        out = io.StringIO()
        with patch.object(dev, "PACKAGE", self.pkg), patch.object(dev.subprocess, "Popen", FakeChild), \
                patch.object(dev.time, "sleep", tick), patch.object(dev.webbrowser, "open"), contextlib.redirect_stdout(out):
            dev.supervise(free_port(), open_browser=False)
        return out.getvalue()

    def test_a_python_change_restarts_the_server_on_the_same_port(self):
        out = self.supervise([lambda: self.touch("server.py"), lambda: None])
        first, second = FakeChild.started
        self.assertEqual(first.cmd, second.cmd)
        self.assertEqual(first.cmd[1:5], ["-m", "lemma", "--dev", "--no-browser"])
        self.assertEqual(first.env[dev.CHILD_ENV], "1")
        self.assertEqual(first.signals, ["TERM"])
        self.assertIn("↻ server.py changed: restarting the server", out)
        self.assertEqual(second.signals, ["TERM"])  # stopped on Ctrl+C too
        self.assertTrue(out.rstrip().endswith("Stopped."))

    def test_after_a_crash_it_waits_for_the_next_edit(self):
        def crash():
            FakeChild.started[-1].returncode = 1

        out = self.supervise([crash, lambda: None, lambda: None, lambda: self.touch("server.py")])
        self.assertEqual(len(FakeChild.started), 2)
        self.assertIn("✗ The server stopped. Fix the error and save to restart.", out)
        self.assertIn("↻ Change detected: starting the server again", out)
        self.assertEqual(FakeChild.started[0].signals, [])  # already gone, so not signalled

    def test_a_child_that_ignores_terminate_is_killed(self):
        class Stubborn(FakeChild):
            def wait(self, timeout=None):
                if timeout and "KILL" not in self.signals:
                    raise subprocess.TimeoutExpired("lemma", timeout)
                return self.returncode

            def terminate(self):
                self.signals.append("TERM")

        child = Stubborn(["lemma"], {})
        dev.stop(child)
        self.assertEqual(child.signals, ["TERM", "KILL"])

    def test_port_free_sees_a_port_in_use(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            self.assertFalse(dev._port_free(s.getsockname()[1]))
        self.assertTrue(dev._port_free(free_port()))


    def test_dev_mode_keeps_its_port_or_stops_saying_why(self):
        # Sign-in returns only to the registered address (localhost:8765), so another port would break it quietly.
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            taken = s.getsockname()[1]
            err = io.StringIO()
            with patch.object(dev, "PORT_WAIT", 0.3), patch.object(dev.subprocess, "Popen") as popen, \
                    contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stop:
                dev.supervise(taken, open_browser=False)
        self.assertNotEqual(stop.exception.code, 0)
        self.assertIn(f"Port {taken} is in use", err.getvalue())
        popen.assert_not_called()

    def test_dev_mode_waits_for_its_port_to_come_free(self):
        port = free_port()
        holder = socket.socket()
        holder.bind(("127.0.0.1", port))
        holder.listen()
        threading.Timer(0.3, holder.close).start()  # the previous Lemma finishes stopping
        self.assertEqual(dev.wait_for_port(port, 3), True)


class FrontendChanges(unittest.TestCase):
    def test_changes_are_reported_relative_to_the_package_with_keep_alives_between(self):
        pkg = Path(tempfile.mkdtemp(prefix="lemma-pkg-"))
        (pkg / "static").mkdir()
        (pkg / "examples").mkdir()
        css = pkg / "static" / "styles.css"
        css.write_text("a {}")
        with patch.object(dev, "PACKAGE", pkg), patch.object(dev, "POLL", 0.01):
            changes = dev.frontend_changes(keepalive=0.03)
            self.assertEqual(next(changes), [])  # nothing changed: a keep-alive
            later = time.time() + 10
            os.utime(css, (later, later))
            self.assertEqual(next(changes), [os.path.join("static", "styles.css")])


if __name__ == "__main__":
    unittest.main()
