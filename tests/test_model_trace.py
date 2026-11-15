"""A trace on the concept's own causal model: `"on": "model"`.

Such a trace has no `nodes` or `edges` of its own. Its answer names the model's node ids, a path answer follows the
model's edges in order, and the player draws a copy of the model's causal visual inside the activity for the learner
to pick nodes on. These tests cover the lesson checks, saving, the offline download, Jev's fact-check text, the
generation guide and the gallery (Python); picking on the copy (tests/model_trace.js, needs node); and the player and
the downloaded lesson in a real browser (tests/model_trace_ui.mjs, needs node, `npm ci` and Chrome or Chromium).
"""
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import fakejev  # noqa: F401  Jev is essential, so every search and build asks this stand-in
from support import call
from lemma import export, factcheck, lesson as L, server

ROOT = Path(__file__).resolve().parents[1]
GALLERY = ROOT / "lemma/examples/gallery"

# The problems the checks report, pinned so each rejection is for the right reason.
NO_MODEL = "a trace on the model needs the concept's model"
NOT_CAUSAL = "a trace on the model needs a causal visual"
NODE_COUNT = "a trace on the model needs a causal model with 3–10 nodes"
DUPLICATE_IDS = "a trace on the model needs the model's nodes to have unique ids"
OWN_DIAGRAM = "a trace on the model takes its nodes and edges from the model, so it can't have its own"
BAD_ON = "on must be \"model\", or left out for a trace with its own diagram"
BAD_ANSWER = "answer must list distinct node ids of the model"
OFF_EDGES = "a path answer must follow the model's edges, in order"

LOOP_PROMPT = "Starting from the warming, trace the loop until it feeds back into warming."
LOOP_EXPLANATION = "Warming shrinks the ice, less ice bounces back less sunlight, so more is soaked up, which warms the planet again."


def gallery_json(slug: str) -> dict:
    return json.loads((GALLERY / f"{slug}.json").read_text())


def concept_of(lesson: dict, cid: str) -> dict:
    return next(c for c in lesson["concepts"] if c["id"] == cid)


def model_trace(**extra) -> dict:
    """A valid trace along the ice–albedo loop: warming → ice → sunlight bounced away → sunlight soaked up."""
    a = {"id": "loop", "kind": "trace", "on": "model", "prompt": LOOP_PROMPT, "path": True,
         "answer": ["temp", "ice", "reflect", "absorb"], "explanation": LOOP_EXPLANATION}
    a.update(extra)
    return a


def loop_concept(trace: dict | None = None) -> dict:
    """The ice–albedo loop concept (a causal model with 5 nodes and 5 edges), with a model trace after its teaching.

    Any trace the gallery lesson already has is taken out first, so the fixture is the same before and after."""
    c = copy.deepcopy(concept_of(gallery_json("ice-albedo-feedback"), "ice_albedo_loop"))
    c["activities"] = [a for a in c["activities"] if a["kind"] != "trace"]
    at = [a["id"] for a in c["activities"]].index("idea") + 1
    c["activities"].insert(at, trace if trace is not None else model_trace())
    return c


def trace_index(c: dict, aid: str = "loop") -> int:
    return [a.get("id") for a in c["activities"]].index(aid)


def problems(c: dict) -> list[str]:
    return list(L.check_concept(c, None))


def trace_problems(c: dict, aid: str = "loop") -> list[str]:
    """The problems reported at the trace itself, without their location."""
    where = f"concept.activities[{trace_index(c, aid)}]: "
    return [p[len(where):] for p in problems(c) if p.startswith(where)]


