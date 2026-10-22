"""Run with: python -m unittest discover tests"""

from __future__ import annotations

import base64
import copy
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
TMP_HOME = tempfile.mkdtemp(prefix="lemma-test-")
os.environ["LEMMA_HOME"] = TMP_HOME

from lemma import auth, categorize, chatgpt, jev, claude, dev, expr, export, generate, ingest, kernels, lesson as L, llm, metrics, search, server, store  # noqa: E402
from lemma.llm import Provider, Reply  # noqa: E402
import fakejev  # noqa: E402,F401  Jev is essential, so every search and build asks this stand-in


# Every person signs in, on their own computer as when hosted, so tests act as a signed-in account too. TESTER is
# the Google account "tester": API calls made straight from a test and HTTP requests that carry session_cookie()
# act as the same account.
TESTER = hashlib.sha256(b"google:tester").hexdigest()[:16]


def sign_in(uid: str = TESTER) -> dict:
    """Signs `uid` in for API functions called straight from a test, as a browser session would."""
    server.REQUEST.user = {"id": uid, "provider": "google", "name": "Tester", "email": f"{uid}@example.com", "avatar": "", "created": 0}
    return server.REQUEST.user


def reset_server():
    """Puts back what server.make_server sets, as for a server on this computer, and signs nobody in."""
    server.ON_THIS_COMPUTER, server.ALLOWED_HOSTS = True, server.LOCAL_HOSTS
    auth.LOCAL_URL = ""
    server.REQUEST.user = None


def session_cookie(name: str = "tester") -> str:
    """A Cookie header for HTTP requests, from a real session of the Google account `name`."""
    user = auth.upsert_user("google", name, name, f"{name}@example.com", "")
    return f"{auth.SESSION_COOKIE}={auth.new_session(user['id'])}"

EXAMPLE = json.loads((ROOT / "lemma/examples/gallery/galton-1886.json").read_text())
SOURCE = (ROOT / "lemma/examples/galton-1886.txt").read_text()
NORM = L.normalize_for_match(SOURCE)


def concept(i=1):
    return copy.deepcopy(EXAMPLE["concepts"][i])


class ExprTests(unittest.TestCase):
    def test_precedence_and_functions(self):
        self.assertEqual(expr.evaluate("1 + 2 * 3 ^ 2", {}), 19)
        self.assertEqual(expr.evaluate("-2^2", {}), -4)
        self.assertEqual(expr.evaluate("x > 1 && y < 1 ? 10 : 20", {"x": 2, "y": 0}), 10)
        self.assertAlmostEqual(expr.evaluate("normcdf(1.96)", {}), 0.975, places=3)
        self.assertEqual(expr.names("a + sin(b) * c"), {"a", "b", "c"})

    def test_errors(self):
        for bad in ("1 +", "foo(1)", "sqrt(1, 2)", "a $ b", "(1"):
            with self.assertRaises(expr.ExprError):
                expr.evaluate(bad, {"a": 1, "b": 1})
        with self.assertRaises(expr.ExprError):
            expr.evaluate("missing + 1", {})

    def test_deep_nesting_is_an_error_not_a_crash(self):
        deep = "sqrt(" * (expr.MAX_NESTING + 1) + "x" + ")" * (expr.MAX_NESTING + 1)
        within = "(" * expr.MAX_NESTING + "x" + ")" * expr.MAX_NESTING
        self.assertEqual(expr.evaluate(within, {"x": 4}), 4)
        for bad in (deep, "(" * 2000 + "1" + ")" * 2000, "x ? 1 : " * 3000 + "0", "-" * 5000 + "1"):
            with self.assertRaises(expr.ExprError):
                expr.evaluate(bad, {"x": 1})
        with self.assertRaises(expr.ExprError):
            expr.names(deep)

    def test_non_finite_does_not_raise(self):
        self.assertEqual(expr.evaluate("1/0", {}), float("inf"))
        self.assertNotEqual(expr.evaluate("sqrt(-1)", {}), expr.evaluate("sqrt(-1)", {}))  # nan


@unittest.skipUnless(shutil.which("node"), "node is needed to compare with the browser engine")
class BrowserParityTests(unittest.TestCase):
    def test_kernels_and_expressions_match_javascript(self):
        cases = {
            "kernels": [["schelling", {"tolerance": 0.5}], ["sir", {"vaccinated": 0.3}], ["opinion", {}], ["opinion", {"rule": 1, "confidence": 0.15, "agents": 300, "rounds": 200}], ["network", {"rule": 1}],
                        ["mean", {"n": 5}], ["two_group", {"mu2": 0.4}], ["regression", {"r": 0.6, "seed": 54, "people": 1000}]],
            "exprs": [["normcdf(x, 1, 2) + norminv(0.3) * binom(7, 3)", {"x": 0.4}], ["round(2.345, 2) - 7 % 3", {}], ["a == 0.3", {"a": 0.1 + 0.2}],
                      ["(" * expr.MAX_NESTING + "1" + ")" * expr.MAX_NESTING, {}], ["max(" * (expr.MAX_NESTING + 1) + "1" + ")" * (expr.MAX_NESTING + 1), {}]],
        }
        out = subprocess.run(["node", str(ROOT / "tests/crosscheck.js")], input=json.dumps(cases), capture_output=True, text=True, check=True)
        js = json.loads(out.stdout)
        for (k, p), jm in zip(cases["kernels"], js["kernels"]):
            for key, v in kernels.run(k, p).items():
                self.assertAlmostEqual(v, jm[key], places=12, msg=f"{k}.{key}")
        for (e, env), jv in zip(cases["exprs"], js["exprs"]):
            try:
                self.assertAlmostEqual(expr.evaluate(e, env), jv, places=12, msg=e)
            except expr.ExprError:
                self.assertEqual(jv, "ERR", e)  # both engines reject the same expressions


class CheckTests(unittest.TestCase):
    def test_example_lesson_passes(self):
        self.assertEqual(list(L.check_lesson(EXAMPLE, SOURCE)), [])

    def test_concept_must_be_taught_before_it_is_asked(self):
        c = concept()
        c["animation"] = None
        self.assertTrue(any("narrated tour" in p for p in L.check_concept(c, NORM)))
        c = concept()
        del c["understand"]["walkthrough"]
        self.assertTrue(any("walkthrough" in p for p in L.check_concept(c, NORM)))

    def test_goals_leave_the_answer_for_the_learner(self):
        c = concept()  # the share passed on: its goal's solution is ratio = 0.65
        self.assertEqual(list(L.check_concept(c, NORM)), [])
        c["explore"]["goals"][0]["hints"][-1] = "Try a share of 0.65."
        self.assertTrue(any("hint 3 gives away the solution ratio = 0.65" in p for p in L.check_concept(c, NORM)))
        c = concept()
        c["explore"]["goals"][0]["text"] = "Set the share passed on to 0.65"
        self.assertTrue(any("its text gives away" in p for p in L.check_concept(c, NORM)))
        c = concept()
        c["explore"]["goals"][0]["hints"][-1] = "Keep the mid-parent at 72 and watch the child box."  # 72 is the default, not the answer
        self.assertEqual(list(L.check_concept(c, NORM)), [])

    def test_narration_focus_must_name_a_part_of_the_model(self):
        c = concept()
        c["animation"]["steps"][0]["focus"] = "nonsense"
        self.assertTrue(any("focus 'nonsense'" in p for p in L.check_concept(c, NORM)))

    def test_narration_can_point_at_marked_parts_of_the_picture(self):
        c = concept(0)  # the example's first concept names its three bars at once
        self.assertEqual(c["animation"]["steps"][0]["focus"], ["father_bar", "mother_bar", "mid_bar"])
        self.assertEqual(list(L.check_concept(c, NORM)), [])
        c["animation"]["steps"][0]["focus"] = ["father_bar", "unmarked_bar"]
        self.assertTrue(any("focus 'unmarked_bar'" in p for p in L.check_concept(c, NORM)))
        c["animation"]["steps"][0]["focus"] = ["father_bar"] * 5
        self.assertTrue(any("list 1–4 parts" in p for p in L.check_concept(c, NORM)))
        del c["model"]["visual"]["bars"][0]["id"]
        c["animation"]["steps"][0]["focus"] = "father_bar"
        self.assertTrue(any("focus 'father_bar'" in p for p in L.check_concept(c, NORM)))

    def test_checks_are_only_for_hard_concepts(self):
        c = concept(1)
        self.assertNotIn("check", c)
        self.assertEqual(list(L.check_concept(c, NORM)), [])
        lesson = copy.deepcopy(EXAMPLE)
        for c in lesson["concepts"][:2]:
            c["check"] = {"kind": "truefalse", "statement": "x", "answer": True, "hint": "h", "misconception": "m"}
        self.assertTrue(any("one or two hardest" in p for p in L.check_lesson(lesson, SOURCE)))

    def test_every_hunch_option_explains_itself(self):
        c = concept()
        del c["predict"]["why"]
        self.assertTrue(any("'why'" in p for p in L.check_concept(c, NORM)))
        c = concept()
        c["predict"]["why"] = c["predict"]["why"][:-1]
        self.assertTrue(any("'why'" in p for p in L.check_concept(c, NORM)))

    def test_goals_have_a_ladder_of_hints(self):
        c = concept()
        c["explore"]["goals"][0]["hints"] = ["Just one"]
        self.assertTrue(any("2–3 lines" in p for p in L.check_concept(c, NORM)))

    def test_terms_are_shown_before_they_are_named(self):
        c = concept(2)
        c["animation"]["steps"][0]["say"] = "This picture shows regression to the mean."
        self.assertTrue(any("used before it is explained" in p for p in L.check_concept(c, NORM)))
        c = concept(2)  # goals and the use-it question come after the walkthrough, so they may name it
        c["explore"]["goals"][0]["text"] = "Show regression to the mean by weakening the link (within 3 points of 67%)"
        self.assertFalse(any("used before it is explained" in p for p in L.check_concept(c, NORM)))
        c = concept(2)
        c["terms"].append({"term": "heritability", "means": "x"})
        self.assertTrue(any("never appears" in p for p in L.check_concept(c, NORM)))

    def test_paper_in_brief_is_grounded(self):
        self.assertEqual(list(L.check_primer(EXAMPLE["primer"], NORM)), [])
        lesson = copy.deepcopy(EXAMPLE)
        lesson["primer"][0]["quote"] = "Galton proved that height is entirely inherited from the father."
        self.assertTrue(any("word for word" in p for p in L.check_lesson(lesson, SOURCE)))
        lesson = copy.deepcopy(EXAMPLE)
        for pg in lesson["primer"]:
            pg.pop("quote", None)
        self.assertTrue(any("at least two pages" in p for p in L.check_lesson(lesson, SOURCE)))
        lesson["primer"] = lesson["primer"][:2]
        self.assertTrue(any("3–6 pages" in p for p in L.check_lesson(lesson, SOURCE)))
        del lesson["primer"]  # lessons saved before the primer existed still pass
        self.assertEqual(list(L.check_lesson(lesson, SOURCE)), [])

    def test_builds_on_must_reuse_the_earlier_model(self):
        lesson = copy.deepcopy(EXAMPLE)
        lesson["concepts"][1]["builds_on"] = "mid_parent"
        self.assertTrue(any("visual type" in p for p in L.check_lesson(lesson, SOURCE)))
        lesson = copy.deepcopy(EXAMPLE)
        more = copy.deepcopy(EXAMPLE["concepts"][0])
        more.update(id="mid_parent_more", builds_on="mid_parent")
        lesson["concepts"].insert(1, more)
        self.assertEqual(list(L.check_lesson(lesson, SOURCE)), [])
        more["model"]["controls"][0]["max"] = 90
        self.assertTrue(any("same label and range" in p for p in L.check_lesson(lesson, SOURCE)))
        lesson["concepts"].insert(0, lesson["concepts"].pop(1))
        self.assertTrue(any("earlier concept" in p for p in L.check_lesson(lesson, SOURCE)))

    def test_quote_must_be_in_paper(self):
        c = concept()
        c["understand"]["quote"] = "children are exactly as tall as the average of their two parents in every family"
        self.assertTrue(any("word for word" in p for p in L.check_concept(c, NORM)))

    def test_quote_tolerates_pdf_spacing(self):
        # The source has "T his  m em oir contains" from OCR.
        self.assertTrue(L.quote_in_source("This memoir contains the data upon which the remarks on the Law of Regression were founded", NORM))

    def test_goal_true_at_start_is_rejected(self):
        c = concept()
        c["explore"]["goals"][0]["when"] = "mp > 60"
        self.assertTrue(any("already true" in p for p in L.check_concept(c, NORM)))

    def test_goal_false_at_solution_is_rejected(self):
        c = concept()
        c["explore"]["goals"][0]["solution"] = {"ratio": 0.2}
        self.assertTrue(any("false at its own solution" in p for p in L.check_concept(c, NORM)))

    def test_solution_off_step_grid_is_rejected(self):
        c = concept()
        c["explore"]["goals"][0]["solution"] = {"ratio": 0.6667}
        self.assertTrue(any("not reachable with step" in p for p in L.check_concept(c, NORM)))

    def test_unknown_names_and_non_finite_outputs(self):
        c = concept()
        c["model"]["outputs"][0]["expr"] = "mp - avg_height"
        self.assertTrue(any("unknown names" in p for p in L.check_concept(c, NORM)))
        c = concept()
        c["model"]["outputs"][0]["expr"] = "1 / (ratio - 0.5)"
        self.assertTrue(any("not a finite number" in p for p in L.check_concept(c, NORM)))

    def test_model_must_be_labelled(self):
        c = concept()
        del c["model"]["note"]
        self.assertTrue(any("teaching model" in p for p in L.check_concept(c, NORM)))

    def test_simulation_goals_are_checked_with_the_kernel(self):
        c = concept(2)
        c["explore"]["goals"][0]["solution"] = {"r": 0.9}
        self.assertTrue(any("false at its own solution" in p for p in L.check_concept(c, NORM)))

    def test_check_formats(self):
        c = concept()
        c["check"] = {"kind": "order", "prompt": "Order", "items": ["a", "b"], "hint": "h", "misconception": "m"}
        self.assertTrue(any("3–6 items" in p for p in L.check_concept(c, NORM)))
        c["check"] = {"kind": "numeric", "question": "q", "answer": 2, "tolerance": 0.1, "hint": "h", "misconception": "m"}
        self.assertEqual(list(L.check_concept(c, NORM)), [])

    def test_equation_needs_a_link(self):
        c = concept()
        for part in c["connect"]["equation"]:
            part.pop("link", None)
        self.assertTrue(any("link" in p for p in L.check_concept(c, NORM)))


class FakeConversation:
    def __init__(self, provider, document):
        self.p, self.document, self.turns = provider, document, 0

    def send(self, text, cancelled=None, on_progress=None):
        with self.p.lock:
            self.p.calls += 1
        self.turns += 1
        if self.turns == 1:
            self.task = text
        reply = self.p.reply(self.task, self.turns)
        if on_progress:  # streams like a real model: some thinking, then the reply written out
            on_progress("thinking", 0)
            on_progress("writing", len(reply.text))
        return reply

    def close(self):
        with self.p.lock:
            self.p.closed += 1


FAKE_PLANS = [{"blocks": ["watch", "walk", "explain", "goal", "predict", "reveal", "connect"], "why": "Explore the model, then apply it."},
              {"blocks": ["explain", "worked", "choice"], "why": "A worked example, then a question."}]


class FakeProvider(Provider):
    """Answers like a model would: an outline, then concepts; the first draft of one concept has a bad quote."""

    id, name, model, label = "fake", "Fake", "fake-1", "Fake"

    def __init__(self):
        self.calls = 0
        self.closed = 0
        self.lock = threading.Lock()

    def available(self):
        return True, ""

    def warm(self, system, document):
        assert "LESSON FORMAT" in system and document.startswith("<paper>")
        self.warmed = getattr(self, "warmed", []) + [self.calls]  # how many replies came before each warm-up

    def conversation(self, system, document):
        assert "LESSON FORMAT" in system and document.startswith("<paper>")
        return FakeConversation(self, document)

    def reply(self, task, turn):
        self.tasks = getattr(self, "tasks", {})
        if "propose a path" in task.lower():
            self.tasks["outline"] = task
            return Reply(json.dumps({
                "title": EXAMPLE["title"], "source": {"title": EXAMPLE["source"]["title"], "authors": "Francis Galton", "year": 1886, "venue": None},
                "summary": EXAMPLE["intro"]["summary"], "background": EXAMPLE["intro"]["background"], "aha": EXAMPLE["intro"]["aha"],
                "primer": EXAMPLE["primer"],
                "concepts": [{"id": c["id"], "title": c["title"], "idea": c["idea"], "role": c["role"], "visual": c["model"]["visual"]["type"], "why": "fits", "hard": c.get("hard", False), "plans": FAKE_PLANS,
                              "needs": [EXAMPLE["concepts"][i - 1]["id"]] if i else []} for i, c in enumerate(EXAMPLE["concepts"])],
            }), "end_turn")
        cid = task.split('Its id must be "')[1].split('"')[0]
        self.tasks = getattr(self, "tasks", {})
        self.tasks[cid] = task
        if cid == "mid_parent_more":  # builds on mid_parent: same model, one new idea
            c = copy.deepcopy(EXAMPLE["concepts"][0])
            c["id"], c["title"] = cid, "More about the mid-parent"
            return Reply(json.dumps(c), "end_turn")
        c = copy.deepcopy(next(x for x in EXAMPLE["concepts"] if x["id"] == cid))
        if cid == "regression_line" and turn == 1:
            c["understand"]["quote"] = "Children are always exactly two thirds as tall as their parents."
        return Reply("```json\n" + json.dumps(c) + "\n```", "end_turn")


