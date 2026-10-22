"""How outlining and building fail, and what the learner and the model are told when they do.

A scripted FakeProvider stands in for the model; the Jev stand-in from fakejev answers every check.
"""

from __future__ import annotations

import copy
import json
import time
import unittest
from unittest.mock import patch

from test_lemma import EXAMPLE, SOURCE, FakeConversation, FakeProvider, wait
from lemma import generate, jev
from lemma.llm import ProviderError, Reply

PAPER = {"text": SOURCE, "title": "Galton", "url": ""}


def outline():
    job = wait(generate.start(generate.Job("outline"), generate.make_outline, FakeProvider(), SOURCE, ""))
    assert job.status == "done", job.error
    return job.result


class Recording(FakeProvider):
    """Keeps every message the model was sent, in order."""

    def __init__(self):
        super().__init__()
        self.sent = []

    def conversation(self, system, document):
        conv = FakeConversation(self, document)
        send = conv.send

        def recorded(text, cancelled=None, on_progress=None):
            self.sent.append(text)
            return send(text, cancelled, on_progress)

        conv.send = recorded
        return conv


class Scripted(Recording):
    """Answers the outline task with `replies` in turn (text or a Reply), then as FakeProvider does."""

    def __init__(self, *replies):
        super().__init__()
        self.replies = list(replies)

    def reply(self, task, turn):
        if "propose a path" in task.lower() and self.replies:
            r = self.replies.pop(0)
            return r if isinstance(r, Reply) else Reply(r, "end_turn")
        return super().reply(task, turn)


class OutlineChecks(unittest.TestCase):
    def test_an_outline_is_refused_with_the_part_that_is_wrong(self):
        base = outline()

        def broken(fn):
            o = copy.deepcopy(base)
            fn(o["concepts"])
            return generate.check_outline(o, SOURCE)

        cases = [
            ("concepts[1] must be an object", lambda cs: cs.__setitem__(1, "a concept")),
            ("concepts[1].id must be unique lower_snake_case", lambda cs: cs[1].update(id=cs[0]["id"])),
            ("concepts[0] needs 'title'", lambda cs: cs[0].update(title=" ")),
            ("concepts[0].visual must be one of", lambda cs: cs[0].update(visual="hologram")),
            ("concepts[1].builds_on must be the id of an earlier concept, or null", lambda cs: cs[1].update(builds_on="nowhere")),
            ("concepts[1] has no model, so it cannot build on another concept's model", lambda cs: cs[1].update(visual="none", builds_on=cs[0]["id"], plans=None)),
            ("concepts[1].needs must be a list of concept ids", lambda cs: cs[1].update(needs="mid_parent")),
            ("concepts[1].needs names 'ghost', which is not a concept in this outline", lambda cs: cs[1].update(needs=["ghost"])),
            ("concepts[0].plans must list 2–3 plans", lambda cs: cs[0].update(plans=[])),
            ("concepts[0].plans[0] needs 'why'", lambda cs: cs[0]["plans"][0].update(why="")),
            ("concepts[0].plans[0].blocks must be 2–12 activity kinds", lambda cs: cs[0]["plans"][0].update(blocks=["dance", "sing"])),
        ]
        self.assertEqual(generate.check_outline(base, SOURCE), [])
        for expected, fn in cases:
            with self.subTest(expected=expected):
                found = broken(fn)
                self.assertTrue(any(expected in p for p in found), found)
        self.assertEqual(generate.check_outline(["not", "an", "outline"]), ["the reply must be a JSON object"])

    def test_a_reviewed_outline_is_tidied_into_an_order_that_works(self):
        o = outline()
        first, second, third = [c["id"] for c in o["concepts"]]
        o["concepts"][0]["needs"] = [second, "deleted_concept"]  # moved above what it relies on, and relies on a removed one
        o["concepts"][1]["needs"] = []
        o["concepts"][1]["builds_on"] = "deleted_concept"
        tidy = generate.order_outline(o)
        self.assertEqual([c["id"] for c in tidy["concepts"]], [second, first, third])
        self.assertEqual(tidy["concepts"][1]["needs"], [second])
        self.assertIsNone(tidy["concepts"][0]["builds_on"])
        self.assertEqual(generate.check_outline(tidy, SOURCE), [])

    def test_a_cycle_is_left_for_the_check_to_report(self):
        o = outline()
        a, b = o["concepts"][0]["id"], o["concepts"][1]["id"]
        o["concepts"][0]["needs"], o["concepts"][1]["needs"] = [b], [a]
        tidy = generate.order_outline(o)
        self.assertEqual([c["id"] for c in tidy["concepts"]][:2], [a, b])
        self.assertTrue(any("which comes later" in p for p in generate.check_outline(tidy, SOURCE)))