def resize(c: dict, n: int):
    """Give the concept's causal model n nodes: the loop's own first, then extra nodes joined in a chain.

    Dropped nodes take their edges, and any narration that points at them, with them."""
    vis = c["model"]["visual"]
    nodes = vis["nodes"][:n]
    for k in range(len(nodes), n):
        nodes.append({"id": f"extra_{k}", "label": f"Extra {k}", "x": (k * 9) % 100, "y": 95})
    ids = {x["id"] for x in nodes}
    edges = [e for e in vis["edges"] if e["from"] in ids and e["to"] in ids]
    for k in range(5, n):
        edges.append({"from": nodes[k - 1]["id"], "to": nodes[k]["id"], "strength": 0.5})
    vis["nodes"], vis["edges"] = nodes, edges
    for steps in (c.get("animation", {}).get("steps", []), c.get("understand", {}).get("walkthrough", {}).get("steps", [])):
        for st in steps:
            f = st.get("focus")
            if f is not None:
                kept = [x for x in (f if isinstance(f, list) else [f]) if not (x in {"push", "temp", "ice", "reflect", "absorb"} and x not in ids)]
                if kept:
                    st["focus"] = kept
                else:
                    st.pop("focus")


class AcceptedTraces(unittest.TestCase):
    """A. Valid traces on the model pass every check."""

    def test_fixture_without_the_trace_is_valid(self):
        # The base the other tests change: the shipped concept passes on its own.
        c = loop_concept()
        c["activities"].pop(trace_index(c))
        self.assertEqual(problems(c), [])

    def test_1_set_answer_names_some_model_nodes(self):
        c = loop_concept(model_trace(path=False, answer=["push", "reflect"]))
        self.assertEqual(problems(c), [])
        c = loop_concept(model_trace(answer=["ice", "reflect"]))
        del c["activities"][trace_index(c)]["path"]
        self.assertEqual(problems(c), [])

    def test_2_path_answer_follows_the_model_edges_in_order(self):
        self.assertEqual(problems(loop_concept(model_trace(answer=["push", "temp", "ice"]))), [])

    def test_3_path_may_run_round_the_models_loop_without_repeating_a_node(self):
        self.assertEqual(problems(loop_concept(model_trace(answer=["push", "temp", "ice", "reflect", "absorb"]))), [])
        self.assertEqual(problems(loop_concept(model_trace(answer=["ice", "reflect", "absorb", "temp"]))), [])

    def test_4_values_in_range_including_a_toggle(self):
        self.assertEqual(problems(loop_concept(model_trace(values={"g": 0.6, "hold": 1}))), [])

    def test_5_without_values(self):
        c = loop_concept()
        self.assertNotIn("values", c["activities"][trace_index(c)])
        self.assertEqual(problems(c), [])

    def test_6_three_and_ten_nodes_are_the_limits_that_pass(self):
        for n, answer in ((3, ["push", "temp", "ice"]), (10, ["reflect", "absorb", "temp"])):
            with self.subTest(nodes=n):
                c = loop_concept(model_trace(answer=answer))
                resize(c, n)
                self.assertEqual(len(c["model"]["visual"]["nodes"]), n)
                self.assertEqual(problems(c), [])

    def test_7_hints_and_hypothetical_work_as_on_any_response_block(self):
        c = loop_concept(model_trace(hints=["Start at the warming.", "Ice comes next."], hypothetical=True))
        self.assertEqual(problems(c), [])
        c["activities"][trace_index(c)]["hints"] = ["a", "b", "c", "d"]
        self.assertEqual(trace_problems(c), ["hints must be 1–3 lines that get more specific"])

    def test_7b_one_node_path_is_allowed_as_today(self):
        self.assertEqual(problems(loop_concept(model_trace(answer=["temp"]))), [])

    def test_8_two_model_traces_in_one_concept_are_each_checked(self):
        c = loop_concept()
        second = model_trace(id="melt", path=False, answer=["ice", "absorb"], values={"hold": 1})
        c["activities"].insert(trace_index(c) + 1, second)
        self.assertEqual(problems(c), [])
        second["answer"] = ["ice", "glacier"]
        found = trace_problems(c, "melt")
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith(BAD_ANSWER), found)
        self.assertEqual(trace_problems(c, "loop"), [])

    def test_9_a_whole_lesson_with_a_model_trace_passes(self):
        lesson = gallery_json("ice-albedo-feedback")
        at = [c["id"] for c in lesson["concepts"]].index("ice_albedo_loop")
        lesson["concepts"][at] = loop_concept()
        self.assertEqual(list(L.check_lesson(lesson, None)), [])

    def test_10_authored_traces_are_checked_as_before(self):
        # Regression: a trace with its own diagram keeps today's rules and messages.
        c = loop_concept({"id": "loop", "kind": "trace", "prompt": "Trace it.", "path": True, "explanation": "Each step is one link.",
                          "nodes": [{"id": "a", "label": "A", "x": 10, "y": 50}, {"id": "b", "label": "B", "x": 50, "y": 50}, {"id": "d", "label": "D", "x": 90, "y": 50}],
                          "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "d"}], "answer": ["a", "b", "d"]})
        self.assertEqual(problems(c), [])
        c["activities"][trace_index(c)]["answer"] = ["a", "d"]
        self.assertEqual(trace_problems(c), ["a path answer must follow the edges, in order"])
        c["activities"][trace_index(c)]["nodes"].pop()
        self.assertIn("needs 3–10 nodes", trace_problems(c))


class RejectedTraces(unittest.TestCase):
    """B. Each invalid trace on the model is refused for its own reason, and the checks never crash."""

    def assertOnly(self, c, message, aid="loop", elsewhere=True):
        """The trace has exactly one problem, starting with `message`; with `elsewhere`, the concept has no others."""
        found = trace_problems(c, aid)
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith(message), found)
        if elsewhere:
            self.assertEqual(len(problems(c)), 1, problems(c))

    def test_11_concept_without_a_model(self):
        # A concept taught without a live model: its explanation, then the trace.
        c = loop_concept()
        del c["model"]
        c["activities"] = [{"id": "idea", "kind": "explain"}, model_trace()]
        self.assertOnly(c, NO_MODEL)

    def test_12_model_whose_visual_is_not_causal(self):
        seen = set()
        for slug in ("ice-albedo-feedback", "galton-1886", "schelling-segregation", "ioannidis-2005", "wave-interference", "euclid-equilateral"):
            lesson, _ = server.load_gallery(slug)
            for c in lesson["concepts"]:
                kind = (c.get("model") or {}).get("visual", {}).get("type")
                if kind in (None, "causal", "network") or kind in seen:
                    continue
                seen.add(kind)
                c = copy.deepcopy(c)
                at = [a["kind"] for a in c["activities"]].index("explain") + 1
                c["activities"].insert(at, model_trace())
                with self.subTest(visual=kind):
                    self.assertOnly(c, NOT_CAUSAL)
        self.assertTrue({"curves", "bars", "table", "agents", "sampling", "geometry"} <= seen, seen)

    def test_13_network_model(self):
        c = loop_concept()
        c["model"]["visual"] = {"type": "network", "kernel": "network", "params": {"threshold": 0.3}}
        self.assertOnly(c, NOT_CAUSAL, elsewhere=False)

    def test_14_more_than_ten_nodes(self):
        c = loop_concept()
        resize(c, 11)
        self.assertEqual([p for p in problems(c) if "model" in p.split(":")[0]], [])  # the model itself is fine
        self.assertOnly(c, NODE_COUNT)

    def test_15_fewer_than_three_nodes(self):
        for n, answer in ((2, ["push", "temp"]), (1, ["push"])):
            with self.subTest(nodes=n):
                c = loop_concept(model_trace(answer=answer))
                resize(c, n)
                self.assertOnly(c, NODE_COUNT, elsewhere=False)

    def test_16_answer_names_a_node_the_model_does_not_have(self):
        self.assertOnly(loop_concept(model_trace(answer=["temp", "glacier"])), BAD_ANSWER)
        self.assertOnly(loop_concept(model_trace(path=False, answer=["temp", "glacier"])), BAD_ANSWER)

    def test_17_path_skips_a_link(self):
        self.assertOnly(loop_concept(model_trace(answer=["temp", "reflect"])), OFF_EDGES)

    def test_5a_an_unknown_node_is_reported_with_the_models_node_ids(self):
        # The ids live in the model's visual, not the trace, so the message says what they are.
        self.assertEqual(trace_problems(loop_concept(model_trace(answer=["temp", "Ice cover"]))),
                         [f"{BAD_ANSWER} (its nodes are push, temp, ice, reflect, absorb)"])

    def test_5b_a_path_off_the_edges_names_the_first_missing_link(self):
        self.assertEqual(trace_problems(loop_concept(model_trace(answer=["temp", "ice", "absorb"]))),
                         [f"{OFF_EDGES}; there is no edge from ice to absorb"])
        self.assertEqual(trace_problems(loop_concept(model_trace(answer=["ice", "temp"]))),
                         [f"{OFF_EDGES}; there is no edge from ice to temp"])

    def test_18_path_runs_against_an_edge(self):
        self.assertOnly(loop_concept(model_trace(answer=["ice", "temp"])), OFF_EDGES)

    def test_19_answer_empty_not_a_list_or_repeated(self):
        for answer in ([], "temp", None, ["temp", "ice", "temp"], [1, 2]):
            with self.subTest(answer=answer):
                self.assertOnly(loop_concept(model_trace(path=False, answer=answer)), BAD_ANSWER)

    def test_20_trace_with_its_own_nodes_or_edges(self):
        nodes = [{"id": "temp", "label": "T", "x": 10, "y": 50}, {"id": "ice", "label": "I", "x": 50, "y": 50}, {"id": "reflect", "label": "R", "x": 90, "y": 50}]
        edges = [{"from": "temp", "to": "ice"}]
        for extra in ({"nodes": nodes}, {"edges": edges}, {"nodes": nodes, "edges": edges}, {"edges": []}):
            with self.subTest(extra=list(extra)):
                self.assertOnly(loop_concept(model_trace(**extra)), OWN_DIAGRAM)

    def test_21_on_names_something_else(self):
        for on in ("network", True, "diagram", "", "Model"):
            with self.subTest(on=on):
                self.assertOnly(loop_concept(model_trace(on=on)), BAD_ON)

    def test_22_bad_values(self):
        cases = {
            "empty": ({}, "values must set at least one control"),
            "not an object": ([0.5], "values must set at least one control"),
            "unknown control": ({"zz": 1}, "'zz' is not a control of the model"),
            "out of range": ({"g": 5}, "'g' must be a number within its control's range"),
            "not a number": ({"g": "high"}, "'g' must be a number within its control's range"),
        }
        for name, (values, message) in cases.items():
            with self.subTest(name):
                self.assertOnly(loop_concept(model_trace(values=values)), message)

    def test_23_prompt_or_explanation_missing(self):
        for key in ("prompt", "explanation"):
            with self.subTest(key):
                trace = model_trace()
                del trace[key]
                self.assertOnly(loop_concept(trace), f"needs '{key}' text")

    def test_24_broken_causal_visual_is_reported_not_crashed_on(self):
        for name, nodes in (("missing", None), ("strings", ["a", "b", "c"]), ("an object", {"a": 1}), ("a number", 5)):
            with self.subTest(nodes=name):
                c = loop_concept()
                if nodes is None:
                    del c["model"]["visual"]["nodes"]
                else:
                    c["model"]["visual"]["nodes"] = nodes
                found = trace_problems(c)  # must not raise
                self.assertEqual(len(found), 1, found)
                self.assertTrue(found[0].startswith(NODE_COUNT), found)
                self.assertTrue(any(p.startswith("concept.model.visual") for p in problems(c)))

    def test_24b_duplicate_node_ids_in_the_model(self):
        c = loop_concept()
        c["model"]["visual"]["nodes"].append({"id": "ice", "label": "More ice", "x": 50, "y": 95})
        self.assertOnly(c, DUPLICATE_IDS, elsewhere=False)

    def test_25_teach_before_practice_still_applies(self):
        c = loop_concept()
        c["activities"].insert(0, c["activities"].pop(trace_index(c)))
        self.assertEqual(problems(c), ["concept.activities[0]: teach before practice"])

    def test_26_an_edited_lesson_with_a_bad_model_trace_is_not_saved(self):
        # Saving an edit (and downloading) runs server.core.require_valid, which refuses a lesson that fails its checks.
        lesson = gallery_json("ice-albedo-feedback")
        at = [c["id"] for c in lesson["concepts"]].index("ice_albedo_loop")
        lesson["concepts"][at] = loop_concept()
        server.core.require_valid(lesson, None)  # a good edit is accepted
        lesson["concepts"][at] = loop_concept(model_trace(answer=["temp", "reflect"]))
        with self.assertRaises(server.ApiError) as refused:
            server.core.require_valid(lesson, None)
        self.assertEqual(refused.exception.status, 422)
        self.assertTrue(any(p.split(": ", 1)[1].startswith(OFF_EDGES) for p in refused.exception.problems), refused.exception.problems)


class AroundTheTrace(unittest.TestCase):
    """E45 (the download), F47–48 (fact-check and generation guide) and G49 (the gallery)."""

    def lesson_with_trace(self) -> dict:
        lesson = gallery_json("ice-albedo-feedback")
        at = [c["id"] for c in lesson["concepts"]].index("ice_albedo_loop")
        lesson["concepts"][at] = loop_concept(model_trace(values={"hold": 0}))
        return lesson

    def test_45_the_download_carries_the_trace_and_sends_nothing(self):
        lesson = self.lesson_with_trace()
        server.core.require_valid(lesson, None)  # only a lesson that passes its checks is downloaded
        html = export.lesson_html(lesson)
        self.assertIn("connect-src 'none'", html)
        payload = json.loads(html.split('<script type="application/json" id="lesson-data">')[1].split("</script>")[0])
        traces = [a for c in payload["concepts"] for a in c["activities"] if a["kind"] == "trace"]
        self.assertEqual(traces, [model_trace(values={"hold": 0})])
        for script in export.SCRIPTS:
            self.assertIn(export._script_safe(export._static(script)).strip()[:200], html)
        self.assertNotRegex(html, r"\bfetch\(|XMLHttpRequest|<script[^>]+src=|<link[^>]+stylesheet")
        # A gallery lesson downloads as shipped, with its model trace.
        shipped = call(server.api_export, body={"lesson": {"gallery": {"slug": "ice-albedo-feedback"}}})
        self.assertIn('"on": "model"', shipped)

    def test_47_fact_check_reads_the_models_labels(self):
        c = loop_concept()
        text = factcheck.concept_text(c, 1)
        self.assertIn(f"TRACING: {LOOP_PROMPT}", text)
        self.assertIn("  links: First push (°C) -> Planet warms (°C); Planet warms (°C) -> Ice cover; Ice cover -> Sunlight bounced away; "
                      "Sunlight bounced away -> Sunlight soaked up; Sunlight soaked up -> Planet warms (°C)", text)
        self.assertIn("  marked answer: Planet warms (°C) -> Ice cover -> Sunlight bounced away -> Sunlight soaked up", text)
        self.assertIn(f"  why: {LOOP_EXPLANATION}", text)

    def test_48_generation_guide_documents_the_model_trace(self):
        guide = L.schema_guide()
        self.assertIn('"on": "model"', guide)
        at = guide.index('"on": "model"')
        about = guide[at - 400: at + 800]
        self.assertIn("causal", about)
        self.assertIn("3–10 nodes", about)

    def test_49_the_ice_albedo_gallery_lesson_traces_its_own_loop(self):
        lesson, source = server.load_gallery("ice-albedo-feedback")
        self.assertEqual(list(L.check_lesson(lesson, source)), [])
        c = concept_of(lesson, "ice_albedo_loop")
        traces = [(i, a) for i, a in enumerate(c["activities"]) if a["kind"] == "trace"]
        self.assertEqual(len(traces), 1)
        i, a = traces[0]
        self.assertEqual(a.get("on"), "model")
        self.assertNotIn("nodes", a)
        self.assertNotIn("edges", a)
        kinds = [x["kind"] for x in c["activities"][:i]]
        self.assertIn("explain", kinds)  # after the teaching
        self.assertTrue(a.get("path"))
        links = {(e["from"], e["to"]) for e in c["model"]["visual"]["edges"]}
        ids = {n["id"] for n in c["model"]["visual"]["nodes"]}
        self.assertGreaterEqual(len(a["answer"]), 3)
        self.assertTrue(set(a["answer"]) <= ids)
        self.assertTrue(all(step in links for step in zip(a["answer"], a["answer"][1:])))
        self.assertIn('"on": "model"', export.lesson_html(lesson))


class PlantedErrors(unittest.TestCase):
    """The eval plants a wrong answer key in a set trace; on the model, the wrong nodes come from the model."""

    def test_a_wrong_answer_is_planted_in_a_set_trace_on_the_model(self):
        import sys
        sys.path.insert(0, str(ROOT / "eval"))
        import plant

        c = loop_concept(model_trace(path=False, answer=["reflect", "absorb"]))
        detail = plant._wrong_task(c)
        self.assertEqual(detail, "trace loop now expects the nodes it should exclude")
        self.assertEqual(c["activities"][trace_index(c)]["answer"], ["push", "temp"])
        # A trace with no other nodes to swap in is left alone, rather than claimed as changed.
        c = loop_concept(model_trace(path=False, answer=["push", "temp", "ice", "reflect", "absorb"]))
        self.assertIsNone(plant._wrong_task(c))


# The picking cases in tests/model_trace.js, by the use case they cover.
PICKING_CASES = [
    "27 draws the copy with the block's values",
    "27 draws the copy in the model's defaults when the block gives none",
    "28 every model node is a pickable button, and nothing else is",
    "29 clicking picks a node and clicking again unpicks it",
    "30 Enter and Space pick with the default prevented; other keys do nothing",
    "31 aria-pressed follows the pick and the name says its place",
    "32 a path shows order numbers on picked nodes",
    "32 a set shows no order numbers",
    "33 links between picked nodes are highlighted",
    "34 a set: a wrong set is not yet, the right set in any order completes",
    "35 a path: the wrong order is not yet, the right order completes",
    "36 Show me picks the answer, marks it and completes",
    "37 Clear empties the picks, resets done and the status",
    "38 Hint shows the hints one at a time",
    "39 changing a pick after completing resets done",
    "40 coming back restores the picks and their marks",
    "H3 without a way to draw the model, an error and nothing to pick",
    "H3 when the drawing fails, an error and nothing to pick",
    "10 an authored trace keeps its node elements when a pick is made",
]


def results(lines: str) -> dict[str, str]:
    """{label: "PASS" | "FAIL ..."} from a script that prints one line per check."""
    out = {}
    for line in lines.splitlines():
        m = re.match(r"^(PASS|FAIL)\s+(.*?)(?:\s+::\s+(.*))?$", line)
        if m:
            out[m.group(2)] = m.group(1) + (f" {m.group(3)}" if m.group(3) else "")
    return out


@unittest.skipUnless(shutil.which("node"), "node is needed to exercise the picking handlers")
class Picking(unittest.TestCase):
    """C. Picking on the copy, through activities.js's own handlers (node, with a stand-in page)."""

    def test_picking_on_the_models_copy(self):
        run = subprocess.run(["node", "tests/model_trace.js"], cwd=ROOT, capture_output=True, text=True, timeout=120)
        got = results(run.stdout)
        for case in PICKING_CASES:
            with self.subTest(case):
                self.assertEqual(got.get(case, "FAIL (never ran)" + (f": {run.stderr[-400:]}" if run.stderr else "")), "PASS")


# The browser checks in tests/model_trace_ui.mjs, run on the downloaded lesson opened from disk.
BROWSER_CHECKS = [
    "41 the copy is inside the activity",
    "2d desktop: no note about scrolling",
    "2d desktop: the copy fits its box, with nothing to scroll",
    "41 the live model panel is not on the stage",
    "42 the copy shows the model's labels",
    "42 the copy shows the model's values",
    "42 the copy shows the model's arrows",
    "42 the copy keeps the model's legend",
    "42 the copy is a group named by the prompt",
    "27 the copy is drawn in the model's defaults",
    "30 Enter picks a node and stays on the screen",
    "30 Space picks a node",
    "1c focus stays on a node picked by keyboard",
    "1a a focused picked node shows its focus ring, and a picked node without focus doesn't",
    "1b the focus ring is dashed, and not the picked colour",
    "31 a picked node is pressed and says its place",
    "32 a picked node shows its place in the path",
    "35 a wrong path is not yet",
    "37 Clear empties the picks",
    "7a clicking the part of a label past its box picks the node",
    "7b clicking empty space next to a node picks nothing",
    "29 clicking picks nodes in order",
    "33 links along the picked path are highlighted",
    "35 the right path completes with the explanation",
    "36 Show me picks the answer and completes",
    "27 the copy is drawn in the block's values",
    "34 the right set in any order completes",
    "10 an authored trace keeps focus on a node picked by keyboard",
    "1d an authored trace shows the focus ring on a focused picked node",
    "44 leaving the screen removes the copy",
    "43 the live causal model draws as before",
    "46 the trace works offline, with no network requests",
    "46 no page errors",
]

# The same lesson on a phone, 390 px wide.
PHONE_CHECKS = [
    "2a phone: node labels are at least 11 px",
    "2a phone: every node is at least 24 by 24 px to tap",
    "2b phone: the page doesn't scroll sideways",
    "2b phone: focusing the right-most node brings it into view",
    "2b phone: a note says the model scrolls sideways",
    "2c phone: no tap highlight on the nodes",
    "2 phone: tapping picks a node",
    "2 phone: no page errors",
]

AUTHORED = {"id": "chain", "kind": "trace", "prompt": "Trace the chain from warming to a darker surface.", "path": True,
            "nodes": [{"id": "a", "label": "Warmer", "x": 10, "y": 50}, {"id": "b", "label": "Less ice", "x": 50, "y": 50},
                      {"id": "c", "label": "Darker surface", "x": 90, "y": 50}],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}], "answer": ["a", "b", "c"], "explanation": "Each step is one link."}


