"""Run with: python -m unittest discover tests"""

from __future__ import annotations

import copy
import http.client
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP_HOME = tempfile.mkdtemp(prefix="lemma-test-")
os.environ["LEMMA_HOME"] = TMP_HOME

from lemma import dev, expr, export, generate, ingest, kernels, lesson as L, llm, search, server  # noqa: E402
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


class OpenCodeProviderTests(unittest.TestCase):
    """Runs the real provider against tests/fake_opencode.py instead of the opencode program."""

    def setUp(self):
        self.log = Path(TMP_HOME) / "fake_oc.log"
        self.log.write_text("")
        os.environ["FAKE_OC_LOG"] = str(self.log)
        self.auth = Path(TMP_HOME) / "xdg"
        (self.auth / "opencode").mkdir(parents=True, exist_ok=True)
        (self.auth / "opencode/auth.json").write_text(json.dumps({"opencode-go": {"type": "api", "key": "secret"}}))
        os.environ["XDG_DATA_HOME"] = str(self.auth)
        self.p = llm.OpenCodeGoProvider(model="glm-5.3", opencode_path=str(ROOT / "tests/fake_opencode.py"))

    def tearDown(self):
        llm.shutdown()
        os.environ.pop("XDG_DATA_HOME", None)

    def events(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()]

    def test_conversation_runs_through_a_private_server_and_cleans_up(self):
        self.assertEqual(self.p.available(), (True, ""))
        conv = self.p.conversation("SYSTEM", "<paper>text</paper>")
        r1 = conv.send("task")
        r2 = conv.send("repair")
        conv.close()
        self.assertEqual(json.loads(r1.text), {"turn": 1, "model": "glm-5.3"})
        self.assertEqual(json.loads(r2.text)["turn"], 2)  # same session: the repair sees the history
        ev = self.events()
        self.assertEqual([e["event"] for e in ev], ["message", "message", "delete"])
        self.assertEqual(ev[0]["nparts"], 2)  # the paper goes only with the first message
        self.assertEqual(ev[1]["nparts"], 1)
        self.assertTrue(all(e["agent"] == "lemma" and e["model"]["providerID"] == "opencode-go" for e in ev[:2]))
        srv = llm._server
        with self.assertRaises(llm.ProviderError):  # the server refuses anyone without the password
            srv.password, real = "wrong", srv.password
            try:
                srv.request("GET", "/agent")
            finally:
                srv.password = real

    def test_models_and_errors(self):
        self.assertEqual([m["id"] for m in self.p.models()], ["glm-5.3", "gpt-5.6-luna"])  # deprecated hidden
        conv = self.p.conversation("S", "<paper>x</paper>")
        with self.assertRaisesRegex(llm.ProviderError, "quota exceeded"):
            conv.send("FAIL please")
        conv.close()

    def test_missing_install_or_login_is_reported(self):
        self.assertEqual(llm.find_opencode(str(ROOT / "tests/fake_opencode.py")), str(ROOT / "tests/fake_opencode.py"))
        self.assertNotEqual(llm.find_opencode("/nope/opencode"), "/nope/opencode")
        orig = llm.find_opencode
        llm.find_opencode = lambda path=None: None
        try:
            ok, msg = llm.OpenCodeGoProvider().available()
        finally:
            llm.find_opencode = orig
        self.assertFalse(ok)
        self.assertIn("isn't installed", msg)
        (self.auth / "opencode/auth.json").write_text("{}")
        ok, msg = self.p.available()
        self.assertFalse(ok)
        self.assertIn("opencode providers login", msg)


