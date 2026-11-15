"""The app is native ES modules (lemma/static/app/), loaded by one module script after the classic scripts it builds
on (ui.js, progress.js, player.js), and all fetched at once (modulepreload). Every module parses and links: each import
names a module that exists and a name it exports, and main.js reaches them all. The server serves them, and only them,
from static/app/."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest

from support import ROOT, Site

STATIC = ROOT / "lemma" / "static"


class Modules(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is needed to link the modules")
    def test_every_module_parses_and_every_import_resolves(self):
        run = subprocess.run(["node", "--experimental-vm-modules", "tests/app_modules.js"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("PASS main.js reaches every module", run.stdout)

    def test_the_page_loads_the_app_as_one_module_after_the_classic_scripts(self):
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        tags = re.findall(r'<script( type="module")? src="static/([a-z/-]+\.js)"></script>', page)
        self.assertEqual([src for module, src in tags if module], ["app/main.js"])
        self.assertEqual(tags[-1], (' type="module"', "app/main.js"))
        self.assertFalse((STATIC / "app.js").exists())

    def test_every_module_is_fetched_at_once(self):
        # Without these, the browser finds the modules one import at a time: a round trip per level of the graph.
        page = (STATIC / "index.html").read_text(encoding="utf-8")
        preloaded = re.findall(r'<link rel="modulepreload" href="static/(app/[a-z]+\.js)">', page)
        self.assertEqual(sorted(preloaded), sorted(f"app/{f.name}" for f in (STATIC / "app").glob("*.js")))
        self.assertLess(page.index('rel="modulepreload"'), page.index("</head>"))

    def test_the_server_serves_the_modules_as_javascript(self):
        with Site() as site:
            for f in sorted((STATIC / "app").glob("*.js")):
                r = site.req("GET", f"/static/app/{f.name}", origin=False)
                with self.subTest(f.name):
                    self.assertEqual(r.status, 200)
                    self.assertIn("javascript", r.header("Content-Type"))
            for bad in ("/static/app/../index.html", "/static/app/sub/x.js", "/static/lib/x.js"):
                with self.subTest(bad):
                    self.assertEqual(site.req("GET", bad, origin=False).status, 404)


if __name__ == "__main__":
    unittest.main()