def find_chrome() -> str | None:
    named = os.environ.get("LEMMA_TEST_CHROME")
    if named:
        return named if Path(named).exists() else None
    names = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
    return next((shutil.which(n) for n in names if shutil.which(n)), None)


def why_no_browser() -> str | None:
    if not shutil.which("node"):
        return "node is needed for the browser tests"
    if not (ROOT / "node_modules" / "puppeteer-core").is_dir():
        return "run `npm ci` for the browser tests"
    if not find_chrome():
        return "Chrome or Chromium is needed for the browser tests (or set LEMMA_TEST_CHROME)"
    return None


def browser_lesson() -> dict:
    """One concept, the ice–albedo loop, with two model traces between its teaching and a goal on the live model."""
    lesson = gallery_json("ice-albedo-feedback")
    c = loop_concept()
    c["activities"] = [
        {"id": "idea", "kind": "explain"},
        model_trace(hints=["Start at the warming."]),
        model_trace(id="parts", path=False, prompt="With the ice held fixed, pick the two kinds of sunlight.", answer=["reflect", "absorb"],
                    values={"hold": 1}, explanation="Sunlight is either bounced away or soaked up."),
        AUTHORED,
        {"id": "goal_1", "kind": "goal", "i": 0},
    ]
    lesson["concepts"], lesson["primer"] = [c], None
    lesson.pop("plan", None)
    return lesson