class CodexProviderTests(unittest.TestCase):
    """Runs the real Codex provider against tests/fake_codex.py instead of the codex program."""

    def setUp(self):
        self.log = Path(TMP_HOME) / "fake_codex.log"
        self.log.write_text("")
        os.environ["FAKE_CODEX_LOG"] = str(self.log)
        os.environ["FAKE_CODEX_LOGGED_IN"] = "1"
        llm._codex_login.clear()
        self.p = llm.CodexProvider(model="gpt-6.1-sol", codex_path=str(ROOT / "tests/fake_codex.py"))

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()]

    def test_locked_down_one_off_runs_with_history_resent(self):
        self.assertEqual(self.p.available(), (True, ""))
        conv = self.p.conversation("SYSTEM PROMPT", "<paper>the paper</paper>")
        self.assertEqual(json.loads(conv.send("task").text), {"turn": 1, "model": "gpt-6.1-sol"})
        self.assertEqual(json.loads(conv.send("fix these").text)["turn"], 2)
        first, second = self.calls()
        args = first["args"]
        for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--json"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--sandbox") + 1], "read-only")
        disabled = {args[i + 1] for i, a in enumerate(args) if a == "--disable"}
        self.assertTrue({"shell_tool", "unified_exec", "code_mode_host", "multi_agent", "apps", "plugins", "computer_use", "browser_use", "memories"} <= disabled)
        configs = [args[i + 1] for i, a in enumerate(args) if a == "-c"]
        self.assertIn('web_search="disabled"', configs)
        self.assertIn('approval_policy="never"', configs)
        self.assertIn('developer_instructions="SYSTEM PROMPT"', configs)
        self.assertTrue(first["prompt"].startswith("<paper>the paper</paper>"))
        # Nothing is kept by Codex, so the repair re-sends the paper, the task and the first reply.
        self.assertIn("task", second["prompt"])
        self.assertIn('{"turn": 1, "model": "gpt-6.1-sol"}', second["prompt"])
        self.assertTrue(second["prompt"].rstrip().endswith("fix these"))

    def test_errors_models_and_limits(self):
        self.assertEqual([m["id"] for m in self.p.models()], ["gpt-6.1-sol", "tiny"])  # hidden ones left out
        with self.assertRaisesRegex(llm.ProviderError, "usage limit reached"):
            self.p.conversation("S", "<paper>x</paper>").send("FAIL")
        tiny = llm.CodexProvider(model="tiny", codex_path=str(ROOT / "tests/fake_codex.py"))
        with self.assertRaisesRegex(llm.ProviderError, "too long for tiny"):
            tiny.conversation("S", "<paper>" + "word " * 2000 + "</paper>").send("task")
        os.environ["FAKE_CODEX_LOGGED_IN"] = "0"
        llm._codex_login.clear()
        ok, msg = self.p.available()
        self.assertFalse(ok)
        self.assertIn("codex login", msg)

    def test_settings_switch_provider_and_migrate_old_keys(self):
        from lemma import store

        store.save_settings({"model": "glm-5.3", "opencode_path": "", "provider": "opencode-go"})
        st = server.api_settings({"provider": "codex", "model": "gpt-6-luna", "path": str(ROOT / "tests/fake_codex.py")})
        self.assertEqual(st["provider"]["id"], "codex")
        self.assertEqual(st["provider"]["model"], "gpt-6-luna")
        saved = store.load_settings()
        self.assertEqual(saved["models"], {"opencode-go": "glm-5.3", "codex": "gpt-6-luna"})
        self.assertNotIn("model", saved)
        self.assertEqual(llm.make_provider(saved, "opencode-go").model, "glm-5.3")
        with self.assertRaises(server.ApiError):
            server.api_settings({"provider": "codex", "path": "/nope/codex"})
        store.save_settings({})


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
        s, raw = self.req("GET", "/static/fonts/barlow-latin-400-normal.woff2")
        self.assertEqual(s, 200)
        self.assertEqual(raw[:4], b"wOF2")
        self.assertEqual(self.req("GET", "/static/fonts/../styles.css")[0], 404)

    def test_status_reports_setup_steps_and_library(self):
        s, raw = self.req("POST", "/api/status/refresh", {})
        self.assertEqual(s, 200)
        st = json.loads(raw)
        self.assertIn("library_count", st)
        for p in st["providers"]:
            self.assertIn(p["id"], ("opencode-go", "codex"))
            self.assertIsInstance(p["installed"], bool)
            self.assertIsInstance(p["signed_in"], bool)
            if p["ok"]:
                self.assertTrue(p["installed"] and p["signed_in"])

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
        server.SOURCES["abc123"] = SOURCE
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
            self.assertIn(b'<script src="/static/dev-reload.js"></script>', get("/")[1])
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
        self.assertEqual(style.count("data:font/woff2;base64,"), 7)  # every face embedded
        self.assertNotIn('url("fonts/', style)

    def test_embedded_json_cannot_break_out(self):
        les = copy.deepcopy(EXAMPLE)
        les["title"] = "</script><script>alert(1)</script>"
        html = export.lesson_html(les)
        self.assertEqual(html.count("</script>"), 6)  # lesson data + 4 scripts + boot
        self.assertIn("&lt;/script&gt;", html.split("<title>")[1].split("</title>")[0])


if __name__ == "__main__":
    unittest.main()
