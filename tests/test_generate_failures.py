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
