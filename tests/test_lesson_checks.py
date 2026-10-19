"""The quality gate in lesson.py, rule by rule: each broken lesson is refused with a message that points at the
broken part, and the unbroken version of the same lesson passes. A lesson that fails these checks is never shown.
"""

from __future__ import annotations

import copy
import json
import unittest

from test_lemma import EXAMPLE, NORM, SOURCE
from lemma import lesson as L


def galton(i=1):
    """A Galton concept with a live model: 1 draws curves (mp, ratio → dev, child, child_dev)."""
    return copy.deepcopy(EXAMPLE["concepts"][i])


def plain():
    """A concept taught without a model: explanation, then a scored choice."""
    return {"id": "jtb", "title": "Knowledge as a recipe", "idea": "Knowledge was said to be justified true belief.",
            "recap": "Three ingredients, once thought enough.",
            "activities": [{"id": "idea", "kind": "explain", "text": "Philosophers long said knowing is believing truly, for good reasons."},
                           {"id": "q", "kind": "choice", "mode": "determinate", "question": "Which ingredient is missing?",
                            "options": [{"text": "Truth", "feedback": "Yes."}, {"text": "Colour", "feedback": "No."}], "answer": 0}],
            "understand": {"explanation": "The recipe has three parts.", "quote": "knowledge is justified true belief, said the old view",
                           "quote_where": "Opening"}}


