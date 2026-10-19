"""Hostile expressions finish quickly, and both engines agree on NaN, infinity, and rounding.

Expected values follow JavaScript semantics, since learners see the browser's result.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from lemma import expr

ROOT = Path(__file__).resolve().parent.parent

# Checked in a child process, so a regression fails the test instead of hanging the suite.
HOSTILE = {
    "round(1, 1e8)": 1,
    "round(1, -1e8)": 0,
    "round(1, 1/0)": 1,
    "binom(1e6, 5e5)": math.inf,
    "binom(1e9, 5e8)": math.inf,
    "binom(1e15, 5e14)": math.inf,
    "binom(1e300, 1e299)": math.inf,
    "binom(1/0, 1/0)": math.nan,
    "binom(1/0, 2)": math.nan,
}

EXPECTED = {
    "(0/0) ? 1 : 2": 2,
    "!(0/0)": 1,
    "not (0/0)": 1,
    "(0/0) && 1": 0,
    "1 && (0/0)": 0,
    "(0/0) || 0": 0,
    "(0/0) || 1": 1,
    "max(1, 0/0)": math.nan,
    "max(0/0, 1)": math.nan,
    "min(1, 0/0)": math.nan,
    "min(0/0, 1)": math.nan,
    "clamp(0/0, 0, 1)": math.nan,
    "clamp(5, 0/0, 1)": math.nan,
    "abs(0/0)": math.nan,
    "sign(0/0)": 0,
    "floor(0/0)": math.nan,
    "floor(-1/0)": -math.inf,
    "ceil(-1/0)": -math.inf,
    "round(-1/0)": -math.inf,
    "round(1/0)": math.inf,
    "round(0/0)": math.nan,
    "round(2.5)": 3,
    "round(-2.5)": -2,
    "round(2.25, 1)": 2.3,
    "round(1, 0/0)": math.nan,
    "round(1234.5, -1e8)": 0,
    "(0/0) == (0/0)": 0,
    "(0/0) != 1": 1,
    "(1/0) != (1/0)": 1,
    "(0/0) < 1": 0,
    "(1/0) % 2": math.nan,
    "5 % (1/0)": 5,
    "pow(0, -1)": math.inf,
    "0 ^ -1": math.inf,
    "(-0) ^ (-1)": -math.inf,
    "pow(-10, 1001)": -math.inf,
    "pow(-10, 1000)": math.inf,
    "pow(1, 0/0)": math.nan,
    "pow(1, 1/0)": math.nan,
    "pow(-1, -1/0)": math.nan,
    "pow(0/0, 0)": 1,
    "binom(0/0, 2)": math.nan,
    "binom(4, 2.5)": 4,
    "binom(7, 3)": 35,
    "binom(-1, 2)": 0,
    "binom(60, 30)": 118264581564861424,
}

LARGE_BINOMS = ["binom(1000, 500)", "binom(1030, 515)", "binom(1e15, 2)", "binom(200, 100)"]


def same(a, b) -> bool:
    if isinstance(a, float) and math.isnan(a):
        return isinstance(b, float) and math.isnan(b)
    if math.isinf(a) or math.isinf(b):
        return a == b
    return abs(a - b) <= 1e-12 * max(1.0, abs(a))


# JSON has no NaN or infinity, so non-finite results travel as strings.
NODE_EVAL = """
require("./lemma/static/expr.js");
const exprs = JSON.parse(require("fs").readFileSync(0, "utf8"));
const enc = (v) => (Number.isFinite(v) ? v : String(v));
process.stdout.write(JSON.stringify(exprs.map((e) => { const t = Date.now(); const v = LemmaExpr.evaluate(e, {}); return [enc(v), Date.now() - t]; })));
"""


def run_node(exprs: list[str]) -> list:
    out = subprocess.run(["node", "-e", NODE_EVAL], input=json.dumps(exprs), capture_output=True, text=True, timeout=10, check=True, cwd=ROOT)
    return [[float(v) if isinstance(v, str) else v, ms] for v, ms in json.loads(out.stdout)]


class BoundedTimeTests(unittest.TestCase):
    def test_hostile_expressions_finish_quickly_in_python(self):
        child = (
            "import json, sys, time\n"
            "from lemma import expr\n"
            "for e in json.loads(sys.argv[1]):\n"
            "    t = time.perf_counter(); v = expr.evaluate(e, {})\n"
            "    print(json.dumps([e, time.perf_counter() - t, v]), flush=True)\n"
        )
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        try:
            out = subprocess.run([sys.executable, "-c", child, json.dumps(list(HOSTILE))], capture_output=True, text=True, timeout=10, env=env, cwd=ROOT, check=True)
        except subprocess.TimeoutExpired as err:
            done = err.stdout.decode() if isinstance(err.stdout, bytes) else err.stdout
            self.fail(f"expression evaluation hung; finished before the hang: {done!r}")
        lines = out.stdout.splitlines()
        self.assertEqual(len(lines), len(HOSTILE))
        for line in lines:
            e, seconds, got = json.loads(line)
            self.assertLess(seconds, 0.5, e)
            self.assertTrue(same(got, float(HOSTILE[e])), f"{e}: got {got!r}, want {HOSTILE[e]!r}")

    @unittest.skipUnless(shutil.which("node"), "node is needed to time the browser engine")
    def test_hostile_expressions_finish_quickly_in_javascript(self):
        try:
            results = run_node(list(HOSTILE))
        except subprocess.TimeoutExpired:
            self.fail("browser engine hung on a hostile expression")
        for e, (got, ms) in zip(HOSTILE, results):
            self.assertLess(ms, 500, e)
            self.assertTrue(same(got, float(HOSTILE[e])), f"{e}: got {got!r}, want {HOSTILE[e]!r}")


class JavaScriptSemanticsTests(unittest.TestCase):
    def test_python_follows_javascript_semantics(self):
        for e, want in EXPECTED.items():
            with self.subTest(e):
                got = expr.evaluate(e, {})
                self.assertTrue(same(got, float(want)), f"got {got!r}, want {want!r}")


@unittest.skipUnless(shutil.which("node"), "node is needed to compare with the browser engine")
class NonFiniteParityTests(unittest.TestCase):
    def test_engines_agree_on_edge_cases(self):
        cases = list(EXPECTED) + LARGE_BINOMS
        try:
            js = run_node(cases)
        except subprocess.TimeoutExpired:
            self.fail("browser engine hung on an edge case")
        for e, (jv, _) in zip(cases, js):
            with self.subTest(e):
                pv = expr.evaluate(e, {})
                self.assertTrue(same(pv, jv), f"python {pv!r}, javascript {jv!r}")


if __name__ == "__main__":
    unittest.main()
