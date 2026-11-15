"""What a retry does, for every state a build's outline can be in when the build stops.

A build stops three ways: the server restarts (interrupted), something fails (error), or the learner cancels. What a
retry may do depends on the outline:

  A. no outline yet (reading sources, sorting the subject, working out what they build on, proposing the outline):
     a retry proposes an outline; there is nothing to choose.
  B. an outline proposed, waiting for review: the build isn't stopped at all, and a restart doesn't change that.
  C. an outline approved: the learner chooses to continue it (reusing finished concepts) or start over.

Each stop is made as it happens: the step's own code is paused part way, then the server "stops" (its memory of the
build is dropped and its threads never write again), so what's on disk is what a real restart would leave.
"""
import copy
import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import fakejev  # noqa: F401  Jev is essential, so every search and build asks this stand-in
from lemma import generate, server, store
from lemma.llm import ProviderError, Reply
from support import SOURCE, TESTER, call, reset_server, sign_in
from test_lemma import wait
from test_multisource import MultiSourceProvider
from test_saved_concepts import drafted, settle_threads


class Model(MultiSourceProvider):
    id, name, model = "fake", "Fake", "fake-1"


def named(name, model):
    return type(name, (Model,), {"id": name.lower(), "name": name, "model": model})


class Hangs(Model):
    """Hangs on the concepts in `on` (or on the outline, with on="outline") until the server stops or the build is
    cancelled, then fails as a dropped connection does."""

    def __init__(self, on=()):
        super().__init__()
        self.on, self.hanging, self.stopped = on, threading.Event(), threading.Event()

    def conversation(self, system, document):
        conv = super().conversation(system, document)
        send = conv.send

        def hanging(text, cancelled=None, on_progress=None):
            outline = "propose a path" in text.lower()
            if (self.on == "outline" and outline) or (not outline and any(f'Its id must be "{c}"' in text for c in self.on)):
                self.hanging.set()
                while not self.stopped.is_set() and not (cancelled and cancelled.is_set()):
                    time.sleep(.01)
                raise ProviderError("The connection closed.")
            return send(text, cancelled, on_progress)
        conv.send = hanging
        return conv


class BadOutlines(Model):
    def reply(self, task, turn):
        return Reply("{}", "end_turn") if "propose a path" in task.lower() else super().reply(task, turn)


class BadConcepts(Model):
    def reply(self, task, turn):
        return super().reply(task, turn) if "propose a path" in task.lower() else Reply("not JSON", "end_turn")


ALL = ["mid_parent", "regression_line", "why_regression"]


class OutlineResumptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = patch.dict(os.environ, {"LEMMA_HOME": self.tmp.name})
        self.env.start()
        sign_in()
        self.reads = []

        def read(urls):
            self.reads.append(urls[0])
            return SimpleNamespace(title="Galton", url=urls[0], text=SOURCE)
        self.patches = [patch.object(server.builds, "_first_readable", side_effect=read)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for job in list(generate.JOBS.values()):
            job.cancelled.set()
        settle_threads()
        for p in self.patches:
            p.stop()
        reset_server()
        self.env.stop()
        self.tmp.cleanup()

    # ------------------------------------------------------------ helpers

    def settled(self, rid):
        for _ in range(1500):
            record = call(server.api_request, rid)
            if record["status"] != "running":
                return record
            time.sleep(.01)
        self.fail("the build did not settle")

    def create(self, provider=None):
        with patch.object(server.core, "_provider", return_value=provider or Model()):
            return call(server.api_request_create, body={"sources": [{"url": "https://example.org/galton", "title": "Galton"}]})["id"]

    def outlined(self):
        rid = self.create()
        record = self.settled(rid)
        self.assertEqual(record["status"], "awaiting_outline", record.get("error"))
        return rid, record

    def approve(self, rid, outline, provider=None):
        with patch.object(server.core, "_provider", return_value=provider or Model()):
            call(server.api_request_outline, rid, body={"outline": outline})

    def retry(self, rid, mode=None, provider=None):
        with patch.object(server.core, "_provider", return_value=provider or Model()):
            call(server.api_request_retry, rid, body={"mode": mode} if mode else {})
        return self.settled(rid)

    def stop(self, rid, release, locked=True):
        """The server stops: its memory of the build is gone, and the thread left running never writes again."""
        time.sleep(.1)  # the step the build reached is saved
        if locked:
            with server.builds._requests_lock:
                job = generate.JOBS.pop(rid)
        else:  # the build holds the lock where it was stopped
            job = generate.JOBS.pop(rid)
        job.cancelled.set()
        release()
        wait(job)
        record = call(server.api_request, rid)
        self.assertEqual(record["status"], "interrupted")
        return record

    @contextmanager
    def paused(self, target, name, after=False):
        """Pauses `target.name` part way (before it runs, or just `after` it ran) until released; then it fails."""
        reached, released = threading.Event(), threading.Event()
        real = getattr(target, name)

        def pause(*a, **k):
            if after:
                real(*a, **k)
            reached.set()
            released.wait(10)
            raise generate.GenerationError("The server stopped.")
        # A method on a class is patched with its signature, so the pause gets the instance and can run the real one.
        with patch.object(target, name, side_effect=pause, autospec=isinstance(target, type)):
            yield reached, released.set

    def stopped_mid_build(self, finished=("mid_parent", "regression_line"), provider=None, edit=None):
        """A build with an approved outline (changed by `edit` at review), stopped by a restart once the concepts in
        `finished` are done."""
        rid, record = self.outlined()
        outline = record["outline"]
        if edit:
            edit(outline)
        hangs = provider or Hangs([c for c in ALL if c not in finished and not any(x["id"] == c and x.get("known") for x in outline["concepts"])])
        self.approve(rid, outline, hangs)
        self.assertTrue(hangs.hanging.wait(10))
        for _ in range(500):
            if set(store.BuiltConcepts(rid, TESTER).load()) >= set(finished):
                break
            time.sleep(.01)
        return rid, self.stop(rid, hangs.stopped.set)

    # ------------------------------------------------------------ A. no outline yet

    def test_A1_stopped_while_reading_sources_reads_them_again(self):
        with self.paused(server.builds, "_first_readable") as (reached, release):
            rid = self.create()
            self.assertTrue(reached.wait(10))
            stopped = self.stop(rid, release)
        self.assertEqual((stopped["resume"], stopped["error"]), (None, "The server stopped during this build. Retry to start a new attempt."))
        self.assertEqual([s["state"] for s in stopped["steps"]], ["stopped"])
        self.reads.clear()
        self.assertEqual(self.retry(rid)["status"], "awaiting_outline")
        self.assertEqual(self.reads, ["https://example.org/galton"])

    def test_A2_stopped_while_sorting_the_subject_keeps_the_sources_read(self):
        with self.paused(server.builds.categorize, "categorize") as (reached, release):
            rid = self.create()
            self.assertTrue(reached.wait(10))
            stopped = self.stop(rid, release)
        self.assertIsNone(stopped["resume"])
        self.reads.clear()
        with patch.object(server.builds.categorize, "categorize", wraps=server.builds.categorize.categorize) as categorize:
            self.assertEqual(self.retry(rid)["status"], "awaiting_outline")
        self.assertEqual(self.reads, [])  # saved as soon as they were read
        self.assertEqual(categorize.call_count, 1)  # the subject it hadn't finished is sorted now

    def test_A3_stopped_while_working_out_what_the_sources_build_on_keeps_the_sources_and_subject(self):
        with self.paused(server.builds.search, "source_subjects") as (reached, release):
            rid = self.create()
            self.assertTrue(reached.wait(10))
            stopped = self.stop(rid, release)
        self.assertIsNone(stopped["resume"])
        category = store.load_request(rid, TESTER)["category"]
        self.reads.clear()
        with patch.object(server.builds.categorize, "categorize") as categorize:
            self.assertEqual(self.retry(rid)["status"], "awaiting_outline")
        self.assertEqual(self.reads, [])  # kept
        categorize.assert_not_called()
        self.assertEqual(store.load_request(rid, TESTER)["category"], category)

    def test_A4_stopped_while_proposing_the_outline_keeps_what_it_had_worked_out(self):
        hangs = Hangs("outline")
        rid = self.create(hangs)
        self.assertTrue(hangs.hanging.wait(10))
        stopped = self.stop(rid, hangs.stopped.set)
        self.assertIsNone(stopped["resume"])
        self.assertEqual({s["id"]: s["state"] for s in stopped["steps"]}["outline"], "stopped")
        self.reads.clear()
        with patch.object(server.builds.search, "source_subjects") as subjects:
            self.assertEqual(self.retry(rid)["status"], "awaiting_outline")
        self.assertEqual(self.reads, [])
        subjects.assert_not_called()  # kept with the request: a retry doesn't pay for it again

    def test_A5_an_outline_that_never_passes_is_an_error_and_retrying_proposes_another(self):
        rid = self.create(BadOutlines())
        failed = self.settled(rid)
        self.assertEqual(failed["status"], "error")
        self.assertTrue(failed["error"].startswith("Couldn't produce a usable outline"))
        self.assertIsNone(failed["resume"])
        self.assertEqual(self.retry(rid)["status"], "awaiting_outline")

    def test_A6_cancelled_while_proposing_the_outline(self):
        hangs = Hangs("outline")
        rid = self.create(hangs)
        self.assertTrue(hangs.hanging.wait(10))
        call(server.api_request_cancel, rid)
        cancelled = self.settled(rid)
        self.assertEqual((cancelled["status"], cancelled["resume"]), ("cancelled", None))
        self.assertEqual({s["id"]: s for s in cancelled["steps"]}["outline"]["detail"], "Not built: you cancelled the build")
        self.assertEqual(self.retry(rid)["status"], "awaiting_outline")

    # ------------------------------------------------------------ B. an outline waiting for review

    def test_B1_a_restart_at_review_changes_nothing_and_it_can_still_be_approved(self):
        rid, record = self.outlined()
        generate.JOBS.pop(rid)  # the server restarts while the outline waits
        after = call(server.api_request, rid)
        self.assertEqual((after["status"], after["resume"], after["outline"]), ("awaiting_outline", None, record["outline"]))
        self.approve(rid, after["outline"])
        self.assertEqual(self.settled(rid)["status"], "done")

    def test_B2_a_restart_at_review_and_then_adding_a_suggested_source(self):
        rid, _ = self.outlined()
        generate.JOBS.pop(rid)
        record = store.load_request(rid, TESTER)
        record["outline"]["subjects"] = [{"title": "Variance", "url": "https://en.wikipedia.org/wiki/Variance", "source": None}]
        store.save_request(record, TESTER)
        with patch.object(server.core, "_provider", return_value=Model()):
            call(server.api_request_add, rid, body={"titles": ["Variance"]})
        self.assertEqual(self.settled(rid)["status"], "awaiting_outline")
        self.assertEqual(len(json.loads(store.load_request(rid, TESTER)["paper"]["text"])["lemma_sources"]), 2)

    def test_B3_cancelled_at_review_then_retried_proposes_a_new_outline_without_asking(self):
        rid, _ = self.outlined()
        call(server.api_request_cancel, rid)
        cancelled = call(server.api_request, rid)
        self.assertEqual((cancelled["status"], cancelled["resume"]), ("cancelled", None))  # never approved: no choice
        again = Model()
        self.assertEqual(self.retry(rid, provider=again)["status"], "awaiting_outline")
        self.assertIn("outline", again.tasks)  # proposed again, not the cancelled one brought back

    def test_B4_a_build_waiting_for_review_cant_be_retried(self):
        rid, _ = self.outlined()
        for mode in (None, "continue", "start_over"):
            with self.assertRaises(server.ApiError) as e:
                self.retry(rid, mode)
            self.assertEqual(e.exception.status, 409)

    def test_B5_stopped_while_reading_sources_added_at_review_reads_them_again(self):
        rid, _ = self.outlined()
        record = store.load_request(rid, TESTER)
        record["outline"]["subjects"] = [{"title": "Variance", "url": "https://en.wikipedia.org/wiki/Variance", "source": None}]
        store.save_request(record, TESTER)
        with self.paused(server.builds, "_first_readable") as (reached, release):
            with patch.object(server.core, "_provider", return_value=Model()):
                call(server.api_request_add, rid, body={"titles": ["Variance"]})
            self.assertTrue(reached.wait(10))
            stopped = self.stop(rid, release)
        self.assertIsNone(stopped["resume"])  # the outline was being remade: there's none to continue
        self.reads.clear()
        self.assertEqual(self.retry(rid)["status"], "awaiting_outline")
        self.assertEqual(self.reads, ["https://en.wikipedia.org/wiki/Variance"])  # the added source, not the first again
        self.assertEqual([s["title"] for s in json.loads(store.load_request(rid, TESTER)["paper"]["text"])["lemma_sources"]], ["Galton", "Variance"])

    # ------------------------------------------------------------ C. an approved outline

    def test_C1_stopped_while_choosing_how_to_teach_offers_the_choice_with_nothing_kept(self):
        rid, record = self.outlined()
        with self.paused(generate, "choose_plans") as (reached, release):
            self.approve(rid, record["outline"])
            self.assertTrue(reached.wait(10))
            stopped = self.stop(rid, release)
        self.assertEqual(stopped["resume"]["kept"], 0)
        again = Model()
        self.assertEqual(self.retry(rid, "continue", again)["status"], "done")
        self.assertEqual((drafted(again), "outline" in again.tasks), (set(ALL), False))  # every concept, the same outline

    def test_C2_stopped_part_way_through_the_concepts_continues_with_the_rest(self):
        rid, stopped = self.stopped_mid_build()
        self.assertEqual((stopped["resume"]["kept"], stopped["resume"]["total"]), (2, 3))
        again = Model()
        self.assertEqual(self.retry(rid, "continue", again)["status"], "done")
        self.assertEqual(drafted(again), {"why_regression"})

    def test_C3_a_build_where_no_concept_passed_offers_the_choice_too(self):
        rid, record = self.outlined()
        self.approve(rid, record["outline"], BadConcepts())
        failed = self.settled(rid)
        self.assertEqual(failed["status"], "error")
        self.assertTrue(failed["error"].startswith("No concept passed the quality checks"))
        self.assertEqual(failed["resume"]["kept"], 0)
        self.assertEqual(self.retry(rid, "continue")["status"], "done")

    def test_C4_concepts_marked_known_dont_count_and_arent_built(self):
        def known(outline):
            outline["concepts"][0]["known"] = True
        rid, stopped = self.stopped_mid_build(finished=("regression_line",), edit=known)
        self.assertEqual((stopped["resume"]["kept"], stopped["resume"]["total"]), (1, 2))
        again = Model()
        self.assertEqual(self.retry(rid, "continue", again)["status"], "done")
        self.assertEqual(drafted(again), {"why_regression"})
        lesson, _ = store.load_lesson(rid, TESTER)
        self.assertEqual(len(lesson["intro"]["known"]), 1)

    def test_C5_an_outline_changed_after_approval_is_no_longer_continued(self):
        rid, _ = self.stopped_mid_build()
        record = store.load_request(rid, TESTER)
        record["outline"]["title"] += " (edited)"  # it no longer matches what was approved
        store.save_request(record, TESTER)
        self.assertIsNone(call(server.api_request, rid)["resume"])
        with self.assertRaises(server.ApiError) as e:
            self.retry(rid, "continue")
        self.assertEqual(e.exception.status, 409)
        self.assertEqual(self.retry(rid)["status"], "awaiting_outline")  # a new outline, as for any build without one
        self.assertFalse(store.BuiltConcepts(rid, TESTER).dir.exists())

    def test_C6_a_build_from_before_approval_was_recorded_gets_a_new_outline(self):
        rid, _ = self.stopped_mid_build()
        record = store.load_request(rid, TESTER)
        del record["approved"]
        store.save_request(record, TESTER)
        self.assertIsNone(call(server.api_request, rid)["resume"])
        self.assertEqual(self.retry(rid)["status"], "awaiting_outline")

    def test_C7_continuing_twice_with_three_models_keeps_everything_and_credits_all_three(self):
        A, B, C = named("Claude", "claude-opus-5-5"), named("OpenAI", "gpt-6.1-sol"), named("OpenCode", "gpt-5.6-luna")
        first = type("HangsA", (Hangs, A), {})(["regression_line", "why_regression"])
        rid, stopped = self.stopped_mid_build(finished=("mid_parent",), provider=first)
        self.assertEqual(stopped["resume"]["kept"], 1)
        second = type("HangsB", (Hangs, B), {})(["why_regression"])
        with patch.object(server.core, "_provider", return_value=second):
            call(server.api_request_retry, rid, body={"mode": "continue"})
        self.assertTrue(second.hanging.wait(10))
        for _ in range(500):
            if "regression_line" in store.BuiltConcepts(rid, TESTER).load():
                break
            time.sleep(.01)
        stopped = self.stop(rid, second.stopped.set)  # stopped again, while continuing
        self.assertEqual((stopped["resume"]["kept"], [m["name"] for m in stopped["resume"]["built_with"]]), (2, ["Claude", "OpenAI"]))
        third = C()
        self.assertEqual(self.retry(rid, "continue", third)["status"], "done")
        self.assertEqual(drafted(third), {"why_regression"})
        lesson, _ = store.load_lesson(rid, TESTER)
        self.assertEqual([(m["name"], m["concepts"]) for m in lesson["made_with"]],
                         [("Claude", ["mid_parent"]), ("OpenAI", ["regression_line"]), ("OpenCode", ["why_regression"])])

    def test_C8_started_over_then_stopped_while_proposing_the_new_outline(self):
        rid, _ = self.stopped_mid_build()
        hangs = Hangs("outline")
        with patch.object(server.core, "_provider", return_value=hangs):
            call(server.api_request_retry, rid, body={"mode": "start_over"})
        self.assertTrue(hangs.hanging.wait(10))
        stopped = self.stop(rid, hangs.stopped.set)
        self.assertIsNone(stopped["resume"])  # the approved outline is gone: nothing to continue
        self.assertFalse(store.BuiltConcepts(rid, TESTER).dir.exists())
        self.assertEqual(self.retry(rid)["status"], "awaiting_outline")

    def test_C9_started_over_then_stopped_again_continues_only_the_new_attempts_concepts(self):
        rid, _ = self.stopped_mid_build()
        review = self.retry(rid, "start_over")
        self.assertEqual(review["status"], "awaiting_outline")
        hangs = Hangs(["regression_line", "why_regression"])
        self.approve(rid, review["outline"], hangs)
        self.assertTrue(hangs.hanging.wait(10))
        for _ in range(500):
            if "mid_parent" in store.BuiltConcepts(rid, TESTER).load():
                break
            time.sleep(.01)
        stopped = self.stop(rid, hangs.stopped.set)
        self.assertEqual(stopped["resume"]["kept"], 1)  # only what this attempt finished
        again = Model()
        self.assertEqual(self.retry(rid, "continue", again)["status"], "done")
        self.assertEqual(drafted(again), {"regression_line", "why_regression"})

    def saved_then_stopped(self, cleared):
        """A build stopped by a restart just after its lesson was saved, before it was marked done: before its saved
        concepts were cleared, or (`cleared`) just after. Returns the build as the server reads it next."""
        rid, record = self.outlined()

        def on_disk():  # what the restart left, before the server reads the build again
            self.assertEqual(store.load_lesson(rid, TESTER)[0]["id"], rid)
            self.assertEqual(store.BuiltConcepts(rid, TESTER).dir.exists(), not cleared)
            self.assertEqual(store.load_request(rid, TESTER)["status"], "running")
        with self.paused(store.BuiltConcepts, "clear", after=cleared) as (reached, release):
            self.approve(rid, record["outline"])
            self.assertTrue(reached.wait(10))
            job = generate.JOBS.pop(rid)  # the server stops; the build holds the lock where it was stopped
            job.cancelled.set()
            release()
            wait(job)
        on_disk()
        record = call(server.api_request, rid)  # the restarted server reads it
        self.assertEqual(record["status"], "done")
        return record

    def assert_finished(self, record):
        rid = record["id"]
        self.assertEqual((record["error"], record["resume"], record["result"]["id"]), ("", None, rid))
        self.assertEqual({s["id"]: (s["state"], s["detail"]) for s in record["steps"]}["save"], ("done", "Saved to your library"))
        self.assertFalse(store.BuiltConcepts(rid, TESTER).dir.exists())
        self.assertEqual(store.load_request(rid, TESTER)["status"], "done")  # settled once, on disk
        self.assertEqual([r["status"] for r in call(server.api_requests) if r["id"] == rid], ["done"])  # not "In progress"
        with self.assertRaises(server.ApiError) as e:
            self.retry(rid, "continue")
        self.assertEqual(e.exception.status, 409)

    def test_C10a_stopped_just_after_the_lesson_was_saved_shows_as_done(self):
        self.assert_finished(self.saved_then_stopped(cleared=False))

    def test_C10b_stopped_after_the_lesson_was_saved_and_its_concepts_cleared_shows_as_done(self):
        self.assert_finished(self.saved_then_stopped(cleared=True))  # rather than offer to pay to build it all again

    # ------------------------------------------------------------ D. the retry request itself

    def test_D1_a_second_retry_while_the_first_runs_is_refused(self):
        rid, _ = self.stopped_mid_build()
        hangs = Hangs(["why_regression"])
        with patch.object(server.core, "_provider", return_value=hangs):
            call(server.api_request_retry, rid, body={"mode": "continue"})
            self.assertTrue(hangs.hanging.wait(10))
            with self.assertRaises(server.ApiError) as e:
                call(server.api_request_retry, rid, body={"mode": "continue"})  # a double click
        self.assertEqual((e.exception.status, e.exception.message), (409, "Only a stopped build can be retried."))
        hangs.stopped.set()

    def test_D2_a_finished_build_cant_be_retried(self):
        rid, record = self.outlined()
        self.approve(rid, record["outline"])
        self.assertEqual(self.settled(rid)["status"], "done")
        with self.assertRaises(server.ApiError) as e:
            self.retry(rid, "continue")
        self.assertEqual(e.exception.status, 409)

    def test_D3_start_over_is_accepted_where_there_is_no_choice(self):
        rid, _ = self.outlined()
        call(server.api_request_cancel, rid)
        self.assertEqual(self.retry(rid, "start_over")["status"], "awaiting_outline")


if __name__ == "__main__":
    unittest.main()