class Repairs(unittest.TestCase):
    def run_outline(self, provider):
        return wait(generate.start(generate.Job("outline"), generate.make_outline, provider, SOURCE, ""))

    def test_a_reply_that_is_not_json_is_sent_back_once_and_then_used(self):
        fp = Scripted("Sorry, I can't produce that.")
        job = self.run_outline(fp)
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(len(fp.sent), 2)
        self.assertIn("the reply was not valid JSON (no JSON object in the reply)", fp.sent[1])

    def test_a_cut_off_reply_is_asked_to_be_more_concise(self):
        fp = Scripted(Reply('{"title": "Galton', "max_tokens"))
        job = self.run_outline(fp)
        self.assertEqual(job.status, "done", job.error)
        self.assertIn("the reply was cut off; make it more concise", fp.sent[1])

    def test_an_outline_that_never_passes_stops_with_its_problems(self):
        fp = Scripted(*["{}"] * (generate.MAX_REPAIRS + 1))
        job = self.run_outline(fp)
        self.assertEqual(job.status, "error")
        self.assertTrue(job.error.startswith("Couldn't produce a usable outline for this paper: primer: needs 3–6 pages"), job.error)
        self.assertIn("; needs 'title'", job.error)
        self.assertEqual(len(fp.sent), generate.MAX_REPAIRS + 1)
        self.assertEqual({s["id"]: s["state"] for s in job.snapshot()["steps"]}["outline"], "failed")

    def test_a_concept_without_activities_is_asked_for_them(self):
        class NoActivitiesFirst(Recording):
            def reply(self, task, turn):
                r = super().reply(task, turn)
                if "Its id must be" in task and turn == 1:
                    c = generate.extract_json(r.text)
                    c.pop("activities", None)
                    return Reply(json.dumps(c), "end_turn")
                return r

        fp = NoActivitiesFirst()
        job = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, PAPER, outline(), ""))
        self.assertEqual(job.status, "done", job.error)
        self.assertTrue(any("needs 'activities', the learner's screens in order" in m for m in fp.sent))


class BuildFailures(unittest.TestCase):
    def build(self, provider, o=None):
        return wait(generate.start(generate.Job("build"), generate.build_lesson, provider, PAPER, o or outline(), ""))

    def test_nothing_to_build_when_every_concept_is_known(self):
        o = outline()
        for c in o["concepts"]:
            c["known"] = True
        job = self.build(FakeProvider(), o)
        self.assertEqual((job.status, job.error), ("error", "Every concept is marked as already known, so there is nothing to build."))

    def test_a_failed_warm_up_does_not_stop_the_build(self):
        class ColdCache(FakeProvider):
            def warm(self, system, document):
                raise ProviderError("caching is not supported")

        job = self.build(ColdCache())
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(len(job.result["concepts"]), 3)

    def test_a_concept_the_model_fails_on_is_left_out_with_the_reason(self):
        class FailsOne(FakeProvider):
            def reply(self, task, turn):
                if 'Its id must be "why_regression"' in task:
                    raise ProviderError("The model is overloaded.")
                return super().reply(task, turn)

        job = self.build(FailsOne())
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(job.result["omitted"], [{"title": EXAMPLE["concepts"][2]["title"], "reason": "The model is overloaded."}])
        step = {s["id"]: s for s in job.snapshot()["steps"]}["why_regression"]
        self.assertEqual(step["state"], "failed")
        self.assertIn("The model is overloaded.", step["detail"])

    def test_no_lesson_when_no_concept_passes(self):
        class Down(FakeProvider):
            def reply(self, task, turn):
                if "Its id must be" in task:
                    raise ProviderError("Service unavailable.")
                return super().reply(task, turn)

        job = self.build(Down())
        self.assertEqual(job.status, "error")
        self.assertTrue(job.error.startswith("No concept passed the quality checks, so there is no lesson to show. Service unavailable."), job.error)

    def test_a_lesson_that_fails_its_final_check_is_not_returned(self):
        o = outline()
        o["aha"] = None
        o["summary"] = "x" * 1600  # past the finished lesson's limit, which only the final check sees once concepts are built
        job = self.build(FakeProvider(), o)
        self.assertEqual(job.status, "error")
        self.assertTrue(job.error.startswith("The assembled lesson failed its final check: lesson.intro: 'summary' is too long"), job.error)

    def test_cancelling_mid_build_stops_the_rest(self):
        holder = {}

        class CancelsDuringFirst(FakeProvider):
            def reply(self, task, turn):
                if 'Its id must be "mid_parent"' in task:
                    holder["job"].cancelled.set()
                return super().reply(task, turn)

        with patch.object(generate, "WORKERS", 1):
            job = generate.Job("build")
            holder["job"] = job
            wait(generate.start(job, generate.build_lesson, CancelsDuringFirst(), PAPER, outline(), ""))
        self.assertEqual((job.status, job.error), ("cancelled", "Cancelled."))
        states = {s["id"]: s["state"] for s in job.snapshot()["steps"]}
        self.assertEqual(states["regression_line"], "waiting")  # never started

    def test_an_outline_without_activity_plans_builds_without_asking_jev_to_choose(self):
        o = outline()
        for c in o["concepts"]:
            c.pop("plans")
        with patch.object(jev, "ask", wraps=jev.ask) as asked:
            job = self.build(FakeProvider(), o)
        self.assertEqual(job.status, "done", job.error)
        self.assertNotIn("activity_plans", job.result)
        self.assertFalse(any("none_suitable" in json.dumps(call.args[1]) for call in asked.call_args_list))


