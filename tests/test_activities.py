"""Offline checks for the shared gallery and model-free activities."""
import copy
from datetime import datetime
import json
import shutil
import subprocess
from pathlib import Path
import unittest

from lemma import export, factcheck, lesson as L, server
import fakejev  # noqa: E402,F401  Jev is essential, so every search and build asks this stand-in

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((ROOT / "lemma/examples/gallery/galton-1886.json").read_text())


class GalleryActivitiesTests(unittest.TestCase):
    def setUp(self):
        self.lesson, _ = server.load_gallery("brown-1954")
        self.source = "A source quotation with enough words to ground this small teaching example."
        self.lesson["primer"] = None
        self.lesson["concepts"] = [{
            "id": "example", "title": "Example", "idea": "Distinguish a supported claim.", "recap": "Use the source.", "terms": [],
            "understand": {"explanation": "Read the source before applying the distinction.", "quote": self.source, "quote_where": "Test fixture"},
            "activities": [
                {"id": "learn", "kind": "explain"},
                {"id": "apply", "kind": "choice", "mode": "determinate", "question": "Which claim is supported?", "answer": 0,
                 "options": [{"text": "The stated claim.", "feedback": "It follows from the source."}, {"text": "An invented claim.", "feedback": "This is not established."}]},
            ],
        }]
        self.concept = self.lesson["concepts"][0]

    def test_all_eighteen_use_one_catalogue_and_activity_format(self):
        entries = server.gallery_index()
        self.assertEqual(len(entries), 18)
        self.assertEqual(len({e["slug"] for e in entries}), 18)
        files = {p.stem for p in (ROOT / "lemma/examples/gallery").glob("*.json") if p.stem != "index"}
        self.assertEqual(files, {e["slug"] for e in entries})
        cards = server.api_gallery({})
        self.assertEqual([c["slug"] for c in cards], [e["slug"] for e in entries])
        for entry in entries:
            with self.subTest(slug=entry["slug"]):
                lesson, source = server.load_gallery(entry["slug"])
                self.assertEqual(list(L.check_lesson(lesson, source)), [])
                self.assertTrue(all(c.get("activities") for c in lesson["concepts"]))
                self.assertEqual(server.api_gallery_lesson(entry["slug"])["id"], lesson["id"])
                html = export.lesson_html(lesson)
                self.assertIn("connect-src 'none'", html)
                self.assertIn("LemmaPlayer.mount", html)
                payload = html.split('<script type="application/json" id="lesson-data">')[1].split('</script>')[0]
                self.assertEqual(json.loads(payload)["concepts"], lesson["concepts"])

    def test_model_free_lesson_is_grounded_and_factchecked_including_choices(self):
        self.assertNotIn("model", self.concept)
        self.assertEqual(list(L.check_lesson(self.lesson, self.source)), [])
        text = factcheck.concept_text(self.concept, 1)
        for a in self.concept["activities"]:
            if a["kind"] == "choice":
                self.assertIn(a["question"], text)
                for o in a["options"]:
                    self.assertIn(o["feedback"], text)
        self.concept["understand"]["quote"] = "This invented sentence is not present in the source document."
        self.assertTrue(L.check_lesson(self.lesson, self.source))

    def test_invalid_activities_are_rejected(self):
        base = self.concept
        mutations = [
            lambda c: c.update(activities=[]),
            lambda c: c["activities"].append(None),
            lambda c: c["activities"][1].update(id=c["activities"][0]["id"]),
            lambda c: c["activities"][1].update(kind="execute_script"),
            lambda c: c["activities"][1].update(answer=True),
            lambda c: c["activities"][1]["options"][0].update(feedback=""),
            lambda c: c["activities"].reverse(),
            lambda c: c["activities"][1].update(mode="interpretive"),
            lambda c: c["activities"].append(dict(id="bad_goal", kind="goal", i=0)),
        ]
        for mutate in mutations:
            c = copy.deepcopy(base)
            mutate(c)
            with self.subTest(concept=c):
                self.assertTrue(L.check_concept(c, None))

    def test_interpretation_has_no_answer_key_and_opening_is_optional(self):
        a = self.concept["activities"][1]
        a["mode"] = "interpretive"
        a.pop("answer")
        self.assertEqual(list(L.check_concept(self.concept, None)), [])
        opening = copy.deepcopy(a)
        opening.update(id="first_judgment", mode="opening")
        self.concept["activities"].insert(0, opening)
        self.assertEqual(list(L.check_concept(self.concept, None)), [])

    def every_block(self):
        """A model-free concept that uses every teaching and response block."""
        quote_a, quote_b = "A source quotation with enough words to ground this small teaching example.", "Separate schools were found to be equal in their buildings and teachers."
        source = quote_a + " " + quote_b
        c = copy.deepcopy(self.concept)
        c["activities"] = [
            {"id": "first", "kind": "choice", "mode": "opening", "question": "Can equal buildings make equal schools?",
             "options": [{"text": "Yes", "feedback": "That was the old test."}, {"text": "No", "feedback": "That is the Court's conclusion."}]},
            {"id": "learn", "kind": "explain"},
            {"id": "steps", "kind": "worked", "title": "Apply the old test", "steps": [{"text": "Compare buildings."}, {"text": "Compare teachers.", "result": "Equal"}], "takeaway": "The old test passes."},
            {"id": "cases", "kind": "compare", "prompt": "Compare two schools.", "hypothetical": True, "cases": [{"label": "School A", "text": "Mixed classes."}, {"label": "School B", "text": "Separated by law."}], "takeaway": "Only separation differs."},
            {"id": "history", "kind": "stages", "prompt": "Follow the cases.", "stages": [{"label": "1950", "text": "Graduate schools differed in facilities."}, {"label": "1954", "text": "The schools were equal."}], "takeaway": "The escape route closed."},
            {"id": "claims", "kind": "choice", "mode": "determinate", "multi": True, "answers": [0, 2], "question": "Which claims are supported?", "hints": ["Look at the holding."],
             "options": [{"text": "A", "feedback": "Supported."}, {"text": "B", "feedback": "Not supported."}, {"text": "C", "feedback": "Supported."}]},
            {"id": "pairs", "kind": "match", "prompt": "Match each case.", "pairs": [{"id": "p1", "text": "Sweatt", "target": "Unequal facilities", "feedback": "Won on facilities."}, {"id": "p2", "text": "Brown", "target": "Equal facilities", "feedback": "Faced the doctrine."}], "takeaway": "Facilities decided the earlier case."},
            {"id": "chain", "kind": "order", "prompt": "Order the chain.", "items": ["Separation", "Feeling inferior", "Less motivation"], "explanation": "Each causes the next."},
            {"id": "path", "kind": "trace", "prompt": "Trace the harm.", "path": True, "nodes": [{"id": "law", "label": "Law", "x": 10, "y": 50}, {"id": "stigma", "label": "Stigma", "x": 50, "y": 50}, {"id": "learning", "label": "Learning", "x": 90, "y": 50}],
             "edges": [{"from": "law", "to": "stigma"}, {"from": "stigma", "to": "learning"}], "answer": ["law", "stigma", "learning"], "explanation": "The harm runs through stigma."},
            {"id": "evidence", "kind": "passage", "question": "Which passage says the schools were equalized?", "answer": 1,
             "options": [{"quote": quote_a, "feedback": "This is about something else."}, {"quote": quote_b, "feedback": "This is the finding."}]},
            {"id": "guess", "kind": "estimate", "question": "How many features were compared?", "answer": 4, "tolerance": 0, "explanation": "Buildings, curricula, qualifications, pay."},
            {"id": "again", "kind": "choice", "mode": "interpretive", "revisits": "first", "question": "Now, can equal buildings make equal schools?",
             "options": [{"text": "Yes", "feedback": "The Court disagreed."}, {"text": "No", "feedback": "The Court's reasoning."}]},
        ]
        c["understand"]["quote"] = quote_a
        return c, source

    def test_every_block_validates_and_reaches_the_fact_check(self):
        c, source = self.every_block()
        self.assertEqual(list(L.check_concept(c, L.normalize_for_match(source))), [])
        text = factcheck.concept_text(c, 1)
        for marker in ("WORKED EXAMPLE", "COMPARISON (a labelled hypothetical case)", "STAGED EVIDENCE", "MATCHING", "ORDERING", "TRACING", "SUPPORTING PASSAGE", "ESTIMATE"):
            self.assertIn(marker, text)
        self.assertIn("Separation -> Feeling inferior -> Less motivation", text)
        self.assertIn("Law -> Stigma -> Learning", text)
        lesson = dict(self.lesson, concepts=[c])
        self.assertEqual(list(L.check_lesson(lesson, source)), [])
        self.assertIn("LemmaActivities", export.lesson_html(lesson))

    def test_invalid_new_blocks_are_rejected(self):
        c, source = self.every_block()
        norm = L.normalize_for_match(source)
        at = {a["id"]: i for i, a in enumerate(c["activities"])}
        mutations = {
            "worked step": lambda c: c["activities"][at["steps"]].update(steps=[{"text": "only one"}]),
            "compare case": lambda c: c["activities"][at["cases"]]["cases"][0].pop("text"),
            "compare values without a model": lambda c: c["activities"][at["cases"]]["cases"][0].update(values={"x": 1}),
            "multi with one answer key": lambda c: c["activities"][at["claims"]].update(answer=0),
            "multi interpretive": lambda c: c["activities"][at["claims"]].update(mode="interpretive"),
            "match not one to one": lambda c: c["activities"][at["pairs"]]["pairs"][1].update(target="Unequal facilities"),
            "order repeats": lambda c: c["activities"][at["chain"]].update(items=["a", "a", "b"]),
            "trace off the edges": lambda c: c["activities"][at["path"]].update(answer=["law", "learning"]),
            "trace unknown node": lambda c: c["activities"][at["path"]].update(answer=["nowhere"]),
            "trace node off the canvas": lambda c: c["activities"][at["path"]]["nodes"][0].update(x=140),
            "invented passage": lambda c: c["activities"][at["evidence"]]["options"][0].update(quote="An invented sentence that the source never contains anywhere."),
            "estimate without tolerance": lambda c: c["activities"][at["guess"]].pop("tolerance"),
            "too many hints": lambda c: c["activities"][at["claims"]].update(hints=["a", "b", "c", "d"]),
            "revisit of a scored question": lambda c: c["activities"][at["again"]].update(revisits="claims"),
            "hypothetical not a flag": lambda c: c["activities"][at["cases"]].update(hypothetical="yes"),
            "model block without a model": lambda c: c["activities"].append({"id": "tour", "kind": "watch"}),
            "practice before teaching": lambda c: c["activities"].insert(0, c["activities"].pop(at["chain"])),
        }
        for name, mutate in mutations.items():
            bad = copy.deepcopy(c)
            mutate(bad)
            with self.subTest(name):
                self.assertTrue(L.check_concept(bad, norm))

    def test_compare_values_and_construction_steps_follow_their_ranges(self):
        c = copy.deepcopy(EXAMPLE["concepts"][0])
        k = next(x for x in c["model"]["controls"] if x.get("type", "slider") == "slider")
        c["activities"].insert(1, {"id": "gates", "kind": "compare", "prompt": "Low or high?",
                                   "cases": [{"label": "Low", "values": {k["id"]: k["min"]}}, {"label": "High", "values": {k["id"]: k["max"]}}], "takeaway": "Both change."})
        self.assertEqual([p for p in L.check_concept(c, None) if "gates" in p or "activities[1]" in p], [])
        c["activities"][1]["cases"][1]["values"] = {k["id"]: k["max"] + abs(k["max"] - k["min"]) + 1}
        self.assertTrue(any("within its control's range" in p for p in L.check_concept(c, None)))
        steps = {"id": "build", "kind": "construction", "title": "Bisect", "prompt": "Build it.", "takeaway": "Done.",
                 "steps": [{"label": "Circle", "note": "Radius AB.", "shapes": [{"type": "circle", "x": 30, "y": 50, "r": 40}]},
                           {"label": "Join", "note": "Join.", "shapes": [{"type": "line", "x1": 30, "y1": 50, "x2": 70, "y2": 50}]}]}
        concept = copy.deepcopy(self.concept)
        concept["activities"].append(steps)
        self.assertEqual(list(L.check_concept(concept, None)), [])
        steps["steps"][0]["shapes"][0]["type"] = "spiral"
        self.assertTrue(L.check_concept(concept, None))

    def test_passages_name_their_source_in_a_combined_lesson(self):
        c, source = self.every_block()
        bundle = json.dumps({"lemma_sources": [{"id": "s1", "title": "One", "url": "", "text": source}]})
        sources = L.source_map(bundle)
        self.assertTrue(L.check_activity_attribution(c, sources, "c"))  # no source_id yet
        for o in c["activities"][[a["id"] for a in c["activities"]].index("evidence")]["options"]:
            o["source_id"] = "s1"
        self.assertEqual(L.check_activity_attribution(c, sources, "c"), [])

    def test_example_and_gallery_share_canonical_content(self):
        example, source = server.load_example()
        gallery, gallery_source = server.load_gallery("galton-1886")
        self.assertEqual(example["concepts"], gallery["concepts"])
        self.assertEqual(source, gallery_source)

    def test_non_galton_sources_have_one_checked_in_representation(self):
        expected = set()
        for entry in server.gallery_index():
            if entry["slug"] == "galton-1886":
                self.assertEqual(entry["source_file"], "galton-1886.txt")
                continue
            relative = f"sources/{entry['slug']}.txt"
            expected.add(entry["slug"])
            self.assertEqual(entry["source_file"], relative)
            lesson, source = server.load_gallery(entry["slug"])
            # A lesson built from several sources keeps their bundle, each source holding only its own quotes.
            sources = list(L.source_map(source).values()) or [{"url": lesson["source"]["url"], "text": source}]
            for s in sources:
                self.assertTrue(s["text"].startswith("VERIFIED QUOTATION EXCERPTS — not the complete source.\n"))
                self.assertIn(s["url"], s["text"])
            self.assertEqual(list(L.check_lesson(lesson, source)), [])
            broken = copy.deepcopy(lesson)
            broken["concepts"][0]["understand"]["quote"] = "An invented passage absent from all the checked in source excerpts."
            self.assertTrue(L.check_lesson(broken, source))
        self.assertEqual({p.stem for p in (ROOT / "lemma/examples/sources").glob("*.txt")}, expected)

    def test_non_galton_metadata_has_one_shape(self):
        keys = None
        for entry in server.gallery_index():
            if entry["slug"] == "galton-1886":
                continue
            lesson = json.loads((ROOT / f"lemma/examples/gallery/{entry['slug']}.json").read_text())
            shape = set(lesson) - {"sources", "category", "flags"}  # a multi-source build adds its sources, Jev's category and review flags
            keys = keys or shape
            self.assertEqual(shape, keys, entry["slug"])
            self.assertIsInstance(datetime.fromisoformat(lesson["created"]), datetime)
            self.assertEqual(set(lesson["provider"]), {"name", "model"})
            metadata = lesson["generation"]
            self.assertEqual(set(metadata), {"provider", "model", "pipeline", "source_chars", "omitted"})
            self.assertEqual(metadata["model"], lesson["provider"]["model"])
            self.assertEqual(metadata["provider"], "claude")
            self.assertEqual(metadata["pipeline"], "lemma.generate.make_outline + build_lesson")
            self.assertGreater(metadata["source_chars"], 0)
            self.assertEqual(metadata["omitted"], len(lesson["omitted"]))

    def test_model_activities_cannot_skip_the_prediction_reveal(self):
        lesson, _ = server.load_gallery("galton-1886")
        c = lesson["concepts"][0]
        c["activities"] = [a for a in c["activities"] if a["kind"] != "reveal"]
        self.assertTrue(any("followed by reveal" in p for p in L.check_concept(c, None)))

    def test_new_gallery_previews_reuse_the_lessons_interactions(self):
        for card in server.api_gallery({}):
            lesson, _ = server.load_gallery(card["slug"])
            entry = next(e for e in server.gallery_index() if e["slug"] == card["slug"])
            cover = next(c for c in lesson["concepts"] if c["id"] == entry["cover"])
            self.assertEqual(card["cover"]["model"], cover.get("model"))
            if cover.get("model"):
                self.assertTrue(card["cover"]["model"]["visual"])
            else:  # a lesson taught without models shows a hands-on activity, or its idea, on its card
                hands_on = [a for a in cover["activities"] if a["kind"] in ("sort", "construction", "inheritance")]
                self.assertEqual(card["cover"]["activity"], hands_on[0] if hands_on else None)
            if lesson.get("generation"):
                self.assertEqual(lesson["generation"]["model"], "claude-opus-5-5")
                self.assertEqual(lesson["generation"]["omitted"], len(lesson["omitted"]))

    @unittest.skipUnless(shutil.which("node"), "node is needed to exercise activity event handlers")
    def test_interactive_teaching_event_handlers(self):
        subprocess.run(["node", "tests/activities.js"], cwd=ROOT, check=True, capture_output=True, text=True)

    def test_invalid_evidence_boards_are_rejected(self):
        c = self.concept
        board = {"id": "board", "kind": "sort", "title": "Classify evidence", "prompt": "Connect each item to its role.", "takeaway": "Roles differ.",
                 "groups": [{"id": "evidence", "label": "Evidence"}, {"id": "claim", "label": "Claim"}],
                 "cards": [{"id": "one", "text": "A record.", "group": "evidence", "feedback": "This supplies evidence."}, {"id": "two", "text": "A conclusion.", "group": "claim", "feedback": "This is a claim."}]}
        c["activities"].insert(1, board)
        board["cards"][0]["group"] = "invented_category"
        self.assertTrue(any("existing group" in p for p in L.check_concept(c, None)))
        board["cards"][0]["group"] = board["groups"][0]["id"]
        board["cards"][0]["feedback"] = ""
        self.assertTrue(L.check_concept(c, None))


if __name__ == "__main__":
    unittest.main()
