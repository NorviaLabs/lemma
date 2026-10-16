"""Run with: python -m unittest discover tests"""

from __future__ import annotations

import base64
import copy
import hashlib
import http.client
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP_HOME = tempfile.mkdtemp(prefix="lemma-test-")
os.environ["LEMMA_HOME"] = TMP_HOME

from lemma import auth, chatgpt, claude, dev, expr, export, generate, ingest, kernels, lesson as L, llm, search, server, store  # noqa: E402
from lemma.llm import Provider, Reply  # noqa: E402

EXAMPLE = json.loads((ROOT / "lemma/examples/galton-1886.json").read_text())
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

    def test_non_finite_does_not_raise(self):
        self.assertEqual(expr.evaluate("1/0", {}), float("inf"))
        self.assertNotEqual(expr.evaluate("sqrt(-1)", {}), expr.evaluate("sqrt(-1)", {}))  # nan


@unittest.skipUnless(shutil.which("node"), "node is needed to compare with the browser engine")
class BrowserParityTests(unittest.TestCase):
    def test_kernels_and_expressions_match_javascript(self):
        cases = {
            "kernels": [["schelling", {"tolerance": 0.5}], ["sir", {"vaccinated": 0.3}], ["opinion", {}], ["network", {"rule": 1}],
                        ["mean", {"n": 5}], ["two_group", {"mu2": 0.4}], ["regression", {"r": 0.6, "seed": 54, "people": 1000}]],
            "exprs": [["normcdf(x, 1, 2) + norminv(0.3) * binom(7, 3)", {"x": 0.4}], ["round(2.345, 2) - 7 % 3", {}], ["a == 0.3", {"a": 0.1 + 0.2}]],
        }
        out = subprocess.run(["node", str(ROOT / "tests/crosscheck.js")], input=json.dumps(cases), capture_output=True, text=True, check=True)
        js = json.loads(out.stdout)
        for (k, p), jm in zip(cases["kernels"], js["kernels"]):
            for key, v in kernels.run(k, p).items():
                self.assertAlmostEqual(v, jm[key], places=12, msg=f"{k}.{key}")
        for (e, env), jv in zip(cases["exprs"], js["exprs"]):
            self.assertAlmostEqual(expr.evaluate(e, env), jv, places=12, msg=e)


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

    def send(self, text, cancelled=None):
        with self.p.lock:
            self.p.calls += 1
        self.turns += 1
        if self.turns == 1:
            self.task = text
        return self.p.reply(self.task, self.turns)

    def close(self):
        with self.p.lock:
            self.p.closed += 1