class JevChoosesPlans(unittest.TestCase):
    def build_with_plan_answer(self, answer):
        def ask(state, questions, timeout):
            if any("none_suitable" in q.get("criteria", {}) for q in questions.values()):
                return answer(questions)
            from fakejev import answer as harmless
            return harmless(state, questions, timeout)

        with patch.object(jev, "ask", side_effect=ask):
            return wait(generate.start(generate.Job("build"), generate.build_lesson, FakeProvider(), PAPER, outline(), ""))

    def test_an_unreadable_choice_stops_the_build_before_anything_is_drafted(self):
        for name, answer in (("unknown option", lambda qs: {k: {"choice": "p9"} for k in qs}), ("missing concept", lambda qs: {})):
            with self.subTest(name):
                job = self.build_with_plan_answer(answer)
                self.assertEqual((job.status, job.error), ("error", "Couldn't choose how to teach the concepts just now. Retry in a moment."))
                self.assertEqual({s["id"]: s for s in job.snapshot()["steps"]}["plans"]["detail"], "The checking service's reply couldn't be read")

    def test_none_suitable_lets_the_model_choose(self):
        job = self.build_with_plan_answer(lambda qs: {k: {"choice": "none_suitable", "confidence": 0.8} for k in qs})
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual({p["chosen"] for p in job.result["activity_plans"]}, {"none_suitable"})
        self.assertEqual({p["plan"] for p in job.result["activity_plans"]}, {None})