@unittest.skipIf(why_no_browser(), why_no_browser())
class InTheBrowser(unittest.TestCase):
    """D41–44 and E46: the downloaded lesson, opened from disk in a real browser with every request blocked."""

    def test_model_trace_in_the_downloaded_lesson(self):
        self.run_flow("desktop", BROWSER_CHECKS)

    def test_model_trace_on_a_phone(self):
        self.run_flow("phone", PHONE_CHECKS)

    def run_flow(self, flow, checks):
        lesson = browser_lesson()
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "lesson.html"
            page.write_text(export.lesson_html(lesson), encoding="utf-8")
            model = lesson["concepts"][0]["model"]
            cfg = {"chrome": find_chrome(), "file": page.as_uri(), "flow": flow, "nodes": model["visual"]["nodes"], "edges": model["visual"]["edges"],
                   "traces": [a for a in lesson["concepts"][0]["activities"] if a["kind"] == "trace"]}
            run = subprocess.run(["node", "tests/model_trace_ui.mjs", json.dumps(cfg)], cwd=ROOT, capture_output=True, text=True, timeout=240)
        got = results(run.stdout)
        for check in checks:
            with self.subTest(check):
                self.assertEqual(got.get(check, "FAIL (never ran)" + (f": {run.stderr[-600:]}" if run.stderr else "")), "PASS")


if __name__ == "__main__":
    unittest.main()