class FakeProvider(Provider):
    """Answers like a model would: an outline, then concepts; the first draft of one concept has a bad quote."""

    id, name, model, label = "fake", "Fake", "fake-1", "Fake"

    def __init__(self):
        self.calls = 0
        self.closed = 0
        self.lock = threading.Lock()

    def available(self):
        return True, ""

    def conversation(self, system, document):
        assert "LESSON FORMAT" in system and document.startswith("<paper>")
        return FakeConversation(self, document)

    def reply(self, task, turn):
        if "propose a path" in task.lower():
            return Reply(json.dumps({
                "title": EXAMPLE["title"], "source": {"title": EXAMPLE["source"]["title"], "authors": "Francis Galton", "year": 1886, "venue": None},
                "summary": EXAMPLE["intro"]["summary"], "background": EXAMPLE["intro"]["background"], "aha": EXAMPLE["intro"]["aha"],
                "primer": EXAMPLE["primer"],
                "concepts": [{"id": c["id"], "title": c["title"], "idea": c["idea"], "role": c["role"], "visual": c["model"]["visual"]["type"], "why": "fits", "hard": c.get("hard", False)} for c in EXAMPLE["concepts"]],
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

    def test_only_hard_concepts_keep_a_check(self):
        fp = FakeProvider()
        outline = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "")).result
        job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, {"text": SOURCE, "title": "", "url": ""}, outline, ""))
        checked = [c["id"] for c in job.result["concepts"] if c.get("check")]
        self.assertEqual(checked, ["why_regression"])
        outline["concepts"] = [dict(c, hard=True) for c in outline["concepts"]]
        self.assertIn("mark at most two concepts as hard", generate.check_outline(outline))

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
     "abstract_inverted_index": {"Children": [0], "regress": [1]}},
    {"display_name": "Very relevant, rarely cited", "publication_year": 2020, "cited_by_count": 0, "relevance_score": 12,
     "best_oa_location": {"pdf_url": "https://pub.example/b.pdf"}},
    {"display_name": "No open copy", "best_oa_location": None, "locations": []},
]}
ARXIV = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1234.5678v1</id>
<title>A small but famous paper</title><published>2004-01-01</published><summary>dup</summary></entry>
<entry><id>http://arxiv.org/abs/2222.0001v2</id><title>A preprint</title><published>2021-05-01</published>
<author><name>Z</name></author><summary>About   things.</summary></entry></feed>"""
WIKI = {"query": {"search": [{"title": "Regression toward the mean", "snippet": "In <span>statistics</span> &amp; more"}]}}


class SearchTests(unittest.TestCase):
    def setUp(self):
        search._cache.clear()
        self.urls = []
        self.orig = search._get

        def fake(url, retry=True):
            self.urls.append(url)
            if "openalex" in url:
                return json.dumps(OPENALEX).encode()
            if "arxiv" in url:
                return ARXIV
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
        self.assertEqual(famous["summary"], "Children regress")
        # Every open copy, full text before DOI landing pages, junk links dropped.
        self.assertEqual(famous["urls"], ["https://pub.example/blocked.pdf", "https://archive.example/x", "https://doi.org/10.1/x"])
        self.assertEqual(pre["url"], "https://arxiv.org/abs/2222.0001v2")  # the duplicate preprint was dropped
        self.assertEqual(r["unavailable"], [])
        self.assertTrue(all("query" not in u or "regression" in u for u in self.urls))

    def test_a_service_that_fails_is_reported_not_fatal(self):
        def failing(url, retry=True):
            if "arxiv" in url:
                raise TimeoutError()
            return self.orig_fake(url)
        self.orig_fake = search._get
        search._get = failing
        r = search.search("x")
        self.assertEqual(r["unavailable"], ["arXiv"])
        self.assertEqual(len(r["results"]), 3)

    def test_bad_queries(self):
        with self.assertRaises(search.SearchError):
            search.search("   ")
        with self.assertRaises(search.SearchError):
            search.search("x" * 201)

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
        FakeAPI.calls.append({"path": self.path, "body": body})
        if not self._authorized():
            return
        last = body["messages"][-1]["content"]
        if "FAIL" in last:
            return self._reply(429, {"error": {"message": "quota exceeded"}})
        if "LONG" in last:
            return self._reply(400, {"error": {"message": "too many tokens", "code": "context_length_exceeded"}})
        turn = sum(m["role"] == "assistant" for m in body["messages"]) + 1
        finish = "length" if "CUT" in last else "stop"
        self._reply(200, {"choices": [{"message": {"role": "assistant", "content": json.dumps({"turn": turn, "model": body["model"]})}, "finish_reason": finish}]})


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

    def test_models_and_errors(self):
        self.assertEqual([m["id"] for m in self.p.models()], ["glm-5.3", "gpt-6.1-sol"])  # embeddings left out
        conv = self.p.conversation("S", "<paper>x</paper>")
        with self.assertRaisesRegex(llm.ProviderError, "quota exceeded"):
            conv.send("FAIL please")
        with self.assertRaisesRegex(llm.ProviderError, "too long for gpt-6.1-sol"):
            conv.send("LONG")
        with self.assertRaisesRegex(llm.ProviderError, "rejected the key"):
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
        self.assertEqual(first["cache_control"], {"type": "ephemeral"})
        self.assertEqual(first["output_config"], {"effort": "high"})
        self.assertEqual(first["fallbacks"], "default")
        self.assertIn(claude.FALLBACK_BETA, FakeAnthropic.calls[0]["headers"]["anthropic-beta"])
        self.assertEqual([m["role"] for m in second["messages"]], ["user", "user", "assistant", "user"])
        self.assertEqual([b["type"] for b in second["messages"][2]["content"]], ["thinking", "text"])  # sent back as Claude sent it
        self.assertEqual(second["messages"][2]["content"][0]["signature"], "sig")
        self.assertEqual(conv.send("CUT").stop_reason, "max_tokens")

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
        with self.assertRaisesRegex(llm.ProviderError, "rejected the key"):
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

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"localhost:{self.port}"}
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
        s, raw = self.req("GET", "/static/fonts/atkinson-hyperlegible-next-latin-normal.woff2")
        self.assertEqual(s, 200)
        self.assertEqual(raw[:4], b"wOF2")
        self.assertEqual(self.req("GET", "/static/fonts/../styles.css")[0], 404)
        s, raw = self.req("GET", "/privacy")
        self.assertEqual(s, 200)
        self.assertIn(b"never writes it to disk", raw)

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
        self.assertEqual(self.req("GET", "/api/status", headers={"X-Lemma-Provider": "nope"})[0], 400)

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
        server.SOURCES[(None, "abc123")] = SOURCE
        self.assertEqual(self.req("POST", "/api/lessons", {"lesson": built})[0], 200)
        listing = json.loads(self.req("GET", "/api/lessons")[1])
        self.assertIn("abc123", [x["id"] for x in listing])
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


class HostedServerTests(unittest.TestCase):
    def tearDown(self):
        server.HOSTED, server.ALLOWED_HOSTS = False, server.LOCAL_HOSTS

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
            self.assertNotIn("chatgpt", [p["id"] for p in json.loads(raw)["providers"]])
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
            # Lemma serves under the public URL's path too, as it does behind Cloudflare Tunnel.
            self.assertEqual(req("GET", "/lemma/api/example")[0], 200)
            s, _, r = req("GET", "/lemma")
            self.assertEqual((s, r.getheader("Location")), (301, "/lemma/"))
            # Signed out: the example works, nothing else does.
            self.assertEqual(req("GET", "/api/example")[0], 200)
            for method, path, body in [("GET", "/api/lessons", None), ("POST", "/api/search", {"query": "x"}), ("POST", "/api/papers", {"url": "https://example.com"})]:
                self.assertEqual(req(method, path, body)[0], 401, path)
            st = json.loads(req("GET", "/api/status")[1])
            self.assertEqual((st["hosted"], st["user"], st["sign_in"]), (True, None, [{"id": "google", "name": "Google"}]))

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
            server.SOURCES[(ada["id"], "adas01")] = SOURCE
            self.assertEqual(req("POST", "/api/lessons", {"lesson": lesson}, tb)[0], 409)  # Bob can't save Ada's build
            self.assertEqual(req("POST", "/api/lessons", {"lesson": lesson}, ta)[0], 200)
            self.assertEqual([x["id"] for x in json.loads(req("GET", "/api/lessons", token=ta)[1])], ["adas01"])
            self.assertEqual(json.loads(req("GET", "/api/lessons", token=tb)[1]), [])
            self.assertEqual(req("GET", "/api/lessons/adas01", token=tb)[0], 404)
            req("DELETE", "/api/lessons/adas01", token=tb)
            self.assertEqual(req("GET", "/api/lessons/adas01", token=ta)[0], 200)  # Bob's delete didn't touch it

            job = generate.Job("build")
            job.owner = ada["id"]
            generate.JOBS[job.id] = job
            self.assertEqual(req("GET", f"/api/jobs/{job.id}", token=ta)[0], 200)
            self.assertEqual(req("GET", f"/api/jobs/{job.id}", token=tb)[0], 404)

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


class ExportTests(unittest.TestCase):
    def test_fonts_are_embedded_not_linked(self):
        html = export.lesson_html(EXAMPLE)
        style = html.split("<style>")[1].split("</style>")[0]
        self.assertIn("font-src data:", html)
        self.assertEqual(style.count("data:font/woff2;base64,"), 3)  # every face embedded
        self.assertNotIn('url("fonts/', style)

    def test_embedded_json_cannot_break_out(self):
        les = copy.deepcopy(EXAMPLE)
        les["title"] = "</script><script>alert(1)</script>"
        html = export.lesson_html(les)
        self.assertEqual(html.count("</script>"), 6)  # lesson data + 4 scripts + boot
        self.assertIn("&lt;/script&gt;", html.split("<title>")[1].split("</title>")[0])


if __name__ == "__main__":
    unittest.main()