class QuestionChecks(unittest.TestCase):
    """The outline of a lesson asked for with a question has to answer it."""

    def test_jev_reads_the_question_against_the_outline(self):
        seen = {}

        def ask(state, questions, timeout):
            seen.update(state=state, questions=questions)
            return {"_model": "jev-test", "answers": {"choice": "partly"}}
        o = outline()
        with patch.object(jev, "ask", side_effect=ask):
            self.assertEqual(generate.answers_question("Why are tall parents' children shorter?", o), "partly")
        self.assertEqual(seen["state"]["question"], "Why are tall parents' children shorter?")
        self.assertEqual(seen["state"]["lesson"]["aha"], o["aha"])
        self.assertEqual(set(seen["questions"]["answers"]["criteria"]), {"answers", "partly", "no"})

    SEARCH = {"query": "Why are tall parents' children usually shorter?", "field": ["statistics"],
              "subjects": [{"title": "Regression toward the mean", "need": 4.5, "relation": "part"},
                           {"title": "Mean", "need": 3.2, "relation": "prerequisite"}],
              "not_covered": ["Galton board"]}

    def asked(self, *edits, answers=None):
        """Makes an outline for SEARCH; each of `edits` changes one outline reply in turn, the last one every later reply.
        `answers` are Jev's readings of the question, in turn."""
        class Answering(Recording):
            def reply(self, task, turn):
                r = super().reply(task, turn)
                if "propose a path" in task.lower():
                    o = generate.extract_json(r.text)
                    o["assumes"] = ["Galton board"]
                    for c in o["concepts"]:
                        c["subject"] = {"mid_parent": "Mean", "regression_line": "Regression toward the mean"}.get(c["id"])
                    edits[min(turn, len(edits)) - 1](o)
                    return Reply(json.dumps(o), "end_turn")
                return r
        readings = list(answers or ["answers"])

        def ask(state, questions, timeout):
            if "answers" in questions:
                return {"_model": "jev-test", "answers": {"choice": readings.pop(0) if len(readings) > 1 else readings[0]}}
            from fakejev import answer as harmless
            return harmless(state, questions, timeout)
        fp = Answering()
        with patch.object(jev, "ask", side_effect=ask):
            job = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "beginner", self.SEARCH))
        return job, fp

    def test_the_outline_is_asked_to_answer_the_question_from_what_it_builds_on(self):
        job, fp = self.asked(lambda o: None)
        self.assertEqual(job.status, "done", job.error)
        task = fp.sent[0]
        self.assertIn("The learner came with a question: «Why are tall parents' children usually shorter?» (field: Statistics & probability)", task)
        self.assertIn("- Regression toward the mean (needed, part of the answer; no source)", task)
        self.assertIn("- Mean (helps, learn first; no source)", task)
        self.assertIn("- Galton board (needed; no source)", task)
        self.assertEqual(job.result["question"], self.SEARCH["query"])
        self.assertEqual([s["title"] for s in job.result["subjects"]], ["Regression toward the mean", "Mean", "Galton board"])

    def test_a_wrong_subject_or_a_late_prerequisite_is_sent_back(self):
        def ghost(o):
            o["concepts"][0]["subject"] = "Ghost"

        def late(o):
            o["concepts"][0]["subject"] = None
            o["concepts"][2]["subject"] = "Mean"  # after the core concepts

        job, fp = self.asked(ghost, late, lambda o: None)
        self.assertEqual(job.status, "done", job.error)
        self.assertIn("concepts[0].subject must be one of the listed subjects", fp.sent[1])
        self.assertIn("concepts[2] teaches 'Mean', which the learner needs first, so it must come before the core concepts", fp.sent[2])

    def test_an_outline_that_doesnt_answer_the_question_is_sent_back(self):
        job, fp = self.asked(lambda o: None, answers=["no", "partly"])
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(len(fp.sent), 2)
        self.assertIn("the outline must answer the learner's question, «Why are tall parents' children usually shorter?»", fp.sent[1])

    def test_without_a_search_nothing_about_a_question_is_asked(self):
        fp = Recording()
        job = wait(generate.start(generate.Job("outline"), generate.make_outline, fp, SOURCE, "beginner"))
        self.assertEqual(job.status, "done", job.error)
        self.assertNotIn("came with a question", fp.sent[0])
        self.assertNotIn("question", job.result)

    def test_the_lesson_answers_the_question_and_says_what_it_assumes(self):
        job, _ = self.asked(lambda o: None)
        fp = Recording()
        built = wait(generate.start(generate.Job("build"), generate.build_lesson, fp, PAPER, job.result, "beginner"))
        self.assertEqual(built.status, "done", built.error)
        intro = built.result["intro"]
        self.assertEqual((intro["question"], intro["assumes"]), (self.SEARCH["query"], ["Galton board"]))
        concept = next(t for t in fp.sent if 'Its id must be "mid_parent"' in t)
        self.assertIn("the learner asked: «Why are tall parents' children usually shorter?». This concept's part in answering it: Mean", concept)
        self.assertIn("never teach them: Galton board", concept)
        from test_lemma import L
        self.assertEqual(list(L.check_lesson(built.result, SOURCE)), [])

    def test_a_question_needing_two_fields_has_one_concept_that_connects_them(self):
        two = dict(self.SEARCH, field=["statistics", "biology"])

        def bridge_none(o):
            pass

        def bridge_two(o):
            o["concepts"][0]["bridge"] = o["concepts"][1]["bridge"] = True

        def bridge_one(o):
            o["concepts"][2]["bridge"] = True
        with patch.object(self, "SEARCH", two):
            job, fp = self.asked(bridge_none, bridge_two, bridge_one)
        self.assertEqual(job.status, "done", job.error)
        self.assertIn("The question needs both Statistics & probability and Biology: mark the one concept that connects them", fp.sent[0])
        self.assertIn("mark exactly one concept with \"bridge\": true, the one that connects the two fields (found 0)", fp.sent[1])
        self.assertIn("(found 2)", fp.sent[2])
        self.assertEqual(job.result["field"], ["statistics", "biology"])

        seen = {}

        def check(c, paper, n=1, link=None):
            seen[c["id"]] = link
            return []
        with patch.object(generate.factcheck, "check_concept", side_effect=check):
            built = wait(generate.start(generate.Job("build"), generate.build_lesson, Recording(), PAPER, job.result, "beginner"))
        self.assertEqual(built.status, "done", built.error)
        bridge = job.result["concepts"][2]["id"]
        self.assertEqual(built.result["intro"]["bridge"], bridge)
        self.assertEqual({cid: link for cid, link in seen.items() if link}, {bridge: "Statistics & probability and Biology"})

    def test_a_one_field_question_has_no_bridge(self):
        def stray(o):
            o["concepts"][0]["bridge"] = True
        job, fp = self.asked(stray, lambda o: None)
        self.assertEqual(job.status, "done", job.error)
        self.assertNotIn("connects them", fp.sent[0])
        self.assertIn("this question needs one field, so no concept is a \"bridge\"", fp.sent[1])

    def test_a_bridge_concept_is_asked_whether_its_link_has_a_source(self):
        from lemma import factcheck
        concept = copy.deepcopy(EXAMPLE["concepts"][0])
        self.assertFalse(any(k.startswith("unsupported_link") for k in factcheck.questions_for(concept)))
        qs = factcheck.questions_for(concept, link="Psychology and Medicine")
        link = [q for k, q in qs.items() if k.startswith("unsupported_link|")]
        self.assertEqual(len(link), len(factcheck.LENSES))
        self.assertIn("a connection between Psychology and Medicine", link[0]["instructions"])
        yes = lambda state, questions, timeout: {k: {"noul": 0.9 if k.startswith("unsupported_link") else 0.0} for k in questions}
        with patch.object(jev, "ask", side_effect=yes):
            flags = factcheck.check_concept(concept, SOURCE, 1, "Psychology and Medicine")
        self.assertEqual([f.kind for f in flags], ["unsupported_link"])
        self.assertIn("say plainly that these sources don't establish it", flags[0])

    def test_a_check_jev_cannot_make_raises(self):
        for name, effect in (("outage", jev.JevError("the checking service answered 529")),
                             ("unreadable", lambda *a: {"answers": {"choice": "maybe"}})):
            with self.subTest(name), patch.object(jev, "ask", side_effect=effect):
                with self.assertRaisesRegex(generate.GenerationError, "^Couldn't check the outline against your question"):
                    generate.answers_question("q", outline())


class Jobs(unittest.TestCase):
    def test_an_unexpected_error_is_reported_with_an_error_id_and_the_server_lives_on(self):
        def boom(job):
            raise RuntimeError("disk on fire")

        with patch("sys.stderr"):
            job = wait(generate.start(generate.Job("outline"), boom))
        self.assertEqual(job.status, "error")
        self.assertRegex(job.error, r"^Unexpected error: RuntimeError: disk on fire \(error [0-9a-f]{8}\)$")

    def test_finished_jobs_are_forgotten_after_six_hours(self):
        old = generate.Job("build")
        old.status, old.created = "done", time.time() - 6 * 3600 - 1
        running = generate.Job("build")
        running.created = old.created
        generate.JOBS[old.id], generate.JOBS[running.id] = old, running
        wait(generate.start(generate.Job("outline"), lambda job: None))
        self.assertNotIn(old.id, generate.JOBS)
        self.assertIn(running.id, generate.JOBS)  # a job still running is kept however old
        generate.JOBS.pop(running.id)


if __name__ == "__main__":
    unittest.main()