BLOCKS = {
    "worked": {"id": "w", "kind": "worked", "title": "T", "steps": [{"text": "a"}, {"text": "b", "result": "r"}], "takeaway": "t"},
    "compare": {"id": "cmp", "kind": "compare", "prompt": "p", "cases": [{"label": "A", "text": "a"}, {"label": "B", "text": "b"}], "takeaway": "t"},
    "stages": {"id": "st", "kind": "stages", "prompt": "p", "stages": [{"label": "1", "text": "a"}, {"label": "2", "text": "b"}], "takeaway": "t"},
    "sort": {"id": "s", "kind": "sort", "title": "T", "prompt": "p", "takeaway": "t", "groups": [{"id": "g1", "label": "G1"}, {"id": "g2", "label": "G2"}],
             "cards": [{"id": "c1", "text": "x", "feedback": "f", "group": "g1"}, {"id": "c2", "text": "y", "feedback": "f", "group": "g2"}]},
    "match": {"id": "m", "kind": "match", "prompt": "p", "takeaway": "t",
              "pairs": [{"id": "p1", "text": "a", "target": "A", "feedback": "f"}, {"id": "p2", "text": "b", "target": "B", "feedback": "f"}]},
    "order": {"id": "o", "kind": "order", "prompt": "p", "items": ["a", "b", "c"], "explanation": "e"},
    "trace": {"id": "tr", "kind": "trace", "prompt": "p", "path": True, "answer": ["a", "b", "c"], "explanation": "e",
              "nodes": [{"id": "a", "label": "A", "x": 10, "y": 10}, {"id": "b", "label": "B", "x": 50, "y": 50}, {"id": "c", "label": "C", "x": 90, "y": 90}],
              "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}]},
    "passage": {"id": "pa", "kind": "passage", "question": "q", "answer": 0,
                "options": [{"quote": "one two three four five six", "feedback": "f"}, {"quote": "seven eight nine ten eleven twelve", "feedback": "f"}]},
    "estimate": {"id": "e", "kind": "estimate", "question": "q", "answer": 1.9, "tolerance": 0.1, "explanation": "x", "hints": ["Divide."]},
    "construction": {"id": "con", "kind": "construction", "title": "T", "prompt": "p", "takeaway": "t",
                     "steps": [{"label": "1", "note": "n", "shapes": [{"type": "circle", "x": 50, "y": 50, "r": 20}]},
                               {"label": "2", "note": "n", "shapes": [{"type": "line", "x1": 0, "y1": 0, "x2": 10, "y2": 10}, {"type": "point", "x": 5, "y": 5}]}]},
    "inheritance": {"id": "inh", "kind": "inheritance", "title": "T", "prompt": "p", "parent": "Aa", "second": "aa"},
    "interpretive": {"id": "i", "kind": "choice", "mode": "interpretive", "question": "q", "options": [{"text": "a", "feedback": "f"}, {"text": "b", "feedback": "f"}]},
    "multi": {"id": "mu", "kind": "choice", "mode": "determinate", "multi": True, "answers": [0, 1], "question": "q",
              "options": [{"text": "a", "feedback": "f"}, {"text": "b", "feedback": "f"}, {"text": "c", "feedback": "f"}]},
}


def with_block(kind, change=None, concept=None):
    c = concept or plain()
    block = copy.deepcopy(BLOCKS[kind])
    if change:
        change(block)
    c["activities"].insert(1, block)
    return c


def problems(c, norm=None):
    return list(L.check_concept(c, norm))


class Gate(unittest.TestCase):
    def assert_refused(self, cases, check=problems):
        """`cases` is [(expected text in a problem, concept)]; each must be refused with that problem."""
        for expected, c in cases:
            with self.subTest(expected=expected):
                found = check(c)
                self.assertTrue(any(expected in p for p in found), f"{expected!r} not in {found}")


def edit(c, fn):
    fn(c)
    return c


class Baselines(unittest.TestCase):
    def test_the_unbroken_concepts_and_blocks_pass(self):
        self.assertEqual(problems(galton(1), NORM), [])
        self.assertEqual(problems(plain()), [])
        for kind in BLOCKS:
            with self.subTest(kind=kind):
                self.assertEqual(problems(with_block(kind)), [])


class Controls(Gate):
    def test_controls_must_be_usable_sliders_and_toggles(self):
        def control(i, **fields):
            return edit(galton(), lambda c: c["model"]["controls"][i].update(fields))

        self.assert_refused([
            ("a model needs 1–4 controls", edit(galton(), lambda c: c["model"].update(controls=[]))),
            ("controls[0]: must be an object", edit(galton(), lambda c: c["model"]["controls"].__setitem__(0, "mp"))),
            ("must be lower_snake_case and not a reserved word", control(0, id="sin")),
            ("duplicate id 'mp'", control(1, id="mp")),
            ("controls[0]: needs a label", control(0, label=" ")),
            ("a toggle has min 0, max 1, step 1", control(1, kind="toggle", min=0, max=2, step=1, default=0)),
            ("kind must be 'slider' or 'toggle'", control(0, kind="dial")),
            ("min, max, step and default must be numbers", control(0, min="low")),
            ("min must be below max", control(0, min=80)),
            ("step must be positive and no larger than the range", control(0, step=0)),
            ("step is too fine", control(0, step=0.001)),
            ("default must be within min..max", control(0, default=99)),
            ("default must sit on the step grid", control(0, default=72.1)),
        ])


class Outputs(Gate):
    def test_every_output_and_drawn_number_is_a_finite_number(self):
        def model(fn):
            return edit(galton(), lambda c: fn(c["model"]))

        self.assert_refused([
            ("model must be an object", edit(galton(), lambda c: c.update(model=None))),
            ("needs a 'note' saying this is a simplified teaching model", model(lambda m: m.update(note=""))),
            ("needs a visual", model(lambda m: m.pop("visual"))),
            ("outputs must be a list of at most 6", model(lambda m: m.update(outputs=m["outputs"] * 3))),
            ("outputs[0]: must be an object", model(lambda m: m["outputs"].__setitem__(0, "dev"))),
            ("must be unique lower_snake_case and not reserved", model(lambda m: m["outputs"][1].update(id="dev"))),
            ("outputs[0]: needs a label", model(lambda m: m["outputs"][0].pop("label"))),
            ("bad expression", model(lambda m: m["outputs"][0].update(expr="mp +"))),
            ("bad expression: sqrt() takes 1–1 arguments, got 2", model(lambda m: m["outputs"][0].update(expr="sqrt(mp, 2)"))),
            ("output 'dev' is not a finite number when controls are mp=72, ratio=1", model(lambda m: m["outputs"][0].update(expr="1 / (mp - 72)"))),
            ("visual.hlines[0].y is not a finite number", model(lambda m: m["visual"]["hlines"][0].update(y="1 / (mp - 72)"))),
            ("visual x.min must be below x.max", model(lambda m: m["visual"]["x"].update(min=80))),
            ("series[1] is undefined over most of the x range", model(lambda m: m["visual"]["series"][1].update(expr="sqrt(-1 - x)"))),
        ])


class Visuals(Gate):
    def test_each_visual_type_has_the_parts_it_draws(self):
        def visual(v):
            return edit(galton(), lambda c: c["model"].update(visual=v))

        table = {"type": "table", "columns": ["a", "b"], "rows": [{"cells": [1]}]}
        causal = {"type": "causal", "nodes": [{"id": "a", "x": 10, "y": 10}, {"id": "b", "x": 150, "y": 10}], "edges": [{"from": "a", "to": "z", "strength": 1}]}
        self.assert_refused([
            ("type must be one of", visual({"type": "pie"})),
            ("a agents visual needs kernel one of", visual({"type": "agents", "kernel": "regression", "params": {}})),
            ("kernel 'regression' has no parameters ['bogus']", visual({"type": "sampling", "kernel": "regression", "params": {"bogus": 1}})),
            ("a curves visual needs 'x'", edit(galton(), lambda c: c["model"]["visual"].pop("x"))),
            ("needs at least one series", edit(galton(), lambda c: c["model"]["visual"].update(series=[]))),
            ("fills[0]: series must be the index of a series", edit(galton(), lambda c: c["model"]["visual"].update(fills=[{"series": 5, "from": 62, "to": 70}]))),
            ("rows[0]: needs 2 cells, one per column", visual(table)),
            ("edges[0]: from and to must be node ids", visual(causal)),
            ("nodes[1]: x and y must be numbers from 0 to 100", visual(causal)),
        ])


class Goals(Gate):
    def test_goals_start_false_and_their_own_solution_reaches_them(self):
        def goal(**fields):
            return edit(galton(), lambda c: c["explore"]["goals"][0].update(fields))

        self.assert_refused([
            ("needs a 'when' condition", goal(when=5)),
            ("needs a 'solution'", edit(galton(), lambda c: c["explore"]["goals"][0].pop("solution"))),
            ("solution sets unknown control 'zzz'", goal(solution={"zzz": 1})),
            ("solution ratio=2 is outside 0..1", goal(solution={"ratio": 2})),
            ("is not reachable with step 0.05", goal(solution={"ratio": 0.651})),
            ("'ratio > 0.5' is already true before the learner does anything", goal(when="ratio > 0.5", solution={"ratio": 0.65})),
            ("'ratio < 0.1' is false at its own solution", goal(when="ratio < 0.1", solution={"ratio": 0.65})),
            ("needs one or two goals", edit(galton(), lambda c: c["explore"].update(goals=[]))),
            ("needs 'hints': 2–3 lines", goal(hints=["Only one."])),
            ("each hint must be at most 240 characters", goal(hints=["x" * 241, "y"])),
            ("hint 1 gives away the solution ratio = 0.65", goal(hints=["Set the share to 0.65.", "Then check."])),
        ])

    def test_a_check_must_ask_for_something_the_goals_did_not(self):
        c = galton()
        c["check"] = {"kind": "model", "task": "Match Galton again.", "hint": "h", "misconception": "m",
                      "when": "abs(mp - 72) < 0.01 && abs(child - 70.75) < 0.15", "solution": {"ratio": 0.65}}
        self.assert_refused([("is already true at goal 1's solution, so it checks nothing new", c)])


class Narration(Gate):
    def test_the_tour_moves_real_controls_and_points_at_real_parts(self):
        def step(i, **fields):
            return edit(galton(), lambda c: c["animation"]["steps"][i].update(fields))

        self.assert_refused([
            ("needs a narrated tour", edit(galton(), lambda c: c["animation"].update(steps=c["animation"]["steps"][:1]))),
            ("animation.steps[0]: must be an object", edit(galton(), lambda c: c["animation"]["steps"].__setitem__(0, "Look."))),
            ("sets mp=200, which is not a control value in range", step(2, set={"mp": 200})),
            ("focus must name one part, or list 1–4 parts", step(0, focus=["mp", "ratio", "dev", "child", "child_dev"])),
            ("focus 'ghost' is not a control, output or marked part of the picture", step(0, focus="ghost")),
            ("'say' is too long", step(0, say="x" * 241)),
        ])


class Terms(Gate):
    def test_a_term_is_shown_before_it_is_named(self):
        def terms(t):
            return edit(galton(), lambda c: c.update(terms=t))

        self.assert_refused([
            ("must be a list of at most 4 terms", terms([{"term": f"t{i}", "means": "m"} for i in range(5)])),
            ("'mid-parent' is used before it is explained", terms([{"term": "mid-parent", "means": "the parents' average"}])),
            ("'zygote' never appears in the walkthrough or explanation", terms([{"term": "zygote", "means": "a fertilised egg"}])),
        ])


class PredictCheckConnect(Gate):
    def test_predict_check_and_equation_rules(self):
        def predict(**fields):
            return edit(galton(), lambda c: c["predict"].update(fields))

        def check(ck):
            return edit(galton(), lambda c: c.update(check=dict({"hint": "h", "misconception": "m"}, **ck)))

        opts = lambda *flags: [{"text": f"o{i}", "correct": f} for i, f in enumerate(flags)]
        self.assert_refused([
            ("needs 2–5 option strings", predict(options=["only"])),
            ("answer must be the index of the correct option", predict(answer=9)),
            ("needs 'why': one short line per option", predict(why=["one"])),
            ("each 'why' line must be at most 260 characters", edit(galton(), lambda c: c["predict"].update(why=["x" * 261] + c["predict"]["why"][1:]))),
            ("kind must be one of", check({"kind": "essay"})),
            ("needs 2–6 options", check({"kind": "choice", "question": "q", "options": opts(True)})),
            ("options[0]: needs text and correct (true/false)", check({"kind": "choice", "question": "q", "options": [{"text": "a"}, {"text": "b", "correct": True}]})),
            ("at least one option must be correct", check({"kind": "choice", "question": "q", "options": opts(False, False)})),
            ("only one option may be correct unless multi is true", check({"kind": "choice", "question": "q", "options": opts(True, True)})),
            ("answer must be true or false", check({"kind": "truefalse", "statement": "s", "answer": "yes"})),
            ("needs a numeric answer and a non-negative tolerance", check({"kind": "numeric", "question": "q", "answer": 2, "tolerance": -1})),
            ("needs 3–6 items, listed in the correct order", check({"kind": "order", "prompt": "p", "items": ["a", "b"]})),
            ("items must be distinct", check({"kind": "order", "prompt": "p", "items": ["a", "b", "a"]})),
            ("needs an equation: a list of parts", edit(galton(), lambda c: c["connect"].update(equation=[]))),
            ("equation[1]: each part needs text", edit(galton(), lambda c: c["connect"]["equation"].__setitem__(1, {"text": ""}))),
            ("link 'ghost' is not a control or output of the model", edit(galton(), lambda c: c["connect"]["equation"][0].update(link="ghost"))),
        ])
        self.assertEqual(problems(check({"kind": "choice", "question": "q", "multi": True, "options": opts(True, True)})), [])


class Activities(Gate):
    def test_activities_teach_before_they_ask(self):
        def acts(*blocks):
            return edit(plain(), lambda c: c.update(activities=list(blocks)))

        explain = {"id": "idea", "kind": "explain"}
        ask = copy.deepcopy(plain()["activities"][1])
        opening = dict(ask, id="first", mode="opening")
        opening.pop("answer")
        self.assert_refused([
            ("activities needs 2–24 teaching and response blocks", acts(explain)),
            ("activities[0]: must be an object", acts("explain", ask)),
            ("id must be unique lower_snake_case", acts(explain, dict(ask, id="idea"))),
            ("unsupported activity kind", acts(explain, dict(ask, kind="dance"))),
            ("hypothetical must be true or false", acts(explain, dict(ask, hypothetical="yes"))),
            ("watch needs its model and content", acts({"id": "t", "kind": "watch"}, ask)),
            ("teach before practice", acts(ask, explain)),
            ("revisits must name an earlier opening choice, from a choice", acts(explain, dict(ask, revisits="idea"))),
            ("a revisit comes after the teaching", acts(opening, dict(ask, revisits="first"), explain)),
            ("activities must include teaching and meaningful engagement", acts(explain, dict(explain, id="more"))),
            ("hints must be 1–3 lines that get more specific", acts(explain, dict(ask, hints=[]))),
            ("each hint must be at most 240 characters", acts(explain, dict(ask, hints=["x" * 241]))),
        ])

    def test_model_screens_need_their_parts_in_order(self):
        def acts(fn):
            return edit(galton(), lambda c: fn(c["activities"]))

        kinds = lambda c: [a["kind"] for a in c["activities"]]
        c = galton()
        self.assertEqual(kinds(c)[:3], ["watch", "walk", "explain"])
        self.assert_refused([
            ("watch needs narration steps", edit(galton(), lambda c: c["animation"].update(steps=[]))),
            ("walk needs walkthrough steps", edit(galton(), lambda c: c["understand"]["walkthrough"].update(steps=[]))),
            ("predict must be immediately followed by reveal", acts(lambda a: a.pop(kinds(c).index("reveal")))),
            ("reveal must immediately follow predict", acts(lambda a: a.pop(kinds(c).index("predict")))),
            ("i must identify an existing goal", acts(lambda a: a[kinds(c).index("goal")].update(i=7))),
        ])

    def test_each_block_kind_checks_its_own_parts(self):
        self.assert_refused([
            ("needs 2–8 steps", with_block("worked", lambda b: b["steps"].pop())),
            ("cases[0]: must be an object", with_block("compare", lambda b: b["cases"].__setitem__(0, "A"))),
            ("cases[0]: values need the concept's model", with_block("compare", lambda b: b["cases"][0].update(values={"mp": 70}))),
            ("cases[0]: needs 'text' or model 'values'", with_block("compare", lambda b: b["cases"][0].pop("text"))),
            ("'ghost' is not a control of the model", with_block("compare", lambda b: b["cases"][0].update(values={"ghost": 1}), concept=galton())),
            ("'mp' must be a number within its control's range", with_block("compare", lambda b: b["cases"][0].update(values={"mp": 999}), concept=galton())),
            ("values must set at least one control", with_block("compare", lambda b: b["cases"][0].update(values={}), concept=galton())),
            ("needs 2–6 stages", with_block("stages", lambda b: b.update(stages=[]))),
            ("mode must be determinate, interpretive or opening", with_block("interpretive", lambda b: b.update(mode="guess"))),
            ("options[0]: must be an object", with_block("interpretive", lambda b: b["options"].__setitem__(0, "a"))),
            ("multi applies only to a determinate choice", with_block("multi", lambda b: b.update(mode="interpretive"))),
            ("a multi choice needs 'answers'", with_block("multi", lambda b: b.update(answers=[0, 0]))),
            ("answer must identify the supported option", edit(plain(), lambda p: p["activities"][1].update(answer=5))),
            ("unscored activities must not have an answer key", with_block("interpretive", lambda b: b.update(answer=0))),
            ("card must reference an existing group", with_block("sort", lambda b: b["cards"][0].update(group="g9"))),
            ("cards need unique lower_snake_case ids", with_block("sort", lambda b: b["cards"][1].update(id="c1"))),
            ("each pair needs a different target", with_block("match", lambda b: b["pairs"][1].update(target="A"))),
            ("items must be text of at most 300 characters", with_block("order", lambda b: b["items"].__setitem__(0, "x" * 301))),
            ("items must be distinct", with_block("order", lambda b: b.update(items=["a", "b", "a"]))),
            ("nodes[0]: needs x and y between 0 and 100", with_block("trace", lambda b: b["nodes"][0].update(x=120))),
            ("edges must be a list of at most 20 links", with_block("trace", lambda b: b.update(edges=[{"from": "a", "to": "b"}] * 21))),
            ("each edge must join two existing nodes", with_block("trace", lambda b: b["edges"].append({"from": "a", "to": "z"}))),
            ("answer must list distinct existing node ids", with_block("trace", lambda b: b.update(answer=["a", "a"]))),
            ("a path answer must follow the edges, in order", with_block("trace", lambda b: b.update(answer=["a", "c", "b"]))),
            ("quote must contain at least 6 words", with_block("passage", lambda b: b["options"][0].update(quote="too short"))),
            ("answer must identify the supporting passage", with_block("passage", lambda b: b.update(answer=3))),
            ("needs a numeric answer and a non-negative tolerance", with_block("estimate", lambda b: b.update(tolerance=-0.1))),
            ("shape type must be one of", with_block("construction", lambda b: b["steps"][0]["shapes"][0].update(type="arc"))),
            ("a circle needs x, y, r between 0 and 100", with_block("construction", lambda b: b["steps"][0]["shapes"][0].update(r=500))),
            ("parent must be AA, Aa or aa", with_block("inheritance", lambda b: b.update(parent="AB"))),
        ])

    def test_quotes_in_passages_are_checked_against_the_source(self):
        c = with_block("passage")
        self.assertTrue(any("appear word for word in the source" in p for p in problems(c, NORM)))
        self.assertEqual(problems(c), [])  # without the source the quote can't be checked, so it isn't refused for that


class ConceptsWithoutModels(Gate):
    def test_a_concept_without_a_model_still_needs_a_grounded_explanation(self):
        self.assert_refused([
            ("understand must contain the explanation and source quote", edit(plain(), lambda c: c.update(understand="text"))),
            ("quote must contain at least 6 words", edit(plain(), lambda c: c["understand"].update(quote="Too short."))),
        ])
        self.assertTrue(any("appear word for word" in p for p in problems(plain(), NORM)))


class Primer(Gate):
    def test_the_paper_in_brief_quotes_the_paper(self):
        def primer(fn):
            pages = copy.deepcopy(EXAMPLE["primer"])
            fn(pages)
            return pages

        quoted = [i for i, p in enumerate(EXAMPLE["primer"]) if p.get("quote")]
        self.assertEqual(list(L.check_primer(EXAMPLE["primer"], NORM)), [])
        self.assert_refused([
            ("needs 3–6 pages", "the paper in one line"),
            ("primer[0]: must be an object", primer(lambda p: p.__setitem__(0, "page"))),
            ("quote is too short (at least 6 words)", primer(lambda p: p[quoted[0]].update(quote="Too short."))),
            ("quote does not appear word for word in the paper", primer(lambda p: p[quoted[0]].update(quote="Galton measured the heights of exactly one family only."))),
            ("at least two pages must quote the paper word for word", primer(lambda p: [pg.pop("quote", None) for pg in p[1:]])),
        ], check=lambda pages: list(L.check_primer(pages, NORM)))


class BuildsOn(Gate):
    def test_a_concept_that_builds_on_another_keeps_its_model(self):
        base = galton()

        def later(fn):
            c = galton()
            fn(c["model"])
            return c

        extra = lambda i: {"id": f"extra{i}", "label": "Extra", "kind": "slider", "min": 0, "max": 1, "step": 0.5, "default": 0}
        self.assertEqual(list(L.check_builds_on(later(lambda m: m["controls"].append(extra(1))), base)), [])
        self.assert_refused([
            ("so it must keep its visual type 'curves'", later(lambda m: m["visual"].update(type="bars"))),
            ("so it must keep its control 'ratio'", later(lambda m: m["controls"].pop())),
            ("control 'mp' must keep the same label and range", later(lambda m: m["controls"][0].update(max=80))),
            ("add at most one new control", later(lambda m: m["controls"].extend([extra(1), extra(2)]))),
        ], check=lambda c: list(L.check_builds_on(c, base)))


class Lessons(Gate):
    def test_the_whole_lesson_rules(self):
        def lesson(fn):
            les = copy.deepcopy(EXAMPLE)
            fn(les)
            return les

        hard = lambda c: dict(c, check={"kind": "truefalse", "statement": "s", "answer": True, "hint": "h", "misconception": "m"})
        self.assertEqual(list(L.check_lesson(EXAMPLE, SOURCE)), [])
        self.assert_refused([
            ("lesson: must be an object", "lesson"),
            ("background must be a list of strings", lesson(lambda l: l["intro"].update(background="one line"))),
            ("needs 1–8 concepts", lesson(lambda l: l.update(concepts=[]))),
            ("3 concepts have a check", lesson(lambda l: l.update(concepts=[hard(c) for c in l["concepts"]]))),
            ("aha must be one sentence of at most 300 characters", lesson(lambda l: l["intro"].update(aha="x" * 301))),
            ("duplicate concept id 'mid_parent'", lesson(lambda l: l["concepts"][1].update(id="mid_parent"))),
            ("builds_on 'later_one' must name an earlier concept", lesson(lambda l: l["concepts"][1].update(builds_on="later_one"))),
            ("so it must keep its visual type 'bars'", lesson(lambda l: l["concepts"][1].update(builds_on="mid_parent"))),
        ], check=lambda les: list(L.check_lesson(les, SOURCE)))


class MultipleSources(Gate):
    """A combined lesson names, for each quote, the source it comes from, and that source must contain it."""

    def setUp(self):
        self.sources = {"s1": {"id": "s1", "title": "Galton", "text": SOURCE}, "s2": {"id": "s2", "title": "Other", "text": "Nothing about heights here at all."}}
        self.quote = EXAMPLE["concepts"][1]["understand"]["quote"]

    def test_quotes_name_a_source_that_contains_them(self):
        ok = {"source_ids": ["s1"], "quote": self.quote, "source_id": "s1"}
        self.assertEqual(L.check_attribution(ok, self.sources, "u"), [])
        self.assert_refused([
            ("source_ids must identify the supporting sources", dict(ok, source_ids=["s9"])),
            ("quote needs a valid source_id", dict(ok, source_id=None)),
            ("quote does not appear in its identified source", dict(ok, source_id="s2", source_ids=["s2"])),
            ("quote source must be included in source_ids", dict(ok, source_ids=["s2"])),
        ], check=lambda block: L.check_attribution(block, self.sources, "u"))

    def test_passage_options_name_their_source(self):
        def passage(**fields):
            def change(b):
                b["options"][0].update(quote=self.quote, **fields)
                b["options"][1].update(quote="Nothing about heights here at all.", source_id="s2")
            return with_block("passage", change)

        self.assertEqual(L.check_activity_attribution(passage(source_id="s1"), self.sources, "c"), [])
        self.assert_refused([
            ("options[0]: quote needs a valid source_id", passage()),
            ("options[0]: quote does not appear in its identified source", passage(source_id="s2")),
        ], check=lambda c: L.check_activity_attribution(c, self.sources, "c"))

    def test_a_combined_lesson_keeps_its_sources_metadata(self):
        bundle = json.dumps({"lemma_sources": list(self.sources.values())})
        les = copy.deepcopy(EXAMPLE)
        les["sources"] = [{"id": "s1", "title": "Renamed"}]
        self.assertTrue(any("lesson.sources: must match the original source metadata" in p for p in L.check_lesson(les, bundle)))

    def test_a_damaged_source_bundle_reads_as_plain_text(self):
        self.assertEqual(L.source_map('{"lemma_sources": [broken'), {})
        self.assertEqual(L.source_document('{"lemma_sources": [broken'), '{"lemma_sources": [broken')


if __name__ == "__main__":
    unittest.main()
