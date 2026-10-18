"""Offline checks for the shared gallery and model-free activities."""
import copy
import json
import shutil
import subprocess
from pathlib import Path
import unittest

from lemma import export, factcheck, lesson as L, server

ROOT = Path(__file__).resolve().parents[1]


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

    def test_all_twelve_use_one_catalogue_and_activity_format(self):
        entries = server.gallery_index()
        self.assertEqual(len(entries), 12)
        self.assertEqual(len({e["slug"] for e in entries}), 12)
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

    def test_example_and_gallery_share_canonical_content(self):
        example, source = server.load_example()
        gallery, gallery_source = server.load_gallery("galton-1886")
        self.assertEqual(example["concepts"], gallery["concepts"])
        self.assertEqual(source, gallery_source)

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
            self.assertEqual(card["cover"]["model"], cover["model"])
            self.assertTrue(card["cover"]["model"]["visual"])
            if lesson.get("generation"):
                self.assertEqual(lesson["generation"]["model"], "claude-opus-5-5")
                self.assertFalse(lesson["omitted"])

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