def wait(job, timeout=30):
    t0 = time.time()
    while job.status == "running" and time.time() - t0 < timeout:
        time.sleep(0.05)
    return job


class GenerationTests(unittest.TestCase):
    def test_outline_and_build_with_repair(self):
        fp = FakeProvider()
        job = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "a curious learner"))
        self.assertEqual(job.status, "done", job.error)
        outline = job.result
        outline["concepts"][0]["known"] = True
        paper = {"text": SOURCE, "title": "Galton", "url": ""}
        job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, paper, outline, "a curious learner"))
        self.assertEqual(job.status, "done", job.error)
        lesson = job.result
        self.assertEqual([c["id"] for c in lesson["concepts"]], ["regression_line", "why_regression"])
        self.assertEqual(lesson["intro"]["known"], [EXAMPLE["concepts"][0]["title"]])
        self.assertEqual(list(L.check_lesson(lesson, SOURCE)), [])
        steps = {s["id"]: s for s in job.snapshot()["steps"]}
        self.assertEqual(steps["regression_line"]["state"], "done")
        self.assertEqual(fp.calls, 1 + 2 + 1)  # outline, two concepts, one repair
        self.assertEqual(lesson["primer"], EXAMPLE["primer"])  # the paper in brief comes from the outline

    def test_outline_needs_a_grounded_paper_in_brief(self):
        fp = FakeProvider()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        self.assertEqual(generate.check_outline(outline, SOURCE), [])
        bad = copy.deepcopy(outline)
        bad["primer"][0]["quote"] = "Height is decided entirely by the father, Galton wrote."
        self.assertTrue(any("word for word" in p for p in generate.check_outline(bad, SOURCE)))
        del bad["primer"]
        self.assertTrue(any(p.startswith("primer") for p in generate.check_outline(bad)))

    def test_outline_meets_the_finished_lessons_intro_limits(self):
        fp = FakeProvider()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        long = copy.deepcopy(outline)
        long["aha"] = "x" * 301
        self.assertTrue(any("'aha' is too long" in p for p in generate.check_outline(long, SOURCE)))
        long = copy.deepcopy(outline)
        long["summary"] = "x" * 1501
        self.assertTrue(any("'summary' is too long" in p for p in generate.check_outline(long, SOURCE)))

    def test_concept_that_never_passes_is_left_out(self):
        class Stubborn(FakeProvider):
            def reply(self, task, turn):
                return super().reply(task, 1)  # repeats the bad first draft

        fp = Stubborn()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual([o["title"] for o in job.result["omitted"]], [EXAMPLE["concepts"][1]["title"]])
        self.assertEqual(len(job.result["concepts"]), 2)
        self.assertEqual(fp.closed, 4)  # every conversation is closed, including the failed one

    def build_with_jev(self, flagged):
        """Build the example with a fake Jev that flags concepts while `flagged(concept_id, round)` says so."""
        from lemma import factcheck
        rounds = {}

        def fake(c, paper, n=1, link=None):
            rounds[c["id"]] = rounds.get(c["id"], 0) + 1
            if flagged(c["id"], rounds[c["id"]]):
                return [factcheck.Flag("concept: " + factcheck.REPAIR["fabricated_finding"], "fabricated_finding", .9)]
            return []

        class Recording(FakeProvider):  # keeps every message the model was sent
            sent = []

            def conversation(self, system, document):
                conv = super().conversation(system, document)
                send = conv.send
                conv.send = lambda text, *a, **k: (self.sent.append(text), send(text, *a, **k))[1]
                return conv

        fp = Recording()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        with patch.object(factcheck, "check_concept", side_effect=fake):
            job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        self.assertEqual(job.status, "done", job.error)
        return job, fp, rounds

    def test_a_jev_flag_is_sent_back_for_repair(self):
        job, fp, rounds = self.build_with_jev(lambda cid, n: cid == "mid_parent" and n == 1)
        self.assertEqual(rounds["mid_parent"], 2)  # flagged, repaired, then judged clean
        self.assertEqual(len(job.result["concepts"]), 3)
        self.assertNotIn("flags", job.result)
        self.assertEqual(sum("independent check" in m for m in fp.sent), 1)  # the model was asked to fix what Jev found

    def test_factcheck_asks_the_reliable_kinds_and_confirms_only_sure_majorities(self):
        from lemma import factcheck
        concept = EXAMPLE["concepts"][1]
        asked = factcheck.questions_for(concept)
        self.assertEqual({k.split("|")[0].split(":")[0] for k in asked}, set(factcheck.BUILD_KINDS))
        self.assertEqual(len({k.split("|")[1] for k in asked}), 3)  # every question through all three lenses

        def ask(state, questions, timeout):
            self.assertIn("WHAT THE MODEL DOES", state)
            self.assertIn("FROM THE PAPER", state)
            sure = {"wrong_claim": [.9, .8, .2], "fabricated_finding": [.9, .6, .65]}  # sure majority / unsure majority
            return {k: {"type": "noul", "noul": sure.get(k.split("|")[0], [.1] * 3)[list(factcheck.LENSES).index(k.split("|")[1])]} for k in questions}

        with patch.object(jev, "available", return_value=True), patch.object(jev, "ask", side_effect=ask):
            flags = factcheck.check_concept(concept, SOURCE)
        self.assertEqual([f.kind for f in flags], ["wrong_claim"])
        self.assertTrue(flags[0].startswith("concept: an independent check"))
        with patch.object(jev, "ask", side_effect=jev.JevError("Jev answered 529")):
            with self.assertRaises(jev.JevError):  # a concept Jev couldn't check is never passed unchecked
                factcheck.check_concept(concept, SOURCE)

    def test_a_concept_jev_cannot_check_is_left_out(self):
        from lemma import factcheck
        fp = FakeProvider()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        real = factcheck.check_concept

        def failing(c, paper, n=1, link=None):
            if c.get("id") == "mid_parent":
                raise jev.JevError("Jev answered 503")
            return real(c, paper, n)

        with patch.object(factcheck, "check_concept", side_effect=failing):
            job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        self.assertNotIn("mid_parent", [c["id"] for c in job.result["concepts"]])
        self.assertIn("the checks couldn't run on it", job.result["omitted"][0]["reason"])

    def test_an_unexpected_error_in_one_concept_leaves_only_that_concept_out(self):
        from lemma import factcheck
        fp = FakeProvider()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        real = factcheck.check_concept

        def failing(c, paper, n=1, link=None):
            if c.get("id") == "mid_parent":
                raise RecursionError("maximum recursion depth exceeded")
            return real(c, paper, n)

        with patch.object(factcheck, "check_concept", side_effect=failing), patch("sys.stderr"):
            job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        self.assertEqual(job.status, "done", job.error)
        self.assertNotIn("mid_parent", [c["id"] for c in job.result["concepts"]])
        self.assertTrue(job.result["concepts"])  # the other concepts are kept
        self.assertIn("unexpected error while checking it (RecursionError", job.result["omitted"][0]["reason"])

    def test_nothing_is_paid_for_without_jev(self):
        fp = FakeProvider()
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            job = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, ""))
            self.assertEqual(job.status, "error")
            self.assertIn("TYPESAFE_API_KEY", job.error)
            job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, {"concepts": []}, ""))
            self.assertEqual(job.status, "error")
        self.assertEqual(fp.calls, 0)

    def test_a_flag_that_stays_never_leaves_a_concept_out(self):
        job, fp, rounds = self.build_with_jev(lambda cid, n: cid == "mid_parent")
        self.assertEqual(rounds["mid_parent"], generate.MAX_REPAIRS + 1)  # every draft was judged
        self.assertEqual(job.result["omitted"], [])
        self.assertIn("mid_parent", [c["id"] for c in job.result["concepts"]])
        self.assertEqual(job.result["flags"], [{"concept": "mid_parent", "kind": "fabricated_finding", "certainty": .9}])
        step = next(s for s in job.snapshot()["steps"] if s["id"] == "mid_parent")
        self.assertIn("possible problem it couldn't confirm", step["detail"])
        self.assertEqual(list(L.check_lesson(job.result, SOURCE)), [])

    def test_only_hard_concepts_keep_a_check(self):
        fp = FakeProvider()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        checked = [c["id"] for c in job.result["concepts"] if c.get("check")]
        self.assertEqual(checked, ["why_regression"])
        outline["concepts"] = [dict(c, hard=True) for c in outline["concepts"]]
        self.assertIn("mark at most two concepts as hard", generate.check_outline(outline))

    def test_the_paper_is_cached_once_before_concepts_start(self):
        fp = FakeProvider()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        before = fp.calls
        job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(fp.warmed, [before])  # once, and before any concept was drafted

    def test_outline_plans_are_checked(self):
        fp = FakeProvider()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        self.assertEqual(generate.check_outline(outline, SOURCE, require_needs=True), [])
        self.assertIn("plans", fp.tasks["outline"])
        bad = copy.deepcopy(outline)
        bad["concepts"][0].pop("plans")
        self.assertTrue(any("needs 'plans'" in p for p in generate.check_outline(bad, SOURCE, require_needs=True)))
        self.assertEqual(generate.check_outline(bad, SOURCE), [])  # an outline saved before plans existed still builds
        bad = copy.deepcopy(outline)
        bad["concepts"][0]["plans"] = [{"blocks": ["explain", "teleport"], "why": "x"}]
        self.assertTrue(any("activity kinds" in p for p in generate.check_outline(bad)))
        bad["concepts"][0]["plans"] = [{"blocks": ["explain", "worked"], "why": "Teaches but never asks."}]
        self.assertTrue(any("teach and then ask" in p for p in generate.check_outline(bad)))
        bad = copy.deepcopy(outline)
        bad["concepts"][1]["visual"] = "none"
        self.assertTrue(any("uses model blocks" in p for p in generate.check_outline(bad)))
        bad["concepts"][1]["plans"] = [{"blocks": ["explain", "stages", "choice"], "why": "Staged evidence, then a question."}]
        self.assertEqual(generate.check_outline(bad), [])
        bad["concepts"][1]["builds_on"] = bad["concepts"][0]["id"]
        self.assertTrue(any("cannot build on" in p for p in generate.check_outline(bad)))

    def test_jev_chooses_each_concepts_plan_before_drafting(self):
        fp = FakeProvider()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        asked = []

        def choose(state, questions, timeout):
            asked.append((state, questions))
            return {"_model": "jev-test", **{cid: {"choice": "p2" if i == 0 else "none_suitable", "confidence": .8} for i, cid in enumerate(questions)}}

        with patch.object(jev, "ask", side_effect=lambda state, q, t: choose(state, q, t) if "concepts" in state else fakejev.answer(state, q, t)):
            job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        self.assertEqual(job.status, "done", job.error)
        state, questions = asked[0]
        first = outline["concepts"][0]["id"]
        self.assertEqual(set(questions[first]["criteria"]), {"p1", "p2", "none_suitable"})
        self.assertIn("explain → worked → choice", fp.tasks[first])  # Jev's choice reached the concept prompt
        self.assertIn("choose the blocks that best fit", fp.tasks[outline["concepts"][1]["id"]])  # none suitable: the model chooses
        plans = {x["concept"]: x for x in job.result["activity_plans"]}
        self.assertEqual(plans[first]["chosen"], "p2")
        self.assertEqual(plans[first]["options"], FAKE_PLANS)
        self.assertEqual([s["state"] for s in job.snapshot()["steps"] if s["id"] == "plans"], ["done"])

    def test_no_concept_is_drafted_when_jev_cannot_choose_plans(self):
        fp = FakeProvider()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        calls = fp.calls
        with patch.object(jev, "ask", side_effect=jev.JevError("Jev answered 503")):
            job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        self.assertEqual(job.status, "error")
        self.assertIn("Couldn't choose how to teach", job.error)
        self.assertEqual(fp.calls, calls)

    def test_a_concept_without_a_model_is_built_from_activities(self):
        class NoModel(FakeProvider):
            def reply(self, task, turn):
                if "A CONCEPT WITHOUT A MODEL" not in task:
                    return super().reply(task, turn)
                self.tasks[task.split('Its id must be "')[1].split('"')[0]] = task
                c = copy.deepcopy(EXAMPLE["concepts"][0])
                c = {k: c[k] for k in ("id", "title", "idea", "role", "terms", "recap")} | {
                    "understand": {k: c["understand"][k] for k in ("explanation", "quote", "quote_where")},
                    "activities": [{"id": "learn", "kind": "explain"},
                                   {"id": "chain", "kind": "order", "prompt": "Order the steps.", "items": ["Measure both parents", "Average them", "Compare with the child"], "explanation": "The mid-parent comes first."}]}
                if turn == 1:  # a first draft that keeps a model it shouldn't have
                    c["model"] = EXAMPLE["concepts"][0]["model"]
                return Reply(json.dumps(c), "end_turn")

        fp = NoModel()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        first = outline["concepts"][0]
        first.update(visual="none", why="It is a procedure, not a quantity", plans=[{"blocks": ["explain", "order"], "why": "Order the procedure."}])
        job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        self.assertEqual(job.status, "done", job.error)
        built = next(c for c in job.result["concepts"] if c["id"] == first["id"])
        self.assertNotIn("model", built)  # repaired: the model was removed
        self.assertEqual([a["kind"] for a in built["activities"]], ["explain", "order"])
        self.assertIn("explain → order", fp.tasks[first["id"]])
        self.assertEqual(list(L.check_lesson(job.result, SOURCE)), [])

    def test_concept_that_builds_on_another_reuses_its_model(self):
        fp = FakeProvider()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        self.assertTrue(outline["aha"])
        outline["concepts"].insert(1, {"id": "mid_parent_more", "title": "More about the mid-parent", "idea": "x", "visual": "bars", "builds_on": "mid_parent"})
        self.assertEqual(generate.check_outline(outline), [])
        job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        self.assertEqual(job.status, "done", job.error)
        more = next(c for c in job.result["concepts"] if c["id"] == "mid_parent_more")
        self.assertEqual(more["builds_on"], "mid_parent")
        self.assertIn('"father"', fp.tasks["mid_parent_more"])  # the base's finished model was in the prompt
        self.assertIn(EXAMPLE["intro"]["aha"], fp.tasks["why_regression"])  # the last concept builds to the aha
        self.assertEqual(job.result["intro"]["aha"], EXAMPLE["intro"]["aha"])
        outline["concepts"][1]["visual"] = "curves"
        self.assertTrue(any("same visual" in p for p in generate.check_outline(outline)))

    def test_concepts_come_after_what_they_rely_on(self):
        fp = FakeProvider()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        ids = [c["id"] for c in outline["concepts"]]
        self.assertEqual(generate.check_outline(outline, require_needs=True), [])
        swapped = copy.deepcopy(outline)
        swapped["concepts"].reverse()
        self.assertTrue(any("comes later" in p for p in generate.check_outline(swapped)))
        # A reviewed outline is tidied: each concept moves to just after what it relies on.
        self.assertEqual([c["id"] for c in generate.order_outline(swapped)["concepts"]], ids)
        self.assertEqual(generate.check_outline(swapped), [])
        # Removing a concept drops references to it, and the rest keeps the learner's order.
        removed = copy.deepcopy(outline)
        del removed["concepts"][0]
        self.assertEqual(generate.order_outline(removed)["concepts"][0]["needs"], [])
        self.assertEqual(generate.check_outline(removed), [])
        missing = copy.deepcopy(outline)
        del missing["concepts"][1]["needs"]
        self.assertTrue(any("'needs'" in p for p in generate.check_outline(missing, require_needs=True)))
        self.assertEqual(generate.check_outline(missing), [])  # outlines from before "needs" still build
        # Each concept is told what it relies on and not to lean on what comes later.
        job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        self.assertEqual([c["id"] for c in job.result["concepts"]], ids)
        self.assertIn("relies on 2]", fp.tasks[ids[2]])
        self.assertIn("never rely on an idea from a", fp.tasks[ids[2]])

    def test_progress_while_building_is_shown_but_not_saved(self):
        job, saved = generate.Job("build"), []
        job.on_change = lambda j: saved.append([dict(s) for s in j.steps])
        job.step("c1", "Concept 1: x", "active", "Drafting")
        job.update("c1", "active", "Drafting · writing, 1.2k characters so far", quiet=True)
        self.assertEqual(len(saved), 1)  # the tick isn't saved…
        self.assertEqual(job.snapshot()["steps"][0]["detail"], "Drafting · writing, 1.2k characters so far")  # …but is shown
        self.assertIn("now", job.snapshot())

        fp = FakeProvider()  # its first draft of regression_line has a bad quote; the fix passes
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        job = generate.Job("build")
        details = []
        job.on_change = lambda j: details.extend((s["detail"], tuple(s.get("problems") or ())) for s in j.steps if s["id"] == "regression_line")
        wait(generate.start(job, generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        fixing = [d for d in details if d[0].startswith("Fixing 1 problem")]
        self.assertTrue(fixing and fixing[0][1] and "quote" in fixing[0][1][0], details)  # what the checks found, shown while fixing
        final = next(s for s in job.snapshot()["steps"] if s["id"] == "regression_line")
        self.assertEqual((final["detail"], final["problems"]), ("Ready, after 1 round of fixes", []))

    def test_extract_json(self):
        self.assertEqual(generate.extract_json('Here:\n```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(generate.extract_json('{"a": {"b": 2}} trailing'), {"a": {"b": 2}})



OPENALEX = {"results": [
    {"display_name": "A small but famous paper", "publication_year": 2004, "cited_by_count": 2000, "relevance_score": 10,
     "authorships": [{"author": {"display_name": n}} for n in ("A", "B", "C", "D")],
     "primary_location": {"source": {"display_name": "Journal X"}},
     "best_oa_location": {"pdf_url": "https://pub.example/blocked.pdf", "landing_page_url": "https://doi.org/10.1/x"},
     "locations": [{"is_oa": True, "pdf_url": None, "landing_page_url": "https://archive.example/x"},
                   {"is_oa": True, "landing_page_url": "https://orcid.org/0000>"}],
     "abstract_inverted_index": {"Children": [0], "regress": [1], "to": [2], "the": [3], "mean": [4]}},
    {"display_name": "Very relevant, rarely cited", "publication_year": 2020, "cited_by_count": 0, "relevance_score": 12,
     "best_oa_location": {"pdf_url": "https://pub.example/b.pdf"}},
    {"display_name": "No open copy", "best_oa_location": None, "locations": []},
]}
ARXIV = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1234.5678v1</id>
<title>A small but famous paper</title><published>2004-01-01</published><summary>dup</summary></entry>
<entry><id>http://arxiv.org/abs/2222.0001v2</id><title>A preprint</title><published>2021-05-01</published>
<author><name>Z</name></author><summary>About   regression to the mean.</summary></entry>
<entry><id>http://arxiv.org/abs/3333.0001v1</id><title>Coresets for federated learning</title><published>2022-01-01</published>
<summary>Nothing about the search.</summary></entry></feed>"""
WIKI = {"query": {"search": [{"title": "Regression toward the mean", "snippet": "In <span>statistics</span> &amp; more"}]}}


class TermsProvider(Provider):
    """The learner's provider as search uses it: asked once for article titles."""
    id, name = "fake", "Fake"

    def __init__(self, terms=(), error=None, wait=False):
        self.terms, self.error, self.wait, self.asked = list(terms), error, wait, []

    def available(self):
        return True, ""

    def conversation(self, system, document):
        provider = self

        class Conv:
            def send(self, text, cancelled=None, on_progress=None):
                provider.asked.append((system, document, text))
                if provider.wait:
                    cancelled.wait(5)
                    raise llm.ProviderError("Cancelled.")
                if provider.error:
                    raise provider.error
                return Reply(json.dumps({"terms": provider.terms}), "end_turn")
        return Conv()


class SearchTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        self.readable = patch.object(ingest, "first_readable", side_effect=lambda urls, **kw: ingest.Paper(text="word " * 1000, title="T", url=urls[0], kind="html"))
        self.readable.start()
        self.addCleanup(self.readable.stop)
        search._cache.clear()
        search._fields.clear()
        self.urls = []
        self.orig = search._get

        def fake(url, retry=True):
            self.urls.append(url)
            if "openalex" in url:
                return json.dumps(OPENALEX).encode()
            if "arxiv" in url:
                return ARXIV
            if "europepmc" in url:
                return json.dumps({"resultList": {"result": []}}).encode()
            if "libretexts" in url:
                return b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
            if "plato.stanford.edu" in url:
                return b"<html></html>"
            if "titles=" in url:
                return json.dumps(self.titles).encode()
            return json.dumps(WIKI).encode()

        search._get = fake

    def tearDown(self):
        search._get = self.orig

    def test_overview_first_then_papers_then_new_preprints(self):
        r = search.search("  regression   to the mean ")
        self.assertEqual(r["query"], "regression to the mean")
        self.assertEqual([x["source"] for x in r["results"]], ["Wikipedia", "OpenAlex", "OpenAlex", "arXiv"])
        wiki, famous, rare, pre = r["results"]
        self.assertEqual(wiki["url"], "https://en.wikipedia.org/wiki/Regression_toward_the_mean")
        self.assertEqual(wiki["summary"], "In statistics & more")
        self.assertEqual(famous["title"], "A small but famous paper")  # citations outweigh a little relevance
        self.assertEqual(famous["authors"], "A, B, C et al.")
        self.assertEqual(famous["summary"], "Children regress to the mean")
        # Every open copy, full text before DOI landing pages, junk links dropped.
        # The arXiv copy of the same paper adds its link instead of being listed twice.
        self.assertEqual(famous["urls"], ["https://pub.example/blocked.pdf", "https://archive.example/x", "https://doi.org/10.1/x", "https://arxiv.org/abs/1234.5678v1"])
        self.assertEqual(pre["url"], "https://arxiv.org/abs/2222.0001v2")  # the duplicate preprint was dropped
        # and so was the one whose title and abstract never mention the search
        self.assertEqual(r["unavailable"], [])
        self.assertTrue(all("query" not in u or "regression" in u for u in self.urls))

    def jev_answers(self, scores, roles=None):
        """A fake Jev that judges each result by its title: relevance on Jev's 0 to 4 scale, and a role."""
        def ask(state, questions, timeout):
            self.jev_state, self.jev_questions = state, questions
            out = {"_model": "jev-test"}
            for r in state["results"]:
                out[f"r{r['n']}_relevance"] = {"score": scores.get(r["title"], 2.0)}
                out[f"r{r['n']}_role"] = {"choice": (roles or {}).get(r["title"], "study")}
            return out
        return [patch.object(jev, "available", return_value=True), patch.object(jev, "ask", side_effect=ask)]

    def test_jev_orders_each_group_and_picks_the_recommendations(self):
        plain = [x["title"] for x in search._search("regression to the mean")["results"] if x["source"] == "OpenAlex"]
        self.assertEqual(plain, ["A small but famous paper", "Very relevant, rarely cited"])  # citations lead without Jev
        for p in self.jev_answers({"A small but famous paper": 1.0, "Very relevant, rarely cited": 3.5}):
            p.start()
            self.addCleanup(p.stop)
        r = search._search("regression to the mean")
        papers = [x for x in r["results"] if x["source"] == "OpenAlex"]
        self.assertEqual([x["title"] for x in papers], ["Very relevant, rarely cited", "A small but famous paper"])
        self.assertEqual(r["results"][0]["source"], "Wikipedia")  # the overview still leads a concept search
        self.assertTrue(papers[0]["recommended"])
        self.assertFalse(papers[1]["recommended"])  # 2 of 5: listed, but not recommended
        self.assertEqual(papers[1]["judged"], {"relevance": 2.0, "role": "study"})
        self.assertEqual(len(self.jev_questions), 2 * len(self.jev_state["results"]))
        self.assertEqual(self.jev_state["search"], "regression to the mean")

    def test_an_off_topic_result_is_never_recommended(self):
        for p in self.jev_answers({"A small but famous paper": 4.0}, {"A small but famous paper": "off_topic"}):
            p.start()
            self.addCleanup(p.stop)
        famous = next(x for x in search._search("regression to the mean")["results"] if x["title"] == "A small but famous paper")
        self.assertFalse(famous["recommended"])

    def test_a_search_jev_cannot_rank_fails(self):
        with patch.object(jev, "ask", side_effect=jev.JevError("Jev answered 529")):
            with self.assertRaisesRegex(search.SearchError, "Couldn't rank the results just now"):
                search._search("regression to the mean")
        with patch.object(jev, "ask", return_value={"_model": "jev-test"}), patch.object(search.logs, "report"):
            with self.assertRaisesRegex(search.SearchError, "^Couldn't rank the results just now. Try again in a moment.$"):  # a reply missing its answers
                search._search("regression to the mean")

    def test_no_search_runs_without_jev(self):
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}), patch.object(search, "_search") as run:
            with self.assertRaisesRegex(search.SearchError, "TYPESAFE_API_KEY"):
                search.search("a topic nobody has searched for")
        run.assert_not_called()

    # What the learner's provider names, and the Wikipedia articles those names land on.
    def pages(self, *titles, redirects=(), disambiguation=(), missing=()):
        self.titles = {"query": {
            "redirects": [{"from": a, "to": b} for a, b in redirects],
            "pages": [{"title": t, "extract": f"About {t.lower()}."} for t in titles]
                     + [{"title": t, "pageprops": {"disambiguation": ""}} for t in disambiguation]
                     + [{"title": t, "missing": True} for t in missing]}}

    def test_the_learners_provider_names_what_to_look_up(self):
        named = ["Regression toward the mean", "Mean", "Correlation", "Heredity", "Francis Galton"]
        self.pages("Regression toward the mean", "Arithmetic mean", "Correlation", redirects=[("Mean", "Arithmetic mean")],
                   disambiguation=["Heredity"], missing=["Francis Galton"])
        provider = TermsProvider(named)
        r = search.search("Why are tall parents' children usually shorter than them?", "advanced", provider)
        system, document, task = provider.asked[0]
        self.assertIn("Why are tall parents' children usually shorter than them?", document)
        self.assertIn("Advanced: has studied or works in the field", task)
        self.assertIn(search.TERMS_STEER["advanced"], task)
        self.assertEqual(r["plan"]["terms"], named)
        # Titles are looked up in one request; a disambiguation page or a missing title is searched for instead.
        self.assertEqual(sum("titles=" in u for u in self.urls), 1)
        self.assertEqual([(a["title"], a["how"]) for a in r["plan"]["articles"]],
                         [("Regression toward the mean", "exact"), ("Arithmetic mean", "exact"), ("Correlation", "exact")])
        wiki = [x for x in r["results"] if x["source"] == "Wikipedia"]
        # The article the question itself finds stays the overview; the others are prerequisites, recommended.
        self.assertEqual([(x["title"], bool(x.get("prerequisite"))) for x in wiki],
                         [("Regression toward the mean", False), ("Arithmetic mean", True), ("Correlation", True)])
        self.assertTrue(all(x["recommended"] for x in wiki))
        self.assertEqual(wiki[1]["recommendation"], "Explains something the idea builds on")
        self.assertEqual(wiki[1]["summary"], "About arithmetic mean.")
        # Wikipedia's API already showed these are articles, so they aren't downloaded to check they can be read.
        read = [call.args[0][0] for call in ingest.first_readable.call_args_list]
        self.assertNotIn(wiki[1]["url"], read)
        self.assertIn(wiki[0]["url"], read)

    def test_a_question_is_about_an_idea_however_long(self):
        self.assertEqual(search.query_kind("Why do people vote against their own economic interests?"), "concept")
        self.assertEqual(search.query_kind("Can you know something just by luck"), "concept")
        self.assertEqual(search.query_kind("The nature of the firm and the theory of transaction costs"), "paper")
        self.assertEqual(search.query_kind("Why did Galton 1886 find regression?"), "paper")  # a year names a paper

    def test_at_most_four_prerequisites_are_recommended(self):
        named = ["Mean", "Variance", "Correlation", "Heredity", "Normal distribution"]
        self.pages(*named)
        r = search.search("regression to the mean", "beginner", TermsProvider(named))
        prerequisites = [x for x in r["results"] if x.get("prerequisite")]
        self.assertEqual(len(prerequisites), 5)
        self.assertEqual(sum(x["recommended"] for x in prerequisites), 4)

    def need_answers(self, need, relation=None, missing=None):
        """A fake Jev that rates each prerequisite's need (Jev's 0 to 4) and relation by title, and a subject
        no article was found for by name; everything else as fakejev does."""
        def ask(state, questions, timeout):
            out = fakejev.answer(state, questions, timeout)
            self.judged_state, self.judged_questions = state, questions
            for r in state.get("results", []):
                if f"r{r['n']}_need" in questions:
                    out[f"r{r['n']}_need"] = {"score": need.get(r["title"], 0.0)}
                    out[f"r{r['n']}_relation"] = {"choice": (relation or {}).get(r["title"], "prerequisite")}
            for m in state.get("not_found", []):
                out[f"m{m['m']}_need"] = {"score": (missing or {}).get(m["title"], 0.0)}
            return out
        p = patch.object(jev, "ask", side_effect=ask)
        p.start()
        self.addCleanup(p.stop)

    def test_prerequisites_are_chosen_by_how_much_the_learner_needs_them(self):
        named = ["Mean", "Variance", "Correlation", "Heredity", "Normal distribution", "Francis Galton"]
        self.pages(*named)
        self.need_answers({"Mean": 4, "Variance": 3, "Correlation": 3.5, "Heredity": 2.5, "Normal distribution": 1, "Francis Galton": 3},
                          {"Francis Galton": "unrelated"})
        r = search.search("regression to the mean", "advanced", TermsProvider(named))
        chosen = [x["title"] for x in r["results"] if x.get("prerequisite") and x["recommended"]]
        self.assertEqual(chosen, ["Mean", "Correlation", "Variance", "Heredity"])  # most needed first, listed in that order
        self.assertEqual([s["title"] for s in r["graph"]["subjects"] if s["recommended"]], chosen)
        self.assertFalse(next(s for s in r["graph"]["subjects"] if s["title"] == "Francis Galton")["recommended"])
        self.assertEqual(r["graph"]["subjects"][0]["need"], 5.0)  # on the 1 to 5 scale, like relevance
        self.assertIn("Advanced: has studied or works in the field", self.judged_state["level"])
        self.assertNotIn("r1_need", self.judged_questions)  # only prerequisites are rated for need
        self.assertNotIn("explains", next(q for k, q in self.judged_questions.items() if k.endswith("_relation"))["criteria"])

    def test_a_prerequisite_needed_too_little_is_listed_but_not_recommended(self):
        named = ["Mean", "Variance", "Correlation", "Heredity", "Normal distribution"]
        self.pages(*named)
        self.need_answers({"Mean": 1.9, "Variance": 4})
        r = search.search("regression to the mean", "beginner", TermsProvider(named))
        self.assertEqual([x["title"] for x in r["results"] if x.get("prerequisite") and x["recommended"]], ["Variance"])
        self.assertEqual(len([x for x in r["results"] if x.get("prerequisite")]), 5)

    def test_brought_sources_are_rated_for_what_they_build_on(self):
        named = ["Mean", "Variance", "Correlation", "Galton board", "Heredity"]
        self.pages("Mean", "Variance", "Correlation", "Heredity", missing=["Galton board"])
        provider = TermsProvider(named)
        seen = {}

        def ask(state, questions, timeout):
            seen.update(state=state, questions=questions)
            need = {"Mean": 3.5, "Variance": 2.0, "Correlation": 3.0, "Heredity": 1.0}
            out = {"_model": "jev-test"}
            for x in state["subjects"]:
                out[f"s{x['n']}_need"] = {"score": need[x["title"]]}
                out[f"s{x['n']}_relation"] = {"choice": "unrelated" if x["title"] == "Heredity" else "prerequisite"}
            for m in state.get("not_found", []):
                out[f"m{m['m']}_need"] = {"score": 3.4}
            return out
        sources = [{"title": "Regression towards Mediocrity", "text": "Galton measured " * 500}]
        with patch.object(jev, "ask", side_effect=ask), patch.object(search, "wikipedia", return_value=[]):
            found = fakejev.REAL_SOURCE_SUBJECTS(provider, sources, "beginner", ["statistics"])
        _, document, task = provider.asked[0]
        self.assertIn("Regression towards Mediocrity", document)
        self.assertLessEqual(document.count("Galton measured"), search.SOURCE_OPENING // len("Galton measured ") + 1)
        self.assertIn("that the sources themselves take for granted", task)
        self.assertIn("Beginner: no background in this field", task)
        self.assertIn("Statistics & probability", task)
        self.assertEqual([(x["title"], x["need"]) for x in found["subjects"]], [("Mean", 4.5), ("Correlation", 4.0), ("Variance", 3.0)])
        self.assertEqual(found["subjects"][0]["url"], "https://en.wikipedia.org/wiki/Mean")
        self.assertEqual(found["not_covered"], ["Galton board"])
        self.assertIn("to follow these sources", seen["questions"]["s1_need"]["instructions"])

    def test_a_check_of_brought_sources_jev_cannot_make_fails(self):
        self.pages("Mean", "Variance", "Correlation", "Heredity", "Normal distribution")
        with patch.object(jev, "ask", side_effect=jev.JevError("the checking service answered 529")):
            with self.assertRaisesRegex(search.SearchError, "^Couldn't work out what your sources build on just now"):
                fakejev.REAL_SOURCE_SUBJECTS(TermsProvider(["Mean", "Variance", "Correlation", "Heredity", "Normal distribution"]),
                                             [{"title": "T", "text": "x"}], "beginner", None)

    def test_when_nothing_would_be_recommended_the_most_needed_prerequisites_are(self):
        named = ["Mean", "Variance", "Correlation", "Heredity", "Normal distribution"]
        self.pages(*named)
        self.need_answers({"Mean": 1.2, "Variance": 1.5, "Correlation": 1.4, "Heredity": 1.1, "Normal distribution": 1.9},
                          {"Normal distribution": "unrelated"})
        with patch.object(search, "RECOMMEND_AT", 9):  # and no other result is close enough to the question
            r = search.search("regression to the mean", "beginner", TermsProvider(named))
        self.assertEqual([x["title"] for x in r["results"] if x["recommended"]], ["Variance", "Correlation"])

    def test_a_needed_subject_no_article_was_found_for_is_not_covered(self):
        named = ["Mean", "Variance", "Correlation", "Galton board", "Reversion"]
        self.pages("Mean", "Variance", "Correlation", missing=["Galton board", "Reversion"])
        self.need_answers({"Mean": 3}, missing={"Galton board": 3.2, "Reversion": 1})
        with patch.object(search, "wikipedia", return_value=[]):  # nor found by searching for it
            r = search.search("regression to the mean", "beginner", TermsProvider(named))
        self.assertEqual([m["title"] for m in self.judged_state["not_found"]], ["Galton board", "Reversion"])
        self.assertEqual(r["graph"]["not_covered"], ["Galton board"])

    def test_a_reply_without_need_fails_the_search(self):
        self.pages("Mean", "Variance", "Correlation", "Heredity", "Normal distribution")

        def ask(state, questions, timeout):
            out = fakejev.answer(state, questions, timeout)
            return {k: v for k, v in out.items() if not k.endswith("_need")}
        with patch.object(jev, "ask", side_effect=ask), patch.object(search.logs, "report"):
            with self.assertRaisesRegex(search.SearchError, "Couldn't rank the results"):
                search.search("regression to the mean", "beginner", TermsProvider(["Mean", "Variance", "Correlation", "Heredity", "Normal distribution"]))

    def test_each_level_is_searched_and_remembered_on_its_own(self):
        self.pages("Mean", "Variance", "Correlation", "Heredity", "Normal distribution")
        provider = TermsProvider(["Mean", "Variance", "Correlation", "Heredity", "Normal distribution"])
        search.search("regression to the mean", "beginner", provider)
        search.search("Regression to the mean", "beginner", provider)
        self.assertEqual(len(provider.asked), 1)  # answered from the cache, with no second call
        search.search("regression to the mean", "advanced", provider)
        self.assertEqual(len(provider.asked), 2)
        self.assertIsNotNone(search.cached("regression to the mean", "advanced"))

    def test_a_search_for_an_identifier_names_nothing(self):
        provider = TermsProvider(["Anything"] * 5)
        r = search.search("doi 10.1093/ije/dyh299", "beginner", provider)
        self.assertEqual((provider.asked, r["plan"]["terms"]), ([], []))

    def field_answers(self, probs, span="one", second=None):
        """A fake Jev that places a question in a field, and judges search results as fakejev does."""
        self.field_asks = []

        def ask(state, questions, timeout):
            if "second" in questions:
                return {"_model": "jev-test", "second": {"choice": second}}
            if "field" not in questions:
                self.judged_state, self.judged_questions = state, questions
                return fakejev.answer(state, questions, timeout)
            self.field_asks.append(state)
            return {"_model": "jev-test", "field": {"choice": max(probs, key=probs.get), "probabilities": probs},
                    "span": {"choice": span}}
        p = patch.object(jev, "ask", side_effect=ask)
        p.start()
        self.addCleanup(p.stop)

    def test_the_question_is_placed_in_a_field_before_anything_is_looked_up(self):
        self.field_answers({"psychology": .6, "economics": .3, "sociology_anthropology": .1})
        self.pages("Conformity", "Social proof", "Herd behavior", "Information cascade", "Peer pressure")
        provider = TermsProvider(["Conformity", "Social proof", "Herd behavior", "Information cascade", "Peer pressure"])
        r = search.search("Why do people follow the herd?", "beginner", provider)
        self.assertEqual((r["field"]["ids"], r["field"]["chosen_by"], r["plan"]["field"]), (["psychology"], "jev", ["psychology"]))
        self.assertEqual([a["id"] for a in r["field"]["alternatives"]], ["economics", "sociology_anthropology"])
        self.assertEqual(self.field_asks, [{"question": "Why do people follow the herd?"}])
        self.assertIn("Its field: Psychology (Behaviour and mind", provider.asked[0][2])
        self.assertIn("Psychology (Behaviour and mind", self.judged_state["field"])  # Jev ranks the results in that field

    def test_a_question_needing_two_fields_asks_for_what_connects_them(self):
        self.field_answers({"physics_astronomy": .9, "chemistry": .1}, "both", second="psychology")
        self.pages("Pressure", "Sound", "Shock wave", "Startle response", "Balloon")
        provider = TermsProvider(["Pressure", "Sound", "Shock wave", "Startle response", "Balloon"])
        r = search.search("Why do balloons pop loudly and scare kids?", "beginner", provider)
        self.assertEqual(r["field"]["ids"], ["physics_astronomy", "psychology"])
        self.assertIn("It needs both fields: include what connects them", provider.asked[0][2])
        self.assertNotIn("Psychology", self.judged_state["field"])  # results are ranked in the main field only
        relation = next(q for k, q in self.judged_questions.items() if k.endswith("_relation"))
        self.assertIn("explains", relation["criteria"])  # a subject can be what connects the two fields

    def test_a_field_the_learner_chose_is_searched_and_cached_on_its_own(self):
        self.field_answers({"chemistry": .6, "religion": .3, "physics_astronomy": .1})
        self.pages("Mercury (element)", "Metal", "Liquid", "Toxicity", "Thermometer")
        provider = TermsProvider(["Mercury (element)", "Metal", "Liquid", "Toxicity", "Thermometer"])
        search.search("Mercury", "beginner", provider)
        religion = categorize.chosen_field(["religion"])
        r = search.search("Mercury", "beginner", provider, field=religion)
        self.assertEqual(len(self.field_asks), 1)  # the learner's choice needs no Jev pick
        self.assertEqual((r["field"]["ids"], r["field"]["chosen_by"]), (["religion"], "learner"))
        self.assertIn("Religion & theology", provider.asked[1][2])
        self.assertEqual(len(provider.asked), 2)  # not answered from the search Jev placed in chemistry
        self.assertEqual(search.cached("Mercury", "beginner", religion)["field"]["ids"], ["religion"])
        self.assertEqual(search.cached("Mercury", "beginner")["field"]["ids"], ["chemistry"])
        self.assertEqual(search.field_of("mercury", ask=False)["ids"], ["chemistry"])  # remembered, not asked again
        self.assertEqual(len(self.field_asks), 1)

    def test_a_question_jev_cannot_place_stops_the_search(self):
        with patch.object(jev, "ask", side_effect=jev.JevError("the checking service answered 529")), patch.object(search, "_search") as run:
            with self.assertRaisesRegex(search.SearchError, "^Couldn't tell which field the question belongs to"):
                search.search("Mercury", "beginner", TermsProvider(["Mercury"] * 5))
        run.assert_not_called()

    def test_a_provider_that_names_nothing_useful_or_fails_stops_the_search(self):
        with self.assertRaisesRegex(search.SearchError, "^Fake didn't say what to look up"):
            search.search("regression to the mean", "beginner", TermsProvider(["Mean", "Variance"]))
        with self.assertRaisesRegex(search.SearchError, "^Fake says you've hit a usage limit.$"):
            search.search("regression to the mean", "beginner", TermsProvider(error=llm.ProviderError("Fake says you've hit a usage limit.")))
        slow = TermsProvider(["Mean"] * 5, wait=True)
        with patch.object(search, "TERMS_TIMEOUT", 0.05):
            with self.assertRaisesRegex(search.SearchError, "^Fake took too long to work out what to look up"):
                search.search("regression to the mean", "beginner", slow)

    def test_when_wikipedia_cant_look_the_titles_up_the_search_still_runs_uncached(self):
        def failing(url, retry=True):
            if "titles=" in url:
                raise TimeoutError()
            return self.orig_fake(url)
        self.orig_fake, search._get = search._get, failing
        r = search.search("regression to the mean", "beginner", TermsProvider(["Mean", "Variance", "Correlation", "Heredity", "Galton"]))
        self.assertIn("Wikipedia", r["unavailable"])
        self.assertEqual(r["results"][0]["title"], "Regression toward the mean")
        self.assertIsNone(search.cached("regression to the mean", "beginner"))

    def test_a_service_that_fails_is_reported_not_fatal(self):
        def failing(url, retry=True):
            if "arxiv" in url:
                raise TimeoutError()
            return self.orig_fake(url)
        self.orig_fake = search._get
        search._get = failing
        r = search.search("regression to the mean")
        self.assertEqual(r["unavailable"], ["arXiv"])
        self.assertEqual(len(r["results"]), 3)

    def test_closeness_to_the_search(self):
        q = "free will"
        self.assertEqual(search.match(q, "Is Belief in Free Will a Cultural Universal?"), 3)  # the phrase
        self.assertEqual(search.match(q, "Will we ever be free?"), 2)  # every word in the title
        self.assertEqual(search.match(q, "Determinism", "Whether the will is free"), 1)  # with the abstract
        self.assertEqual(search.match(q, "Model-free control", "Controllers without a model"), 0)
        self.assertEqual(search.match("counterfactual causation", "Counterfactual Theories of Causal Explanation"), 2)  # by stem
        q = "Vaswani et al attention is all you need 2017"  # the author counts, the year and "et al" don't
        self.assertEqual(search.match(q, "Attention Is All You Need", "Ashish Vaswani, Noam Shazeer"), 1)
        self.assertEqual(search.match(q, "Patches Are All You Need?", "Trockman, Kolter"), 0)

    def test_a_paper_search_looks_up_identifiers_and_drops_years(self):
        self.assertEqual(search.search_words("Vaswani et al. attention is all you need 2017"), "Vaswani attention is all you need")
        search.search("doi 10.1093/ije/dyh299")
        self.assertTrue(any(u.startswith("https://api.openalex.org/works/doi:10.1093/ije/dyh299") for u in self.urls), self.urls)
        self.urls.clear()
        search.search("arXiv 1706.03762v7")
        self.assertTrue(any("id_list=1706.03762v7" in u for u in self.urls), self.urls)
        self.urls.clear()
        search.search("Galton 1886 regression towards mediocrity")
        sent = [urllib.parse.unquote_plus(u) for u in self.urls if "openalex" in u or "arxiv" in u]
        self.assertTrue(sent and not any("1886" in u for u in sent), sent)

    def test_openalex_gets_the_server_key_only_when_it_has_one(self):
        with patch.dict(os.environ, {"OPENALEX_API_KEY": ""}):
            search.search("regression to the mean")
        self.assertTrue(self.urls and not any("api_key" in u for u in self.urls), self.urls)
        self.urls.clear()
        search._cache.clear()
        with patch.dict(os.environ, {"OPENALEX_API_KEY": "test-openalex-key"}):
            search.search("regression to the mean")
        sent = [u for u in self.urls if "api_key=test-openalex-key" in u]
        self.assertTrue(sent and all(u.startswith("https://api.openalex.org/") for u in sent), self.urls)

    def test_bad_queries(self):
        with self.assertRaises(search.SearchError):
            search.search("   ")
        with self.assertRaises(search.SearchError):
            search.search("x" * 201)

    def test_a_result_gets_a_time_budget_for_all_its_links(self):
        tried = []

        def slow(u, timeout):
            tried.append((u, timeout))
            time.sleep(.6)
            raise ingest.IngestError("The site took too long to respond.")

        with patch.object(ingest, "from_url", side_effect=slow):
            with self.assertRaisesRegex(ingest.IngestError, "too slow"):
                server._first_readable(["https://a/x", "https://b/y", "https://c/z"], timeout=5, budget=1.5)
        self.assertEqual([u for u, _ in tried], ["https://a/x"])  # under a second left, so b and c were skipped
        self.assertLessEqual(tried[0][1], 1.5)

    def test_first_readable_copy_wins_and_short_pages_are_skipped(self):
        orig = ingest.from_url
        pages = {"https://a/blocked.pdf": None, "https://b/abstract": "short " * 50, "https://c/full": "word " * 2000}

        def fake(u):
            if pages[u] is None:
                raise ingest.IngestError("The site answered 403 Forbidden.")
            return ingest.Paper(text=pages[u], title="T", url=u, kind="html", pages=0)

        ingest.from_url = fake
        try:
            self.assertEqual(server._first_readable(list(pages)).url, "https://c/full")
            with self.assertRaisesRegex(ingest.IngestError, "403"):
                server._first_readable(["https://a/blocked.pdf"])
            with self.assertRaisesRegex(ingest.IngestError, "short summary"):
                server._first_readable(["https://a/blocked.pdf", "https://b/abstract"])
        finally:
            ingest.from_url = orig

    def test_only_public_addresses_are_fetched_even_after_a_redirect(self):
        with self.assertRaisesRegex(ingest.IngestError, "public web addresses"):
            ingest.from_url("http://127.0.0.1:9/paper.pdf")
        with self.assertRaisesRegex(ingest.IngestError, "public web addresses"):
            ingest.from_url("http://169.254.169.254/latest/meta-data/")

        class Redirect(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:9/secret")
                self.end_headers()

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        orig = ingest._public_addresses

        def pretend_public(host, port):  # "pub.test" stands for a public site that redirects inward
            if host == "pub.test":
                return socket.getaddrinfo("127.0.0.1", port, type=socket.SOCK_STREAM)
            return orig(host, port)

        ingest._public_addresses = pretend_public
        try:
            with self.assertRaisesRegex(ingest.IngestError, "public web addresses"):
                ingest.from_url(f"http://pub.test:{httpd.server_address[1]}/paper")
        finally:
            ingest._public_addresses = orig
            httpd.shutdown()
            httpd.server_close()


class FakeAPI(BaseHTTPRequestHandler):
    """A stand-in for an OpenAI-compatible API. Records each call."""

    calls: list = []

    def log_message(self, *args):
        pass

    def _reply(self, status, obj):
        raw = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self):
        if self.headers.get("Authorization") != "Bearer good-key":
            self._reply(401, {"error": {"message": "Incorrect API key provided"}})
            return False
        return True

    def do_GET(self):
        if self._authorized():
            self._reply(200, {"data": [{"id": "gpt-6.1-sol"}, {"id": "text-embedding-3"}, {"id": "glm-5.3", "context_length": 200000}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAPI.calls.append({"path": self.path, "body": body, "headers": {k.lower(): v for k, v in self.headers.items()}})
        if not self._authorized():
            return
        last = body["messages"][-1]["content"]
        if "FAIL" in last:
            return self._reply(429, {"error": {"message": "quota exceeded"}})
        if "LONG" in last:
            return self._reply(400, {"error": {"message": "too many tokens", "code": "context_length_exceeded"}})
        turn = sum(m["role"] == "assistant" for m in body["messages"]) + 1
        finish = "length" if "CUT" in last else "stop"
        text = json.dumps({"turn": turn, "model": body["model"]})
        if body.get("stream") and "STREAM" in last:  # the reply in pieces, as an OpenAI-compatible API streams it
            chunks = [{"choices": [{"delta": {"reasoning_content": "hmm"}}]}] + \
                     [{"choices": [{"delta": {"content": text[i:i + 5]}}]} for i in range(0, len(text), 5)] + \
                     [{"choices": [{"delta": {}, "finish_reason": finish}]}]
            raw = ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            return self.wfile.write(raw)
        self._reply(200, {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}]})


class HTTPProviderTests(unittest.TestCase):
    """Runs the real provider against FakeAPI."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.info = llm.ProviderInfo("openai", "OpenAI", f"http://127.0.0.1:{cls.httpd.server_address[1]}/v1", "gpt-6.1-sol", "")

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        FakeAPI.calls.clear()
        self.p = llm.HTTPProvider(self.info, "good-key")

    def test_conversation_resends_the_history(self):
        self.assertEqual(self.p.available(), (True, ""))
        conv = self.p.conversation("SYSTEM", "<paper>text</paper>")
        r1 = conv.send("task")
        r2 = conv.send("repair")
        self.assertEqual(json.loads(r1.text), {"turn": 1, "model": "gpt-6.1-sol"})
        self.assertEqual(json.loads(r2.text)["turn"], 2)
        self.assertEqual(r1.stop_reason, "end_turn")
        first, second = (c["body"]["messages"] for c in FakeAPI.calls)
        self.assertEqual([m["role"] for m in first], ["system", "user", "user"])
        self.assertEqual(first[1]["content"], "<paper>text</paper>")
        self.assertEqual([m["role"] for m in second], ["system", "user", "user", "assistant", "user"])
        self.assertEqual(second[-1]["content"], "repair")
        self.assertNotIn("tools", FakeAPI.calls[0]["body"])
        self.assertEqual(conv.send("CUT").stop_reason, "max_tokens")

    def test_opencode_gets_one_session_id_per_conversation(self):
        oc = llm.HTTPProvider(llm.ProviderInfo("opencode-go", "OpenCode Go", self.info.base, "glm-5.3", "", "x-opencode-session"), "good-key")
        first, second = oc.conversation("S", "<paper>x</paper>"), oc.conversation("S", "<paper>x</paper>")
        first.send("draft")
        first.send("repair")
        second.send("draft")
        ids = [c["headers"].get("x-opencode-session") for c in FakeAPI.calls]
        self.assertTrue(ids[0] and ids[0] == ids[1], ids)  # a draft and its repair share one session…
        self.assertNotEqual(ids[1], ids[2])  # …and the next conversation gets its own
        self.assertTrue(all(c["headers"]["user-agent"].startswith("Lemma/") for c in FakeAPI.calls))  # identifies itself
        FakeAPI.calls.clear()
        self.p.conversation("S", "<paper>x</paper>").send("draft")  # OpenAI doesn't ask for it, so it isn't sent
        self.assertNotIn("x-opencode-session", FakeAPI.calls[0]["headers"])
        self.assertEqual(llm.PROVIDERS["opencode-go"].session_header, "x-opencode-session")

    def test_a_streamed_reply_reports_its_progress(self):
        conv = self.p.conversation("S", "<paper>x</paper>")
        seen = []
        r = conv.send("STREAM please", on_progress=lambda phase, chars: seen.append((phase, chars)))
        self.assertEqual(json.loads(r.text), {"turn": 1, "model": "gpt-6.1-sol"})  # reassembled from its pieces
        self.assertTrue(FakeAPI.calls[-1]["body"]["stream"])
        self.assertEqual(seen[0], ("thinking", 0))
        self.assertEqual(seen[-1], ("writing", len(r.text)))
        self.assertEqual(conv.send("STREAM CUT").stop_reason, "max_tokens")
        self.assertEqual(json.loads(conv.send("plain").text)["turn"], 3)  # a provider that won't stream still works

    def test_models_and_errors(self):
        self.assertEqual([m["id"] for m in self.p.models()], ["glm-5.3", "gpt-6.1-sol"])  # embeddings left out
        conv = self.p.conversation("S", "<paper>x</paper>")
        with self.assertRaisesRegex(llm.ProviderError, "quota exceeded"):
            conv.send("FAIL please")
        with self.assertRaisesRegex(llm.ProviderError, "too long for gpt-6.1-sol"):
            conv.send("LONG")
        with self.assertRaisesRegex(llm.ProviderError, "didn.t accept this key"):
            llm.HTTPProvider(self.info, "bad-key").models()

    def test_missing_key_or_unknown_provider(self):
        ok, msg = llm.make_provider("openai").available()
        self.assertFalse(ok)
        self.assertIn("Add your OpenAI key", msg)
        self.assertEqual(llm.make_provider("opencode-go", "k", "glm-5.3").model, "glm-5.3")
        self.assertEqual(llm.make_provider(None, "k").id, "opencode-go")
        with self.assertRaises(llm.ProviderError):
            llm.make_provider("codex", "k")


def fake_jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


class FakeChatGPT(BaseHTTPRequestHandler):
    """A stand-in for the ChatGPT Codex backend. Records each call."""

    calls: list = []

    def log_message(self, *args):
        pass

    def _send(self, status, raw, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send(200, json.dumps({"models": [{"slug": "gpt-6.1-sol", "display_name": "GPT-6.1-Sol", "visibility": "list", "context_window": 272000},
                                               {"slug": "hidden", "visibility": "hide"}]}).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeChatGPT.calls.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        last = body["input"][-1]["content"][0]["text"]
        if "LIMIT" in last:
            return self._send(429, json.dumps({"detail": "usage limit reached"}).encode())
        if "FAIL" in last:
            events = [{"type": "response.failed", "response": {"error": {"message": "model overloaded"}}}]
        else:
            turn = sum(m["role"] == "assistant" for m in body["input"]) + 1
            out = [{"type": "reasoning", "summary": []},
                   {"type": "message", "content": [{"type": "output_text", "text": json.dumps({"turn": turn, "model": body["model"]})}]}]
            events = [{"type": "response.created"}, {"type": "response.output_text.delta", "delta": "{"},
                      {"type": "response.completed", "response": {"output": out}}]
        self._send(200, "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode(), "text/event-stream")


class ChatGPTTests(unittest.TestCase):
    """The subscription provider, against FakeChatGPT and a stubbed token endpoint."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeChatGPT)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.backend = chatgpt.BACKEND
        chatgpt.BACKEND = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        chatgpt.BACKEND = cls.backend
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        FakeChatGPT.calls.clear()
        self.token_calls = []
        self.orig_token = chatgpt._token_request

        def fake_token(fields):
            self.token_calls.append(fields)
            n = len(self.token_calls)
            return {"access_token": fake_jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-1"}, "n": n}),
                    "refresh_token": f"refresh-{n}", "expires_in": 3600, "id_token": fake_jwt({"email": "me@example.com"})}

        chatgpt._token_request = fake_token

    def tearDown(self):
        chatgpt._token_request = self.orig_token
        chatgpt._stop_listening()
        chatgpt.sign_out()

    def sign_in(self):
        url = chatgpt.start_sign_in()
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        return q

    def callback(self, query):
        c = http.client.HTTPConnection("127.0.0.1", chatgpt.CALLBACK_PORT, timeout=10)
        c.request("GET", "/auth/callback?" + urllib.parse.urlencode(query))
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    def test_sign_in_with_pkce_then_refresh(self):
        self.assertFalse(chatgpt.status()["signed_in"])
        q = self.sign_in()
        self.assertEqual((q["client_id"], q["redirect_uri"], q["code_challenge_method"]), (chatgpt.CLIENT_ID, chatgpt.REDIRECT_URI, "S256"))
        self.assertTrue(chatgpt.status()["waiting"])
        self.assertEqual(self.callback({"code": "c", "state": "wrong"}), 400)  # someone else's redirect is ignored
        self.assertEqual(self.callback({"code": "the-code", "state": q["state"]}), 200)
        verifier = self.token_calls[0]["code_verifier"]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, q["code_challenge"])
        self.assertEqual(self.token_calls[0]["code"], "the-code")
        st = chatgpt.status()
        self.assertEqual((st["signed_in"], st["email"]), (True, "me@example.com"))
        self.assertEqual(oct(os.stat(chatgpt._auth_file()).st_mode & 0o777), "0o600")
        token, account = chatgpt.access_token()
        self.assertEqual((account, len(self.token_calls)), ("acct-1", 1))  # still fresh: no refresh
        auth = chatgpt.load()
        auth["expires"] = time.time()
        store.write_private(chatgpt._auth_file(), json.dumps(auth))
        chatgpt.access_token()
        self.assertEqual(self.token_calls[1], {"grant_type": "refresh_token", "refresh_token": "refresh-1", "client_id": chatgpt.CLIENT_ID})

    def test_conversation_models_and_errors(self):
        p = llm.make_provider("chatgpt")
        self.assertFalse(p.available()[0])
        with self.assertRaisesRegex(llm.ProviderError, "Sign in"):
            p.conversation("S", "<paper>x</paper>").send("task")
        q = self.sign_in()
        self.callback({"code": "c", "state": q["state"]})
        self.assertEqual(p.available(), (True, ""))
        self.assertEqual([m["id"] for m in p.models()], ["gpt-6.1-sol"])
        conv = p.conversation("SYSTEM", "<paper>text</paper>")
        self.assertEqual(json.loads(conv.send("task").text), {"turn": 1, "model": "gpt-6.1-sol"})
        self.assertEqual(json.loads(conv.send("repair").text)["turn"], 2)
        first, second = FakeChatGPT.calls
        self.assertEqual(first["body"]["instructions"], "SYSTEM")
        self.assertEqual((first["body"]["store"], first["body"]["stream"]), (False, True))
        self.assertEqual(first["headers"]["chatgpt-account-id"], "acct-1")
        self.assertEqual([m["role"] for m in second["body"]["input"]], ["user", "user", "assistant", "user"])
        with self.assertRaisesRegex(llm.ProviderError, "model overloaded"):
            conv.send("FAIL")
        with self.assertRaisesRegex(llm.ProviderError, "usage limit"):
            conv.send("LIMIT")


def caps(adaptive=True, effort=True):
    return {"thinking": {"supported": True, "types": {"adaptive": {"supported": adaptive}, "enabled": {"supported": not adaptive}}},
            "effort": {"supported": effort, "high": {"supported": effort}}}


class FakeAnthropic(BaseHTTPRequestHandler):
    """A stand-in for the Anthropic Messages and Models APIs. Records each call."""

    calls: list = []
    MODELS = {"claude-opus-5-5": caps(), "claude-haiku-4-5": caps(adaptive=False, effort=False), "claude-sonnet-4-6": caps(effort=False)}

    def log_message(self, *args):
        pass

    def _send(self, status, raw, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _model(self, mid):
        return {"type": "model", "id": mid, "display_name": mid.upper(), "created_at": "2026-01-01T00:00:00Z",
                "max_input_tokens": 1000000, "max_tokens": 128000, "capabilities": self.MODELS[mid]}

    def do_GET(self):
        if self.headers.get("x-api-key") != "good-key":
            return self._send(401, json.dumps({"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}).encode())
        path = urllib.parse.urlsplit(self.path).path
        if path == "/v1/models":
            data = [self._model(m) for m in self.MODELS]
            return self._send(200, json.dumps({"data": data, "has_more": False, "first_id": data[0]["id"], "last_id": data[-1]["id"]}).encode())
        self._send(200, json.dumps(self._model(path.rsplit("/", 1)[1])).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAnthropic.calls.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        last = body["messages"][-1]["content"]
        if "LIMIT" in last:
            return self._send(429, json.dumps({"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}).encode())
        if not body.get("stream"):  # a prefill-only warm-up: no content, just the usage
            return self._send(200, json.dumps({"id": "msg_0", "type": "message", "role": "assistant", "model": body["model"], "content": [],
                                               "stop_reason": "max_tokens", "stop_sequence": None,
                                               "usage": {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 1200}}).encode())
        turn = sum(m["role"] == "assistant" for m in body["messages"]) + 1
        text = json.dumps({"turn": turn, "model": body["model"]})
        stop = "refusal" if "REFUSE" in last else "max_tokens" if "CUT" in last else "end_turn"
        msg = {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"], "content": [], "stop_reason": None,
               "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 1}}
        events = [("message_start", {"type": "message_start", "message": msg}),
                  ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
                  ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig"}}),
                  ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                  ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}}),
                  ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": text}}),
                  ("content_block_stop", {"type": "content_block_stop", "index": 1}),
                  ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 5}}),
                  ("message_stop", {"type": "message_stop"})]
        self._send(200, "".join(f"event: {k}\ndata: {json.dumps(v)}\n\n" for k, v in events).encode(), "text/event-stream")


class ClaudeTests(unittest.TestCase):
    """The Claude provider, through the real SDK against FakeAnthropic."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeAnthropic)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        claude.BASE_URL = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        claude.BASE_URL = None
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        FakeAnthropic.calls.clear()

    def test_conversation_streams_caches_and_keeps_thinking(self):
        p = llm.make_provider("claude", "good-key")
        self.assertEqual(p.model, "claude-opus-5-5")
        conv = p.conversation("SYSTEM", "<paper>text</paper>")
        self.assertEqual(json.loads(conv.send("task").text), {"turn": 1, "model": "claude-opus-5-5"})
        self.assertEqual(json.loads(conv.send("repair").text)["turn"], 2)
        first, second = (c["body"] for c in FakeAnthropic.calls)
        self.assertEqual((first["system"], first["stream"], first["thinking"]), ("SYSTEM", True, {"type": "adaptive"}))
        self.assertEqual(first["cache_control"], {"type": "ephemeral"})  # this conversation's own turns, for its repairs
        self.assertEqual(first["messages"][0]["content"][0]["cache_control"], {"type": "ephemeral"})  # the paper, shared by every concept
        self.assertEqual(first["output_config"], {"effort": "high"})
        self.assertEqual(first["fallbacks"], "default")
        self.assertIn(claude.FALLBACK_BETA, FakeAnthropic.calls[0]["headers"]["anthropic-beta"])
        self.assertEqual([m["role"] for m in second["messages"]], ["user", "user", "assistant", "user"])
        self.assertEqual([b["type"] for b in second["messages"][2]["content"]], ["thinking", "text"])  # sent back as Claude sent it
        self.assertEqual(second["messages"][2]["content"][0]["signature"], "sig")
        self.assertEqual(conv.send("CUT").stop_reason, "max_tokens")

    def test_warming_caches_the_paper_with_the_real_settings(self):
        p = llm.make_provider("claude", "good-key")
        usage = p.warm("SYSTEM", "<paper>text</paper>")
        self.assertEqual(usage.cache_creation_input_tokens, 1200)
        p.conversation("SYSTEM", "<paper>text</paper>").send("task")
        warm, real = (c["body"] for c in FakeAnthropic.calls)
        self.assertEqual(warm["max_tokens"], 0)
        self.assertFalse(warm.get("stream"))  # max_tokens 0 rejects streaming
        self.assertNotIn("cache_control", warm)  # a top-level breakpoint would key the cache to the end of the warm-up
        self.assertEqual(warm["messages"][0], real["messages"][0])  # the same paper, with the same breakpoint
        for key in ("system", "thinking", "output_config", "fallbacks", "model"):
            self.assertEqual(warm[key], real[key], key)  # rendered into the prefix, so they must match

    def test_other_models_skip_what_they_dont_take(self):
        conv = llm.make_provider("claude", "good-key", "claude-sonnet-4-6").conversation("S", "<paper>x</paper>")
        conv.send("task")
        call = FakeAnthropic.calls[0]
        self.assertNotIn("output_config", call["body"])
        self.assertNotIn("fallbacks", call["body"])
        self.assertNotIn("anthropic-beta", call["headers"])

    def test_models_and_errors(self):
        p = llm.make_provider("claude", "good-key")
        self.assertEqual([m["id"] for m in p.models()], ["claude-opus-5-5", "claude-sonnet-4-6"])  # no adaptive thinking: left out
        conv = p.conversation("S", "<paper>x</paper>")
        with self.assertRaisesRegex(llm.ProviderError, "declined"):
            conv.send("REFUSE")
        with self.assertRaisesRegex(llm.ProviderError, "rate or usage limit"):
            conv.send("LIMIT")
        with self.assertRaisesRegex(llm.ProviderError, "didn.t accept this key"):
            llm.make_provider("claude", "bad-key").models()
        self.assertFalse(llm.make_provider("claude").available()[0])
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaisesRegex(llm.ProviderError, "Cancelled"):
            conv.send("task", cancelled)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server(18765)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.cookie = session_cookie()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"localhost:{self.port}", "Cookie": self.cookie}
        h.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, data, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, raw

    def test_index_and_static(self):
        s, raw = self.req("GET", "/")
        self.assertEqual(s, 200)
        self.assertIn(b"Lemma", raw)
        self.assertEqual(self.req("GET", "/static/player.js")[0], 200)
        self.assertEqual(self.req("GET", "/static/../server.py")[0], 404)
        s, raw = self.req("GET", "/static/fonts/archivo-latin-normal.woff2")
        self.assertEqual(s, 200)
        self.assertEqual(raw[:4], b"wOF2")
        self.assertEqual(self.req("GET", "/static/fonts/../styles.css")[0], 404)
        s, raw = self.req("GET", "/privacy")
        self.assertEqual(s, 200)
        self.assertIn(b"never writes it to disk", raw)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)  # the FAQ is a document page like privacy
        c.request("GET", "/faq", headers={"Host": f"localhost:{self.port}"})
        r = c.getresponse()
        raw = r.read()
        c.close()
        self.assertEqual(r.status, 200)
        self.assertIn(b'<details id="key-safe">', raw)
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("Cache-Control"), "no-store")  # like privacy and terms, never cached

    def test_status_follows_the_credential_headers(self):
        s, raw = self.req("GET", "/api/status")
        self.assertEqual(s, 200)
        st = json.loads(raw)
        self.assertIn("library_count", st)
        self.assertEqual({p["id"]: p["sign_in"] for p in st["providers"]}, {"opencode-go": False, "openai": False, "claude": False, "chatgpt": True})
        self.assertFalse(st["provider"]["ok"])  # no key sent
        st = json.loads(self.req("GET", "/api/status", headers={"X-Lemma-Provider": "openai", "X-Lemma-Key": "sk-secret-123", "X-Lemma-Model": "m"})[1])
        self.assertEqual((st["provider"]["id"], st["provider"]["model"], st["provider"]["ok"]), ("openai", "m", True))
        self.assertNotIn("sk-secret-123", json.dumps(st))  # the key never comes back
        # A provider the browser saved that OpenLemma no longer offers, such as the old Claude subscription: status
        # still answers, with the default provider unconnected, so the page loads and Settings offers the rest.
        s, raw = self.req("GET", "/api/status", headers={"X-Lemma-Provider": "claude-code"})
        st = json.loads(raw)
        self.assertEqual((s, st["provider"]["id"], st["provider"]["ok"]), (200, llm.DEFAULT_PROVIDER, False))
        self.assertNotIn("claude-code", {p["id"] for p in st["providers"]})
        s, raw = self.req("GET", "/api/models", headers={"X-Lemma-Provider": "claude-code", "X-Lemma-Key": "k"})
        self.assertEqual((s, json.loads(raw)["error"]), (400, "OpenLemma doesn't offer this AI provider. Choose another on your account page."))

    def test_rejects_foreign_host_and_origin(self):
        self.assertEqual(self.req("GET", "/api/status", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.req("POST", "/api/lessons", {"lesson": {}}, headers={"Origin": "http://evil.example"})[0], 403)

    def test_example_export_and_library(self):
        s, raw = self.req("GET", "/api/example")
        self.assertEqual(s, 200)
        ex = json.loads(raw)
        s, html = self.req("POST", "/api/export", {"lesson": ex})
        self.assertEqual(s, 200)
        self.assertIn(b"connect-src 'none'", html)
        self.assertNotIn(b"fetch(", html)
        # Saving needs the paper text so quotes can be re-checked.
        built = dict(ex, id="abc123", example=False)
        self.assertEqual(self.req("POST", "/api/lessons", {"lesson": built})[0], 409)
        store.save_lesson(built, SOURCE, TESTER)  # as a finished build saves it, with its source
        self.assertEqual(self.req("POST", "/api/lessons", {"lesson": built})[0], 200)
        listing = json.loads(self.req("GET", "/api/lessons")[1])
        self.assertIn("abc123", [x["id"] for x in listing])
        self.assertEqual(next(x for x in listing if x["id"] == "abc123")["category"], "")  # saved before categories
        sorted_lesson = dict(built, id="abc124", category={"primary": {"id": "statistics", "name": "Statistics"}})
        server.store.save_lesson(sorted_lesson, SOURCE, TESTER)
        listing = json.loads(self.req("GET", "/api/lessons")[1])
        self.assertEqual(next(x for x in listing if x["id"] == "abc124")["category"], "Statistics")  # the library shows its subject
        self.assertEqual(self.req("DELETE", "/api/lessons/abc124")[0], 200)
        # An edit that breaks grounding is refused.
        broken = copy.deepcopy(built)
        broken["concepts"][0]["understand"]["quote"] = "This sentence is not in the paper at all, not even close."
        s, raw = self.req("POST", "/api/lessons", {"lesson": broken})
        self.assertEqual(s, 422)
        self.assertTrue(json.loads(raw)["problems"])
        self.assertEqual(self.req("DELETE", "/api/lessons/abc123")[0], 200)

    def test_upload_text_paper(self):
        import base64

        s, raw = self.req("POST", "/api/papers", {"filename": "galton.txt", "content_type": "text/plain", "data": base64.b64encode(SOURCE.encode()).decode()})
        self.assertEqual(s, 200, raw)
        self.assertGreater(json.loads(raw)["chars"], 40000)

    def test_gallery_lessons_open_read_only(self):
        items = json.loads(self.req("GET", "/api/gallery")[1])
        self.assertEqual([x["slug"] for x in items], [x["slug"] for x in server.gallery_index()])
        self.assertEqual(len(items), 18)
        for x in items:
            self.assertTrue(x["field"] and x["concepts"] and x["cover"]["idea"], x["slug"])
            s, raw = self.req("GET", f"/api/gallery/{x['slug']}")
            self.assertEqual(s, 200, raw)
            lesson = json.loads(raw)
            self.assertTrue(lesson["example"])
            self.assertEqual(lesson["gallery"]["slug"], x["slug"])
            self.assertEqual(list(L.check_lesson(lesson, None)), [], x["slug"])
            self.assertEqual(self.req("POST", "/api/lessons", {"lesson": lesson})[0], 400)  # can't be saved or edited
        self.assertEqual(self.req("GET", "/api/gallery/nope")[0], 404)
        # A download is made from the lesson as shipped, whatever the browser sends back.
        tampered = json.loads(self.req("GET", "/api/gallery/gettier-1963")[1])
        tampered["title"] = "Something else entirely"
        s, html = self.req("POST", "/api/export", {"lesson": tampered})
        self.assertEqual(s, 200)
        self.assertNotIn(b"Something else entirely", html)

    def test_every_gallery_lesson_opens(self):
        for entry in server.gallery_index():  # served only after passing its checks
            s, raw = self.req("GET", f"/api/gallery/{entry['slug']}")
            self.assertEqual(s, 200, (entry["slug"], raw[:200]))

    def test_unexpected_error_is_reported_without_its_message(self):
        import contextlib
        import io

        err = io.StringIO()
        with patch.object(server.store, "list_lessons", side_effect=RuntimeError("paper text sk-secret-123")), contextlib.redirect_stderr(err):
            s, raw = self.req("GET", "/api/lessons")
        self.assertEqual(s, 500)
        message = json.loads(raw)["error"]
        eid = re.search(r"error id ([0-9a-f]{8})\.$", message).group(1)
        self.assertEqual(message, "Something went wrong inside OpenLemma. Try again; if it keeps happening, "
                                  f"email contact@openlemma.org with error id {eid}.")
        self.assertNotIn(b"sk-secret-123", raw)
        self.assertIn(f"error {eid} in GET /api/lessons: RuntimeError", err.getvalue())
        self.assertIn("server.py", err.getvalue())  # where it broke
        self.assertNotIn("sk-secret-123", err.getvalue())

    def test_connections_beyond_the_limit_wait_their_turn(self):
        with patch.object(server, "MAX_CONNECTIONS", 1):
            httpd = server.make_server(0, exact=True)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            port = httpd.server_address[1]
            idle = socket.create_connection(("127.0.0.1", port))  # takes the only slot and sends nothing
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
            c.request("GET", "/api/status", headers={"Host": f"localhost:{port}"})
            with self.assertRaises(TimeoutError):
                c.getresponse()
            idle.close()  # its slot frees up, so the waiting request is answered
            c.sock.settimeout(10)
            self.assertEqual(c.getresponse().status, 200)
        finally:
            httpd.shutdown()
            httpd.server_close()


class HostedServerTests(unittest.TestCase):
    def tearDown(self):
        reset_server()

    def test_needs_its_domain_names(self):
        with self.assertRaises(ValueError):
            server.make_server(0, host="0.0.0.0")

    def test_answers_its_domain_and_drops_chatgpt_sign_in(self):
        httpd = server.make_server(0, host="0.0.0.0", allowed_hosts=("tools.example.com",))
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        def req(method, path, headers):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request(method, path, b"{}" if method == "POST" else None, headers)
            r = c.getresponse()
            raw = r.read()
            c.close()
            return r.status, raw

        site = {"Host": "tools.example.com"}
        try:
            s, raw = req("GET", "/api/status", site)
            self.assertEqual(s, 200)
            offered = {p["id"] for p in json.loads(raw)["providers"]}
            self.assertNotIn("chatgpt", offered)  # the one thing a hosted server leaves out
            self.assertIn("claude", offered)  # the keyed providers are all still there
            self.assertEqual(req("GET", "/api/status", {"Host": "evil.example"})[0], 403)
            self.assertEqual(req("GET", "/api/chatgpt", site)[0], 404)
            self.assertEqual(req("POST", "/api/chatgpt/login", dict(site, Origin="https://tools.example.com"))[0], 404)
            self.assertEqual(req("GET", "/api/models", dict(site, **{"X-Lemma-Provider": "chatgpt"}))[0], 400)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_accounts_keep_their_own_library_and_builds(self):
        env = {"LEMMA_PUBLIC_URL": "https://tools.example.com/lemma", "LEMMA_GOOGLE_CLIENT_ID": "gid", "LEMMA_GOOGLE_CLIENT_SECRET": "gsecret"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        httpd = server.make_server(0, host="0.0.0.0", allowed_hosts=("tools.example.com", "www.example.com"))
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        def req(method, path, body=None, token=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            h = {"Host": "tools.example.com", "Origin": "https://tools.example.com"}
            if token:
                h["Cookie"] = f"{auth.SESSION_COOKIE}={token}"
            c.request(method, path, json.dumps(body).encode() if body is not None else None, h)
            r = c.getresponse()
            raw = r.read()
            c.close()
            return r.status, raw, r

        try:
            # Lemma serves under the public URL's path too, as it does behind Cloudflare Tunnel.
            self.assertEqual(req("GET", "/lemma/api/example")[0], 200)
            # Its other names send people to the public address, so sign-in starts and ends on one host.
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", "/lemma/privacy?x=1", headers={"Host": "www.example.com"})
            r = c.getresponse()
            self.assertEqual((r.status, r.getheader("Location")), (301, "https://tools.example.com/lemma/privacy?x=1"))
            c.close()
            s, _, r = req("GET", "/lemma")
            self.assertEqual((s, r.getheader("Location")), (301, "/lemma/"))
            # Signed out: the example works, nothing else does.
            self.assertEqual(req("GET", "/api/example")[0], 200)
            for method, path, body in [("GET", "/api/lessons", None), ("POST", "/api/search", {"query": "x"}), ("POST", "/api/papers", {"url": "https://example.com"})]:
                self.assertEqual(req(method, path, body)[0], 401, path)
            st = json.loads(req("GET", "/api/status")[1])
            self.assertEqual((st["user"], st["sign_in"]), (None, [{"id": "google", "name": "Google", "label": "Continue with Google"}]))

            # Signing in starts at Google with a state cookie scoped to /lemma/; a wrong state is refused.
            s, _, r = req("GET", "/auth/google/start")
            self.assertEqual(s, 302)
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(r.getheader("Location")).query)
            self.assertEqual(q["redirect_uri"], ["https://tools.example.com/lemma/auth/google/callback"])
            self.assertIn("Path=/lemma/; Max-Age=600; HttpOnly; SameSite=Lax; Secure", r.getheader("Set-Cookie"))
            s, _, r = req("GET", "/auth/google/callback?code=c&state=forged")
            self.assertEqual(s, 302)
            self.assertTrue(r.getheader("Location").startswith("https://tools.example.com/lemma/#/signin?error="))
            self.assertEqual(req("GET", "/auth/twitter/start")[0], 404)

            ada = auth.upsert_user("google", "1", "Ada", "ada@example.com", "")
            bob = auth.upsert_user("github", "2", "Bob", "bob@example.com", "")
            ta, tb = auth.new_session(ada["id"]), auth.new_session(bob["id"])
            self.assertEqual(json.loads(req("GET", "/api/status", token=ta)[1])["user"]["name"], "Ada")

            lesson = dict(json.loads(req("GET", "/api/example")[1]), id="adas01", example=False)
            store.save_lesson(lesson, SOURCE, ada["id"])  # Ada's finished build
            self.assertEqual(req("POST", "/api/lessons", {"lesson": lesson}, tb)[0], 409)  # Bob can't save Ada's build
            self.assertEqual(req("POST", "/api/lessons", {"lesson": lesson}, ta)[0], 200)
            self.assertEqual([x["id"] for x in json.loads(req("GET", "/api/lessons", token=ta)[1])], ["adas01"])
            self.assertEqual(json.loads(req("GET", "/api/lessons", token=tb)[1]), [])
            self.assertEqual(req("GET", "/api/lessons/adas01", token=tb)[0], 404)
            req("DELETE", "/api/lessons/adas01", token=tb)
            self.assertEqual(req("GET", "/api/lessons/adas01", token=ta)[0], 200)  # Bob's delete didn't touch it

            s, _, r = req("POST", "/api/logout", {}, ta)
            self.assertEqual(s, 200)
            self.assertIn(f"{auth.SESSION_COOKIE}=; Path=/lemma/; Max-Age=0", r.getheader("Set-Cookie"))
            self.assertIsNone(json.loads(req("GET", "/api/status", token=ta)[1])["user"])
        finally:
            generate.JOBS.clear()
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            httpd.shutdown()
            httpd.server_close()

    def test_daily_limits_and_anonymous_counts(self):
        env = {"LEMMA_PUBLIC_URL": "https://tools.example.com", "LEMMA_ADMINS": "ada@example.com", "LEMMA_DAILY_SEARCHES": "1"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        httpd = server.make_server(0, host="0.0.0.0", allowed_hosts=("tools.example.com",))
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        def req(method, path, body=None, token=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            h = {"Host": "tools.example.com", "Origin": "https://tools.example.com"}
            if token:
                h["Cookie"] = f"{auth.SESSION_COOKIE}={token}"
            c.request(method, path, json.dumps(body).encode() if body is not None else None, h)
            r = c.getresponse()
            raw = r.read()
            c.close()
            return r.status, raw, r

        try:
            ada = auth.upsert_user("google", "11", "Ada", "ada@example.com", "")
            bob = auth.upsert_user("github", "12", "Bob", "bob@example.com", "")
            ta, tb = auth.new_session(ada["id"]), auth.new_session(bob["id"])

            # Anyone, signed in or not, can report a known event; unknown names are dropped.
            for name in ("lesson_open", "lesson_open", "made_up"):
                self.assertEqual(req("POST", "/api/event", {"name": name})[0], 200)
            self.assertEqual(req("GET", "/api/stats", token=tb)[0], 404)  # only the admins see counts
            today = next(iter(json.loads(req("GET", "/api/stats", token=ta)[1]).values()))
            self.assertEqual(today.get("lesson_open"), 2)
            self.assertNotIn("made_up", today)

            # Each account has its own daily allowance.
            self.assertTrue(metrics.take(bob["id"], "search"))
            self.assertFalse(metrics.take(bob["id"], "search"))
            self.assertTrue(metrics.take(ada["id"], "search"))
            with patch.object(server, "_provider", return_value=FakeProvider()):
                s, raw, _ = req("POST", "/api/search", {"query": "loss aversion"}, tb)
            self.assertEqual(s, 429)
            self.assertIn("today's 1 searches", json.loads(raw)["error"])

            s, raw, r = req("GET", "/terms")
            self.assertEqual(s, 200)
            self.assertIn(b"Terms of use", raw)
            self.assertIn("https://static.cloudflareinsights.com", r.getheader("Content-Security-Policy"))
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            httpd.shutdown()
            httpd.server_close()


class ServerLimitTests(unittest.TestCase):
    """What one account can make a hosted server do at once, and what needs an account at all."""

    def setUp(self):
        self.was = server.DEV

    def tearDown(self):
        server.DEV = self.was
        reset_server()
        server.REQUEST.user = None
        generate.JOBS.clear()

    @staticmethod
    def as_user(uid):
        server.REQUEST.user = {"id": uid, "email": f"{uid}@example.com"}

    def test_exporting_your_own_lesson_needs_an_account_when_hosted(self):
        lesson, _ = server.load_example()
        server.REQUEST.user = None
        with self.assertRaises(server.ApiError) as e:
            server.api_export({"lesson": dict(lesson, id="mine", example=False)})
        self.assertEqual(e.exception.status, 401)

    def test_anyone_can_download_the_example_and_gallery_as_shipped(self):
        server.REQUEST.user = None
        lesson, _ = server.load_example()
        tampered = dict(lesson, example=True, title="Not the real title")
        html = server.api_export({"lesson": tampered})
        self.assertIn(lesson["title"], html)
        self.assertNotIn("Not the real title", html)  # the shipped lesson, not the one sent
        slug = server.api_gallery({})[0]["slug"]
        self.assertIn("<!doctype html>", server.api_export({"lesson": {"gallery": {"slug": slug}}}))

    def test_exporting_an_unknown_lesson_refuses_rather_than_skipping_the_quote_check(self):
        lesson, _ = server.load_example()
        self.as_user("exp1")
        with self.assertRaises(server.ApiError) as e:
            server.api_export({"lesson": dict(lesson, id="nosuchlesson", example=False)})
        self.assertEqual(e.exception.status, 409)

    def test_parallel_requests_cannot_overspend_the_daily_allowance(self):
        os.environ["LEMMA_DAILY_SEARCHES"] = "3"
        try:
            granted, go = [], threading.Barrier(30)
            def take():
                go.wait()
                granted.append(metrics.take("race1", "search"))
            threads = [threading.Thread(target=take) for _ in range(30)]
            for t in threads: t.start()
            for t in threads: t.join()
            self.assertEqual(granted.count(True), 3)
        finally:
            os.environ.pop("LEMMA_DAILY_SEARCHES", None)

    def test_parallel_builds_cannot_pass_the_running_cap(self):
        results, go = [], threading.Barrier(6)
        def start():
            self.as_user("race2")
            go.wait()
            try:
                server._new_job("build"); results.append("ok")
            except server.ApiError as e:
                results.append(e.status)
        threads = [threading.Thread(target=start) for _ in range(6)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(results.count("ok"), server.MAX_RUNNING_EACH)

    def test_a_running_build_cannot_be_deleted_out_of_the_running_count(self):
        self.as_user("del1")
        job = server._new_job("request")
        generate.JOBS[job.id] = job
        with self.assertRaises(server.ApiError) as e:
            server.api_lesson_delete(job.id)
        self.assertEqual(e.exception.status, 409)
        self.assertIn(job.id, generate.JOBS)

    def test_one_account_can_read_only_two_sources_at_once(self):
        release, started, results = threading.Event(), threading.Semaphore(0), []
        def slow(url, **kw):
            started.release(); release.wait(5)
            return ingest.Paper(text="x" * 2000, title="T", kind="html", url=url)
        def read():
            self.as_user("papers1")
            try:
                server.api_papers({"url": "https://example.org/a"}); results.append("ok")
            except server.ApiError as e:
                results.append(e.status)
        with patch.object(ingest, "from_url", slow):
            first = [threading.Thread(target=read) for _ in range(2)]
            for t in first: t.start()
            for _ in first: started.acquire(timeout=5)
            read()  # a third, while two are still being read
            release.set()
            for t in first: t.join()
        self.assertEqual(sorted(map(str, results)), ["429", "ok", "ok"])

    def test_a_build_that_fails_to_start_does_not_stay_running(self):
        self.as_user("ph1")
        server.REQUEST.headers = {}
        record = {"id": "abcdef123456", "title": "T", "request": {"audience": ""}, "paper": {"text": "x"}, "status": "queued"}
        with patch.object(server.store, "save_request", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                server._launch_request(record, None, "ph1")
        self.assertNotIn("abcdef123456", generate.JOBS)
        server._new_job("build")  # the account can still build

    def test_a_bad_content_length_is_refused_before_any_body_is_read(self):
        httpd = server.make_server(0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            for length, status in (("-1", 400), ("abc", 400), (str(server.MAX_BODY + 1), 413)):
                with socket.create_connection(httpd.server_address, timeout=5) as sock:
                    sock.sendall(f"POST /api/event HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {length}\r\n\r\n{{}}".encode())
                    reply = sock.recv(200).decode()
                self.assertIn(f" {status} ", reply.split("\r\n")[0], length)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_the_film_streams_in_byte_ranges_and_caches(self):
        httpd = server.make_server(0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        path = "/static/film-v5-720.mp4"
        size = (Path(server.STATIC.joinpath("film-v5-720.mp4"))).stat().st_size
        def get(headers):
            c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
            c.request("GET", path, headers=dict({"Host": "localhost"}, **headers))
            r = c.getresponse(); body = r.read(); c.close()
            return r, body
        try:
            r, body = get({"Range": "bytes=0-99"})
            self.assertEqual((r.status, len(body), r.getheader("Content-Range")), (206, 100, f"bytes 0-99/{size}"))
            self.assertEqual(r.getheader("Content-Type"), "video/mp4")
            r, body = get({"Range": f"bytes={size - 10}-"})
            self.assertEqual((r.status, len(body)), (206, 10))
            r, body = get({})
            self.assertEqual((r.status, len(body), r.getheader("Accept-Ranges")), (200, size, "bytes"))
            self.assertIn("immutable", r.getheader("Cache-Control"))
            r, _ = get({"Range": f"bytes={size + 5}-"})
            self.assertEqual((r.status, r.getheader("Content-Range")), (416, f"bytes */{size}"))
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_dev_mode_is_off_on_a_hosted_server(self):
        server.DEV = True
        httpd = server.make_server(0, host="0.0.0.0", allowed_hosts=("tools.example.com",))
        httpd.server_close()
        self.assertFalse(server.DEV)

    def test_a_large_upload_that_isnt_a_pdf_is_refused(self):
        self.as_user("up1")
        data = base64.b64encode(b"<html>" + b"x" * (ingest.MAX_PAGE_BYTES + 10)).decode()
        with self.assertRaises(server.ApiError) as e:
            server.api_papers({"data": data, "filename": "big.html", "content_type": "text/html"})
        self.assertEqual(e.exception.status, 413)


class DevModeTests(unittest.TestCase):
    def test_change_detection(self):
        d = Path(tempfile.mkdtemp(dir=TMP_HOME))
        (d / "a.py").write_text("x = 1")
        (d / "b.css").write_text("")
        before = dev.snapshot(d, (".py",))
        self.assertEqual(list(before), [str(d / "a.py")])
        os.utime(d / "a.py", (time.time() + 5, time.time() + 5))
        (d / "c.py").write_text("")
        self.assertEqual(dev.changed(before, dev.snapshot(d, (".py",))), [str(d / "a.py"), str(d / "c.py")])

    def test_dev_server_injects_reload_script_and_streams_events(self):
        httpd = server.make_server(0, exact=True)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        host = {"Host": f"localhost:{port}"}
        try:
            def get(path, read=None):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                c.request("GET", path, headers=host)
                r = c.getresponse()
                body = b"".join(r.readline() for _ in range(read)) if read else r.read()
                c.close()
                return r.status, body

            server.DEV = False
            self.assertNotIn(b"dev-reload.js", get("/")[1])
            self.assertEqual(get("/api/dev/events")[0], 404)
            server.DEV = True
            self.assertIn(b'<script src="static/dev-reload.js"></script>', get("/")[1])
            status, first = get("/api/dev/events", read=3)  # three lines: retry, event, data
            self.assertEqual(status, 200)
            self.assertIn(f"event: hello\ndata: {dev.BOOT_ID}".encode(), first)
        finally:
            server.DEV = False
            httpd.shutdown()
            httpd.server_close()

    def test_export_never_includes_the_reload_script(self):
        self.assertNotIn("dev-reload", export.lesson_html(EXAMPLE))

    def test_export_has_no_feedback_prompt_and_sends_nothing(self):
        # The end-of-lesson feedback prompt is made by app.js and handed to the player only for signed-in accounts;
        # the offline file mounts the player with no hooks, so it has no prompt and nothing that could send one.
        html = export.lesson_html(EXAMPLE)
        self.assertIn('LemmaPlayer.mount(document.getElementById("main"), JSON.parse(document.getElementById("lesson-data").textContent), {});', html)
        for absent in ("How was this lesson", "api/feedback", "fetch(", "XMLHttpRequest", "sendBeacon"):
            self.assertNotIn(absent, html)


class ExportTests(unittest.TestCase):
    def test_fonts_are_embedded_not_linked(self):
        html = export.lesson_html(EXAMPLE)
        style = html.split("<style>")[1].split("</style>")[0]
        self.assertIn("font-src data:", html)
        embedded = style.count("data:font/woff2;base64,") - style.count('data:font/woff2;base64,"')
        self.assertEqual(embedded, 2)  # every face a lesson uses; the gallery cards' italic is left out empty
        self.assertNotIn('url("fonts/', style)

    def test_embedded_json_cannot_break_out(self):
        les = copy.deepcopy(EXAMPLE)
        les["title"] = "</script><script>alert(1)</script>"
        html = export.lesson_html(les)
        self.assertEqual(html.count("</script>"), len(export.SCRIPTS) + 2)  # lesson data, scripts, boot
        self.assertIn("&lt;/script&gt;", html.split("<title>")[1].split("</title>")[0])


class FakeJev(BaseHTTPRequestHandler):
    """Answers like TypeSafe's Jev: the choice it was told to give, with a probability for every option."""
    reply, status, seen = None, 200, []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeJev.seen.append((self.headers.get("Authorization"), body))
        raw = json.dumps(FakeJev.reply).encode()
        self.send_response(FakeJev.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


class CategorizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeJev)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.env = patch.dict(os.environ, {"TYPESAFE_API_KEY": "ts-test", "TYPESAFE_URL": f"http://127.0.0.1:{self.httpd.server_address[1]}/v1/systemone"})
        self.env.start()
        for p in (patch.object(jev, "ask", fakejev.REAL_ASK), patch.object(jev, "RETRY_WAIT", 0)):
            p.start()
            self.addCleanup(p.stop)
        FakeJev.status, FakeJev.seen = 200, []
        FakeJev.reply = {"model": "jev-1.13.0", "answers": {"category": {"type": "choice", "choice": "medicine", "confidence": .7,
                         "probabilities": {"medicine": .6, "ai_ml": .3, "other": .1}}}}

    def tearDown(self):
        self.env.stop()

    def test_primary_and_a_likely_runner_up(self):
        c = categorize.categorize({"title": "Deep learning for diagnosis", "text": "x" * 100})
        self.assertEqual(c["primary"], {"id": "medicine", "name": "Medicine"})
        self.assertEqual(c["secondary"], {"id": "ai_ml", "name": "AI & machine learning"})
        self.assertEqual(c["probabilities"]["medicine"], .6)
        auth_header, body = FakeJev.seen[0]
        self.assertEqual(auth_header, "Bearer ts-test")
        self.assertEqual(body["model"], jev.MODEL)
        q = body["questions"]["category"]
        self.assertEqual(q["type"], "choice")
        self.assertEqual(set(q["criteria"]), set(categorize.CATEGORIES))

    def test_an_unlikely_runner_up_is_left_out(self):
        FakeJev.reply["answers"]["category"]["probabilities"] = {"medicine": .85, "ai_ml": .1, "other": .05}
        self.assertIsNone(categorize.categorize({"title": "t", "text": "x"})["secondary"])

    def test_sources_share_the_text_budget(self):
        bundle = json.dumps({"lemma_sources": [{"id": "s1", "title": "A", "text": "a" * 100_000}, {"id": "s2", "title": "B", "text": "b" * 100_000}]})
        categorize.categorize({"title": "Combined", "text": bundle})
        sent = FakeJev.seen[0][1]["state"]["sources"]
        self.assertEqual([s["title"] for s in sent], ["A", "B"])
        self.assertEqual(sum(len(s["text"]) for s in sent), categorize.STATE_CHARS)

    def test_failures_raise_a_categorize_error(self):
        FakeJev.status = 401
        with self.assertRaises(categorize.CategorizeError):
            categorize.categorize({"title": "t", "text": "x"})
        FakeJev.status, FakeJev.reply = 200, {"answers": {"category": {"choice": "astrology", "probabilities": {}}}}
        with self.assertRaises(categorize.CategorizeError):
            categorize.categorize({"title": "t", "text": "x"})

    def test_a_lesson_jev_cannot_sort_stops_its_build(self):
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            self.assertFalse(jev.available())
            with self.assertRaisesRegex(generate.GenerationError, "TYPESAFE_API_KEY"):
                server._categorize({}, {"title": "t", "text": "x"})
        self.assertEqual(FakeJev.seen, [])
        FakeJev.status = 401
        with self.assertRaisesRegex(generate.GenerationError, "401"):
            server._categorize({}, {"title": "t", "text": "x"})

    def test_a_brief_outage_is_retried_and_a_refusal_is_not(self):
        FakeJev.status = 503
        with self.assertRaises(categorize.CategorizeError):
            categorize.categorize({"title": "t", "text": "x"})
        self.assertEqual(len(FakeJev.seen), jev.ATTEMPTS)
        FakeJev.status, FakeJev.seen = 401, []
        with self.assertRaises(categorize.CategorizeError):
            categorize.categorize({"title": "t", "text": "x"})
        self.assertEqual(len(FakeJev.seen), 1)

    def test_a_categorised_lesson_passes_the_checks(self):
        lesson = copy.deepcopy(EXAMPLE)
        lesson["category"] = categorize.categorize({"title": "t", "text": "x"})
        source = (ROOT / "lemma/examples/galton-1886.txt").read_text()
        self.assertEqual(list(L.check_lesson(lesson, source)), [])

    def field_reply(self, probs, span, second="medicine"):
        FakeJev.reply = {"model": "jev-1.13.0", "answers": {
            "field": {"type": "choice", "choice": max(probs, key=probs.get), "probabilities": probs},
            "span": {"type": "choice", "choice": span, "probabilities": {span: .8}},
            "second": {"type": "choice", "choice": second, "probabilities": {second: .7}}}}

    def test_a_question_gets_one_field_and_the_likely_others_to_switch_to(self):
        self.field_reply({"chemistry": .5, "physics_astronomy": .3, "religion": .15, "other": .04, "law": .01}, "one")
        f = categorize.question_field("Mercury")
        self.assertEqual((f["ids"], f["kind"], f["chosen_by"]), (["chemistry"], "one", "jev"))
        self.assertEqual([a["id"] for a in f["alternatives"]], ["physics_astronomy", "religion"])
        body = FakeJev.seen[0][1]
        self.assertEqual(body["state"], {"question": "Mercury"})
        self.assertEqual(set(body["questions"]["field"]["criteria"]), set(categorize.CATEGORIES))

    def test_a_question_needing_two_fields_names_the_second_by_asking_for_it(self):
        # The runner-up of "which field?" is biology, but asked for the other field it needs, Jev names medicine.
        self.field_reply({"psychology": .9, "biology": .07, "medicine": .03}, "both")
        f = categorize.question_field("Why does stress make you sick?")
        self.assertEqual((f["ids"], f["kind"]), (["psychology", "medicine"], "both"))
        self.assertEqual([a["id"] for a in f["alternatives"]], ["biology"])
        asked = FakeJev.seen[1][1]["questions"]["second"]
        self.assertIn("needs Psychology and one other field", asked["instructions"])
        self.assertNotIn("psychology", asked["criteria"])
        self.field_reply({"psychology": .9, "biology": .07, "medicine": .03}, "one")
        FakeJev.seen = []
        self.assertEqual(categorize.question_field("Why does stress make you sick?")["kind"], "one")
        self.assertEqual(len(FakeJev.seen), 1)  # one field needs no second question
        self.field_reply({"psychology": .9, "biology": .1}, "both", second="psychology")
        with self.assertRaises(categorize.CategorizeError):  # not a second field at all
            categorize.question_field("Why does stress make you sick?")

    def test_a_question_jev_cannot_place_raises(self):
        FakeJev.status = 401
        with self.assertRaises(categorize.CategorizeError):
            categorize.question_field("Mercury")
        FakeJev.status, FakeJev.reply = 200, {"answers": {"field": {"choice": "astrology", "probabilities": {}}, "span": {"choice": "one"}}}
        with self.assertRaises(categorize.CategorizeError):
            categorize.question_field("Mercury")


sys.path.insert(0, str(ROOT / "eval"))
import jev_judge  # noqa: E402
import plant as eval_plant  # noqa: E402
import questions as eval_questions  # noqa: E402


class JevEvalTests(unittest.TestCase):
    """The Jev eval's own logic, with Jev faked: what it plants, what it shows Jev, and how answers combine."""

    source = (ROOT / "lemma/examples/galton-1886.txt").read_text()

    def judged(self, yes_for=(), split=(), lesson=None, failing=(), opposite=(), quote_no=False, p_for=None):
        """Judge a lesson (the example by default) with a fake Jev that passes every check, except: yes to critical-error
        questions whose key contains any of `yes_for` (`split`: only one lens says yes), and the Part B checks in `failing` fail."""
        lesson = lesson or EXAMPLE
        self.asked = []

        def ask(state, questions, timeout):
            self.asked.append((state, questions))
            out = {"_model": "fake"}
            for k, q in questions.items():
                if q["type"] == "noul" and "|B|" in k:
                    dim, j = k.split("|")[2].split(".")
                    wanted = eval_questions.PART_B[dim]["checks"][int(j)].get("passed_when", "yes")
                    passes = f"{dim}.{j}" not in failing
                    out[k] = {"type": "noul", "noul": .95 if (wanted == "yes") == passes else .05}
                elif q["type"] == "noul" and "|N|" in k:  # a number in the paper in brief: reported, unless told otherwise
                    out[k] = {"type": "noul", "noul": (p_for or {}).get(k.split("|")[2], .95)}
                elif q["type"] == "noul":
                    hit = any(s in k for s in yes_for) or any(s in k for s in split) and k.endswith("|referee")
                    out[k] = {"type": "noul", "noul": (p_for or {}).get(k.split("|")[2], .9 if hit else .1)}
                elif "|D|" in k:  # a direction question: agree with the model unless this source is told to say the opposite
                    source = k.split("|")[2].split(":")[0]
                    out[k] = {"type": "choice", "choice": "x", "probabilities": {"opposite": 1} if source in opposite else {"not_said": .6}}
                elif quote_no and "|A|A1|" in k:
                    out[k] = {"type": "choice", "choice": "no", "probabilities": {"no": .9}}
                elif "|A|" in k and eval_questions.PART_A[k.split("|")[2]].get("passed_when") == "no":  # no problem found
                    out[k] = {"type": "choice", "choice": "no", "probabilities": {"no": .9}}
                else:
                    out[k] = {"type": "choice", "choice": "yes", "probabilities": {"yes": .9}}
            return out
        with patch.object(jev, "ask", side_effect=ask):
            judged = jev_judge.judge_lesson(lesson, self.source)
        return judged, jev_judge.combine(lesson, judged)

    def lesson_with_tasks(self):
        """The example with a concept taught without a model: worked example, then scored tasks."""
        lesson = copy.deepcopy(EXAMPLE)
        c = lesson["concepts"][0]
        lesson["concepts"].append({k: c[k] for k in ("title", "idea", "role", "terms", "recap")} | {
            "id": "procedure", "understand": {k: c["understand"][k] for k in ("explanation", "quote", "quote_where")},
            "activities": [{"id": "learn", "kind": "explain"},
                           {"id": "steps", "kind": "worked", "title": "Average two parents", "steps": [{"text": "Scale the mother's height."}, {"text": "Average."}], "takeaway": "One number."},
                           {"id": "q", "kind": "choice", "mode": "determinate", "question": "Which is averaged?", "answer": 0,
                            "options": [{"text": "Both parents", "feedback": "Yes."}, {"text": "The father only", "feedback": "No."}]},
                           {"id": "chain", "kind": "order", "prompt": "Order the steps.", "items": ["Scale", "Average", "Compare"], "explanation": "Scale first."}]})
        return lesson

    def test_every_planted_kind_changes_one_concept_and_leaves_the_original(self):
        before = json.dumps(EXAMPLE, sort_keys=True)
        self.assertIsNone(eval_plant.plant(EXAMPLE, self.source, "wrong_task_answer"))  # no scored activity blocks to break
        tasks = self.lesson_with_tasks()
        for kind in eval_plant.KINDS:
            out = eval_plant.plant(tasks if kind == "wrong_task_answer" else EXAMPLE, self.source, kind)
            self.assertIsNotNone(out, kind)
            lesson, where = out
            self.assertEqual(where["kind"], kind)
            changed = [c["id"] for c, o in zip(lesson["concepts"], (tasks if kind == "wrong_task_answer" else EXAMPLE)["concepts"]) if c != o]
            self.assertEqual(changed, [where["concept"]], kind)
        self.assertEqual(json.dumps(EXAMPLE, sort_keys=True), before)

    def test_the_evals_questions_are_its_own(self):
        from lemma import factcheck
        for kind in factcheck.BUILD_KINDS:  # what the build checks, the eval asks in its own words
            if kind in eval_questions.CRITICAL:
                self.assertNotEqual(eval_questions.CRITICAL[kind], factcheck.CRITICAL.get(kind), kind)
        self.assertNotEqual(eval_questions.WRONG_ANSWER, factcheck.WRONG_ANSWER)
        self.assertFalse(set(eval_questions.LENSES.values()) & set(factcheck.LENSES.values()))
        for spec in eval_questions.PART_B.values():
            self.assertTrue(all(set(c) <= {"ask", "passed_when", "when"} and c.get("passed_when", "yes") in ("yes", "no") for c in spec["checks"]))
        groups = [g for spec in eval_questions.SCORES.values() for g in spec["groups"]]
        self.assertEqual(len(groups), len(set(groups)))  # each group counts in one score only
        self.assertTrue(set(eval_questions.PART_A) | set(eval_questions.PART_B) <= set(groups))  # and every item counts somewhere

    def test_the_teaching_is_judged_as_a_learner_sees_it(self):
        self.judged()
        for state, questions in self.asked:
            hidden = all("|A|" in k and not eval_questions.PART_A[k.split("|")[2]]["paper"] or k.startswith("lesson|B|") and not
                         eval_questions.PART_B[k.split("|")[2].split(".")[0]]["paper"] for k in questions)
            if hidden:
                self.assertNotIn("reached when", state)
        self.assertTrue(any("reached when" in state for state, _ in self.asked))  # the critical-error questions still see the conditions

    def test_concepts_get_only_the_questions_that_apply(self):
        _, r = self.judged(lesson=self.lesson_with_tasks())
        asked = {k for _, q in self.asked for k in q if k.startswith("procedure|")}
        items = {k.split("|")[2] for k in asked if "|A|" in k}
        # no model, goals, hints, interpretations or other sources
        self.assertEqual(items, {"A1", "A4", "A6", "A7", "A8", "A12", "A14", "A15", "A17", "A18", "A19"})
        self.assertNotIn("procedure|C|reversed_model|referee", asked)
        self.assertEqual({k.split("|")[2] for k in asked if "wrong_answer" in k}, {"wrong_answer:q", "wrong_answer:chain"})
        self.assertEqual(r["verdict"], "ship")
        self.assertNotIn("procedure.A2", r["items"])

    def test_a_problem_finding_check_fails_on_yes(self):
        _, r = self.judged(failing=("B4.1", "B4.2"))  # goal text states the value; an early hint gives it away
        self.assertLess(r["scales"]["B4"], 1)
        self.assertEqual(r["verdict"], "ship_with_fixes")
        self.assertTrue(any("state the value" in p for p in r["top_problems"]))

    def test_the_builds_own_flags_are_reported_apart(self):
        lesson = copy.deepcopy(EXAMPLE)
        lesson["flags"] = [{"concept": lesson["concepts"][0]["id"], "kind": "wrong_claim", "certainty": .8}]
        _, r = self.judged(lesson=lesson)
        self.assertEqual(len(r["build_check"]["flags_left_for_review"]), 1)
        self.assertEqual(r["critical_errors"], [])  # the eval's verdict comes from its own questions

    def test_scores_rise_and_fall_with_what_jev_finds(self):
        clean = self.judged()[1]["scores"]
        self.assertEqual(set(clean), set(eval_questions.SCORES) | {"overall"})
        self.assertTrue(all(80 <= v <= 100 for k, v in clean.items() if k not in ("presentation", "overall")), clean)  # Jev's scores
        data = jev_judge.data_checks(EXAMPLE)  # Presentation comes from the lesson itself, not from Jev
        groups = [sum(v.values()) / len(v) for k, v in data.items() if v and "M:" + k in eval_questions.SCORES["presentation"]["groups"]]
        self.assertEqual(clean["presentation"], round(100 * sum(groups) / len(groups), 1))
        wrong = self.judged(yes_for=("|C|wrong_claim|",))[1]["scores"]
        self.assertLess(wrong["accuracy"], clean["accuracy"])
        self.assertEqual({k: v for k, v in wrong.items() if k not in ("accuracy", "overall")},
                         {k: v for k, v in clean.items() if k not in ("accuracy", "overall")})  # a wrong claim moves Accuracy alone
        practice = self.judged(failing=("B4.1", "B4.2"))[1]["scores"]
        self.assertLess(practice["practice"], clean["practice"])
        self.assertEqual(practice["teaching"], clean["teaching"])

    def test_runs_are_compared_paper_by_paper(self):
        import contextlib
        import io
        import run as eval_run
        with tempfile.TemporaryDirectory() as tmp:
            def make(name, overall, version="jev-eval-4"):
                d = Path(tmp, name, "papers")
                d.mkdir(parents=True)
                papers = [{"unit": f"{i:02d}", "scores": {"accuracy": overall[i], "teaching": overall[i], "coverage": overall[i], "overall": overall[i]}}
                          for i in range(len(overall))]
                Path(tmp, name, "summary.json").write_text(json.dumps({
                    "papers": papers, "scorecard": {"build": {"concepts_kept": 100.0}},
                    "comparable_on": {"questions": [version], "judge_model": "jev-1.13.0"}}))
                return str(Path(tmp, name))
            base = make("base", [60, 62, 58, 61, 59])
            better = make("better", [70, 71, 69, 72, 68])
            same = make("same", [61, 61, 59, 60, 60])
            args = lambda run, against: type("A", (), {"run": run, "against": against})()
            with contextlib.redirect_stdout(io.StringIO()):
                eval_run.compare(args(better, base))
                eval_run.compare(args(same, base))
            up = json.loads(Path(better, "compare-vs-base.json").read_text())["scores"]["overall"]
            self.assertEqual((up["reading"], up["change"]), ("better", 10.0))
            self.assertEqual(json.loads(Path(same, "compare-vs-base.json").read_text())["scores"]["overall"]["reading"], "no clear difference")
            other = make("other", [70, 71, 69, 72, 68], version="jev-eval-3")
            with self.assertRaises(SystemExit):
                eval_run.compare(args(other, base))  # different questions: not comparable

    def test_the_direction_check_catches_a_reversed_model(self):
        clean = self.judged()[1]
        self.assertTrue(any("|D|" in k for _, q in self.asked for k in q))
        self.assertFalse([c for c in clean["critical_errors"] if c["type"] == "reversed_model"])
        # The paper says every pair moves both ways at once, so whatever the model does, it says the opposite too.
        def ask(state, questions, timeout):
            out = {"_model": "fake"}
            for k, q in questions.items():
                if "|D|dir_paper" in k:
                    out[k] = {"type": "choice", "choice": "rises", "probabilities": {"rises": .9, "falls": .9}}
                elif "|A|" in k and eval_questions.PART_A[k.split("|")[2]].get("passed_when") == "no":
                    out[k] = {"type": "choice", "choice": "no", "probabilities": {"no": .9}}
                elif q["type"] == "choice":
                    out[k] = {"type": "choice", "choice": "yes", "probabilities": {"yes": .9}}
                else:
                    dim, _, j = k.split("|")[2].partition(".")
                    passing = "|B|" not in k or eval_questions.PART_B[dim]["checks"][int(j)].get("passed_when", "yes") == "yes"
                    out[k] = {"type": "noul", "noul": .95 if "|B|" in k and passing else .05}
            return out
        with patch.object(jev, "ask", side_effect=ask):
            judged = jev_judge.judge_lesson(EXAMPLE, self.source)
        r = jev_judge.combine(EXAMPLE, judged)
        reversed_ = [c for c in r["critical_errors"] if c["type"] == "reversed_model"]
        self.assertTrue(reversed_ and all(c["via"] == "dir_paper" and "the paper says" in c["detail"] for c in reversed_))
        self.assertEqual(r["verdict"], "dont_ship")
        self.assertLess(r["scores"]["models"], clean["scores"]["models"])
        self.assertEqual(r["scores"]["teaching"], clean["scores"]["teaching"])

    def test_a_quote_judged_unsupported_is_a_misleading_quote(self):
        _, r = self.judged(quote_no=True)
        self.assertTrue(all(c["type"] == "misleading_quote" and c["via"] == "A1" for c in r["critical_errors"]))
        self.assertEqual(len(r["critical_errors"]), len(EXAMPLE["concepts"]))

    def test_each_kind_has_its_own_threshold(self):
        _, r = self.judged(p_for={"misleading_quote": .6, "reversed_model": .95})
        kinds = {c["type"] for c in r["critical_errors"]}
        self.assertIn("misleading_quote", kinds)  # 0.6 clears the quote threshold of 0.55
        self.assertNotIn("reversed_model", kinds)  # the general reversed-model question only sends it to a person
        self.assertTrue(all(c["borderline"] for c in r["critical_errors"]))  # 0.6 is within 0.1 of 0.55
        self.assertTrue(any(x["what"].endswith("reversed_model") and x["why"].startswith("a possible") for x in r["needs_review"]))

    def test_a_planted_reversal_really_reverses_a_taught_output(self):
        lesson, where = eval_plant.plant(EXAMPLE, self.source, "reversed_model")
        c = next(x for x in lesson["concepts"] if x["id"] == where["concept"])
        before = next(x for x in EXAMPLE["concepts"] if x["id"] == where["concept"])
        flipped = {(d["control"], d["output"]): d["model"] for d in jev_judge.model_directions(c)}
        original = {(d["control"], d["output"]): d["model"] for d in jev_judge.model_directions(before)}
        self.assertTrue(any(flipped.get(k) not in (None, v) for k, v in original.items()), where)

    def test_a_combined_lessons_checks_see_every_source(self):
        bundle = json.dumps({"lemma_sources": [{"id": f"s{i}", "title": f"Source {i}", "url": "", "text": f"OPENING{i} " + "x " * 40000 + f" CLOSING{i}"}
                                               for i in (1, 2, 3)]})
        seen = jev_judge.lesson_evidence({"primer": []}, bundle)
        for i in (1, 2, 3):
            self.assertIn(f"OPENING{i}", seen)
            self.assertIn(f"CLOSING{i}", seen)
        self.assertLess(len(seen), jev_judge.LESSON_PAPER + 2000)

    def test_checks_that_dont_apply_are_not_asked(self):
        self.judged()
        asked = {k.split("|")[2] for _, q in self.asked for k in q if k.startswith("lesson|B|")}
        omitted_check = next(f"B5.{j}" for j, c in enumerate(eval_questions.PART_B["B5"]["checks"]) if c.get("when") == "omitted")
        self.assertNotIn(omitted_check, asked)  # the example leaves nothing out
        lesson = copy.deepcopy(EXAMPLE)
        lesson["omitted"] = [{"title": "A concept", "reason": "it failed"}]
        self.judged(lesson=lesson)
        self.assertIn(omitted_check, {k.split("|")[2] for _, q in self.asked for k in q if k.startswith("lesson|B|")})

    def test_the_paper_in_briefs_numbers_are_checked_one_at_a_time(self):
        lesson = copy.deepcopy(EXAMPLE)
        lesson["intro"]["summary"] = "Galton measured 928 adult children. The paper reports 4242 unicorns."
        items = jev_judge.brief_numbers(lesson, self.source)
        found = {x["number"]: x for x in items}
        self.assertIn("928", found["928"]["passage"])  # shown where the paper gives it
        self.assertIsNone(found["4242"]["passage"])  # the paper never prints this one
        _, r = self.judged(lesson=lesson, p_for={"num:2": .1})
        asked = [k for _, q in self.asked for k in q if "|N|" in k]
        self.assertEqual(len(asked), len(items))
        self.assertTrue(any(x["what"] == "lesson number 2" for x in r["needs_review"]))
        clean = self.judged(lesson=lesson)[1]["scores"]
        self.assertLess(r["scores"]["accuracy"], clean["accuracy"])

    def test_data_checks_measure_the_lesson_itself(self):
        c = copy.deepcopy(EXAMPLE["concepts"][0])
        c["animation"]["steps"] = [{"say": "This bar is the father.", "focus": "father", "ms": 2400},
                                   {"say": "Raise the father's height and watch the bar grow.", "set": {"father": 72}, "ms": 3000},
                                   {"say": "Now raise the mother too.", "ms": 2400},  # describes a change it doesn't make, points at nothing
                                   {"say": " ".join(["word"] * 45), "focus": "father"}]  # too long to take in
        c["understand"]["walkthrough"]["steps"] = []
        checks = jev_judge.data_checks({"concepts": [c]})
        self.assertEqual(checks["signaling"][c["id"]], .5)  # 2 of 4 steps point at something
        self.assertEqual(checks["contiguity"][c["id"]], .5)  # of the 2 steps describing a change, 1 makes it
        self.assertEqual(checks["apprehension"][c["id"]], .75)  # the 45-word step is too long
        self.assertEqual(checks["constructive"][c["id"]], 1.0)  # it has a 'Use it' question

    def test_jev_sees_the_quote_in_its_paper_context(self):
        quote = EXAMPLE["concepts"][0]["understand"]["quote"]
        context = jev_judge.quote_context(self.source, quote)
        self.assertIn(quote.split()[0], context)
        self.assertGreater(len(context), len(quote))

    def test_a_clean_lesson_ships(self):
        judged, r = self.judged()
        self.assertEqual(r["verdict"], "ship")
        self.assertEqual(r["critical_errors"], [])
        self.assertEqual(r["needs_review"], [])
        # every concept is asked with the paper and as taught, plus directions from the paper and from its teaching
        # when its model has an output that moves one way; the lesson twice more; and the paper in brief's numbers
        with_directions = sum(1 for c in EXAMPLE["concepts"] if jev_judge.model_directions(c))
        numbers = 1 if jev_judge.brief_numbers(EXAMPLE, self.source) else 0
        self.assertEqual(len(judged["requests"]), 2 * len(EXAMPLE["concepts"]) + 2 * with_directions + 2 + numbers)

    def test_most_lenses_confirm_a_critical_error(self):
        _, r = self.judged(yes_for=("|C|wrong_claim|",))
        self.assertEqual(r["verdict"], "dont_ship")
        self.assertEqual({c["type"] for c in r["critical_errors"]}, {"wrong_claim"})
        self.assertTrue(all(x["state"] and x["question"] for x in r["needs_review"]))  # a person sees what Jev saw

    def test_one_lens_alone_sends_it_to_a_person_without_failing_the_lesson(self):
        _, r = self.judged(split=("|C|wrong_claim|",))
        self.assertEqual(r["critical_errors"], [])
        self.assertEqual(r["verdict"], "ship")
        self.assertTrue(r["needs_review"] and all(x["why"].startswith("a possible critical error") for x in r["needs_review"]))


if __name__ == "__main__":
    unittest.main()
