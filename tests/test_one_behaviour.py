"""OpenLemma behaves the same on your own computer as hosted for others.

Nothing may differ: sign-in (Google OAuth both ways), the providers (the ChatGPT and Claude subscriptions
included, each signed in per account) and every page. Two checks hold that in place:

* the structure: the switch ``server.http.ON_THIS_COMPUTER`` is read only where the server binds, and the old mode
  switches are gone;
* the behaviour: the same requests to a server on this computer and to one on a public address get the same
  answers.
"""

from __future__ import annotations

import ast
import base64
import json
import re
import unittest
from pathlib import Path

from support import SITE, SOURCE, Site, reset_server, session_cookie

ROOT = Path(__file__).resolve().parent.parent / "lemma"
SWITCHES = {"ON_THIS_COMPUTER"}
# Where the switch may be read: binding (address, port, browser, live reload).
ALLOWED = {("server/http.py", "make_server"), ("__main__.py", "main")}


class Structure(unittest.TestCase):
    def reads(self):
        """(file, enclosing function, line) for every use of the switch that isn't its own definition."""
        found = []
        for path in ROOT.rglob("*.py"):  # the server package too
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in [None, *[n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]]:
                body = tree.body if fn is None else fn.body
                for stmt in body:
                    if fn is None and isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        continue
                    for node in ast.walk(stmt):
                        name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
                        if name in SWITCHES and not (fn is None and isinstance(getattr(node, "ctx", None), ast.Store)):
                            found.append((path.relative_to(ROOT).as_posix(), fn.name if fn else "<module>", node.lineno))
        return found

    def test_the_switch_is_read_only_where_this_computer_offers_differ(self):
        stray = [r for r in self.reads() if (r[0], r[1]) not in ALLOWED]
        self.assertEqual(stray, [], "only how the server binds may depend on where OpenLemma runs")

    def test_the_old_mode_switches_are_gone(self):
        python = "\n".join(p.read_text(encoding="utf-8") for p in ROOT.rglob("*.py"))
        browser = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "static").rglob("*.js"))  # the app's modules too
        self.assertIsNone(re.search(r"\bHOSTED\b", python))
        self.assertIsNone(re.search(r"(?<!ON_)THIS_COMPUTER|\"computer\"", python), "sign-in is the same everywhere")
        self.assertIsNone(re.search(r"\bENABLED\b", (ROOT / "metrics.py").read_text(encoding="utf-8")))
        self.assertIsNone(re.search(r"\.hosted\b", browser), "the browser must not behave differently when hosted")


class Behaviour(unittest.TestCase):
    """The same requests, signed out and signed in, to a server on this computer and to one on a public address."""

    def script(self, public, cookie):
        """(status, shape of the answer, headers) for each request of one script, to a server on this computer or to
        one answering a public domain name."""
        upload = {"filename": "notes.txt", "data": base64.b64encode(SOURCE.encode()).decode()}
        calls = [
            ("GET", "/api/status", None), ("GET", "/api/example", None), ("GET", "/api/gallery", None),
            ("GET", "/api/lessons", None), ("GET", "/api/requests", None), ("GET", "/api/stats", None),
            ("POST", "/api/event", {"name": "lesson_open"}), ("POST", "/api/papers", upload),
            ("POST", "/api/requests", {"sources": []}), ("GET", "/api/lessons/nope", None),
            ("GET", "/api/signin/chatgpt", None), ("GET", "/api/signin/claude-subscription", None),
            ("POST", "/api/signin/claude-subscription/login", {}), ("GET", "/", None), ("GET", "/privacy", None),
            ("GET", "/api/gallery/community", None), ("GET", "/api/shared", None), ("GET", "/api/shared/" + "A" * 22, None),
            ("GET", "/api/shared/" + "A" * 22 + "/about", None), ("GET", "/api/lessons/nope/share", None),
        ]
        kept = ("Content-Security-Policy", "Strict-Transport-Security", "X-Frame-Options", "Referrer-Policy", "Cache-Control")
        out = {}
        with Site(hosted=public, env={"LEMMA_PUBLIC_URL": f"http://{SITE}" if public else ""}, exact=False) as site:
            for method, path, body in calls:
                reply = site.req(method, path, body, cookie=cookie)
                try:
                    data = json.loads(reply.raw)
                except ValueError:
                    data = None
                shape = sorted(data) if isinstance(data, dict) else type(data).__name__
                if path == "/api/status":
                    shape = {k: v for k, v in data.items() if k not in ("providers", "sign_in", "provider")}
                    shape["user"] = bool(shape["user"])
                out[(method, path)] = (reply.status, shape, {k: reply.header(k) for k in kept})
        return out

    def test_the_same_requests_get_the_same_answers(self):
        try:
            for who in ("signed out", "signed in"):
                with self.subTest(who=who):
                    cookie = session_cookie() if who == "signed in" else ""
                    here, public = self.script(False, cookie), self.script(True, cookie)
                    differ = sorted(k for k in here if here[k] != public[k])
                    self.assertEqual(differ, [], [(k, here[k], public[k]) for k in differ])
                    expect = 200 if who == "signed in" else 401  # the subscriptions are offered everywhere, to signed-in accounts
                    self.assertEqual([public[("GET", f"/api/signin/{p}")][0] for p in ("chatgpt", "claude-subscription")], [expect] * 2)
                    # Sharing: the community gallery and a link's title are for anyone; the rest needs an account.
                    self.assertEqual(public[("GET", "/api/gallery/community")][0], 200)
                    self.assertEqual(public[("GET", "/api/shared/" + "A" * 22 + "/about")][0], 404)  # no such link, for anyone
                    self.assertEqual([public[("GET", p)][0] for p in ("/api/shared", "/api/shared/" + "A" * 22, "/api/lessons/nope/share")],
                                     [200, 404, 404] if who == "signed in" else [401] * 3)
        finally:
            reset_server()


if __name__ == "__main__":
    unittest.main()
