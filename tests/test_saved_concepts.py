"""Concepts a build finished and checked are saved under LEMMA_HOME, so a build the server stopped carries on from them.

A saved concept is reused only by a build of the same outline version from the same sources; otherwise it is built again.
"""
import copy
import json
import os
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import fakejev  # noqa: F401  Jev is essential, so every search and build asks this stand-in
from lemma import factcheck, generate, jev, server, store
from lemma import lesson as L
from lemma.llm import ProviderError
from test_lemma import EXAMPLE, SOURCE, TESTER, FakeProvider, reset_server, sign_in, wait
from test_multisource import MultiSourceProvider

PAPER = {"text": SOURCE, "title": "Galton", "url": ""}


def settle_threads():
    """A build's thread writes its last metric just after its status settles: let it finish before the home is removed."""
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.name.endswith("(run)"):
            t.join(10)


def drafted(provider) -> set:
    """The concepts a provider was asked to draft."""
    return {k for k in getattr(provider, "tasks", {}) if k != "outline"}


class SavedConceptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = patch.dict(os.environ, {"LEMMA_HOME": self.tmp.name})
        self.env.start()
        self.saved = store.BuiltConcepts("build1")
        self.outline = wait(generate.start(generate.Job("outline"), generate.make_outline, FakeProvider(), SOURCE, "")).result

    def tearDown(self):
        settle_threads()
        self.env.stop()
        self.tmp.cleanup()

    def build(self, provider=None, outline=None, paper=PAPER):
        provider = provider or FakeProvider()
        job = wait(generate.start(generate.Job("build"), generate.build_lesson, provider, paper,
                                  copy.deepcopy(outline or self.outline), "beginner", "build1", self.saved))
        self.assertEqual(job.status, "done", job.error)
        return job, provider

    def test_each_checked_concept_is_saved_privately_and_reused_by_the_same_build(self):
        first, _ = self.build()
        ids = [c["id"] for c in first.result["concepts"]]
        self.assertEqual(sorted(self.saved.load()), sorted(ids))
        for path in self.saved.dir.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.saved.dir.stat().st_mode & 0o777, 0o700)
        again, provider = self.build()
        self.assertEqual(drafted(provider), set())  # nothing paid for twice
        self.assertEqual(provider.calls, 0)
        self.assertEqual(again.result["concepts"], first.result["concepts"])
        steps = {s["id"]: s for s in again.snapshot()["steps"]}
        self.assertTrue(all(steps[i]["state"] == "done" and "kept from the earlier attempt" in steps[i]["detail"] for i in ids))
        self.assertIsNone(again.snapshot()["eta_seconds"])  # kept concepts don't pretend to have taken no time

    def test_only_the_concepts_still_missing_are_built(self):
        self.build()
        self.saved.discard("why_regression")  # as if the server stopped while it was being drafted
        job, provider = self.build()
        self.assertEqual(drafted(provider), {"why_regression"})
        self.assertEqual([c["id"] for c in job.result["concepts"]], [c["id"] for c in self.outline["concepts"]])
        self.assertIn("why_regression", self.saved.load())

    def test_a_concept_left_out_is_not_saved_and_is_tried_again(self):
        class Stubborn(FakeProvider):
            def reply(self, task, turn):
                return super().reply(task, 1)  # repeats regression_line's bad first draft

        first, _ = self.build(Stubborn())
        self.assertEqual([o["title"] for o in first.result["omitted"]], [EXAMPLE["concepts"][1]["title"]])
        self.assertNotIn("regression_line", self.saved.load())
        job, provider = self.build()
        self.assertEqual(drafted(provider), {"regression_line"})
        self.assertEqual(job.result["omitted"], [])

    def test_another_outline_version_rebuilds_everything_and_drops_what_was_saved(self):
        self.build()
        old = self.saved.load()
        edited = copy.deepcopy(self.outline)
        edited["concepts"][2]["idea"] += " Seen again in the next generation."
        job, provider = self.build(outline=edited)
        self.assertEqual(drafted(provider), {c["id"] for c in self.outline["concepts"]})
        new = self.saved.load()
        self.assertEqual(sorted(new), sorted(old))
        self.assertTrue(all(new[i]["outline"] != old[i]["outline"] for i in new))  # the old version's files were replaced
        self.assertTrue(all(e["outline"] == generate.fingerprint(edited) for e in new.values()))

    def test_other_sources_rebuild_everything(self):
        self.build()
        job, provider = self.build(paper=dict(PAPER, text=SOURCE + "\n\nA note added to the source."))
        self.assertEqual(drafted(provider), {c["id"] for c in self.outline["concepts"]})

    def test_the_outline_version_doesnt_depend_on_key_order(self):
        reordered = json.loads(json.dumps(self.outline, sort_keys=True))
        self.assertEqual(generate.fingerprint(reordered), generate.fingerprint(self.outline))
        self.build()
        _, provider = self.build(outline=reordered)
        self.assertEqual(drafted(provider), set())

    def test_a_saved_concept_that_no_longer_passes_the_rules_is_built_again(self):
        self.build()
        entry = self.saved.load()["mid_parent"]
        entry["concept"]["understand"]["quote"] = "Height is decided entirely by the father."  # not in the source
        self.saved.save("mid_parent", entry)
        (self.saved.dir / "regression_line.json").write_text("{ cut off mid-wri")
        job, provider = self.build()
        self.assertEqual(drafted(provider), {"mid_parent", "regression_line"})
        self.assertNotEqual(job.result["concepts"][0]["understand"]["quote"], entry["concept"]["understand"]["quote"])

    def test_a_concept_on_another_concepts_model_is_kept_only_with_that_very_model(self):
        outline = copy.deepcopy(self.outline)
        outline["concepts"].insert(1, {"id": "mid_parent_more", "title": "More about the mid-parent", "idea": "x", "visual": "bars", "builds_on": "mid_parent"})
        self.build(outline=outline)
        saved = self.saved.load()
        self.assertEqual(saved["mid_parent_more"]["base"], generate.fingerprint(saved["mid_parent"]["concept"]))
        _, provider = self.build(outline=outline)
        self.assertEqual(drafted(provider), set())  # its base was kept, so it is too
        self.saved.discard("mid_parent")
        job, provider = self.build(outline=outline)
        self.assertEqual(drafted(provider), {"mid_parent", "mid_parent_more"})  # a new base means a new model to build on
        self.assertIn('"father"', provider.tasks["mid_parent_more"])
        more = next(c for c in job.result["concepts"] if c["id"] == "mid_parent_more")
        self.assertEqual(more["builds_on"], "mid_parent")

    def test_plans_are_chosen_only_for_concepts_still_to_build_and_kept_ones_keep_theirs(self):
        first, _ = self.build()
        self.saved.discard("why_regression")
        asked = []

        def ask(state, questions, timeout):
            asked.append(sorted(questions))
            return fakejev.answer(state, questions, timeout)
        with patch.object(jev, "ask", side_effect=ask):
            job, _ = self.build()
        self.assertIn(["why_regression"], asked)  # the only concept Jev chose a plan for
        self.assertEqual(job.result["activity_plans"], first.result["activity_plans"])

    def test_a_flag_jev_couldnt_resolve_is_kept_with_its_concept(self):
        with patch.object(factcheck, "check_concept", side_effect=lambda c, *a, **k: [
                factcheck.Flag("concept: " + factcheck.REPAIR["fabricated_finding"], "fabricated_finding", .9)] if c["id"] == "mid_parent" else []):
            first, _ = self.build()
        self.assertEqual([f["concept"] for f in first.result["flags"]], ["mid_parent"])
        job, provider = self.build()
        self.assertEqual(drafted(provider), set())
        self.assertEqual(job.result["flags"], first.result["flags"])
        step = next(s for s in job.snapshot()["steps"] if s["id"] == "mid_parent")
        self.assertIn("flagged 1 possible problem", step["detail"])

    def test_every_model_that_built_a_concept_is_credited_in_order(self):
        class A(FakeProvider): id, name, model = "a", "Claude", "claude-opus-5-5"
        class B(FakeProvider): id, name, model = "b", "OpenAI", "gpt-6.1-sol"
        class C(FakeProvider): id, name, model = "c", "OpenCode Go", "gpt-5.6-luna"
        self.build(A())
        self.saved.discard("regression_line"), self.saved.discard("why_regression")
        self.build(B())
        self.saved.discard("why_regression")
        job, _ = self.build(C())
        self.assertEqual(job.result["made_with"], [{"name": "Claude", "model": "claude-opus-5-5", "concepts": ["mid_parent"]},
                                                   {"name": "OpenAI", "model": "gpt-6.1-sol", "concepts": ["regression_line"]},
                                                   {"name": "OpenCode Go", "model": "gpt-5.6-luna", "concepts": ["why_regression"]}])
        self.assertEqual(job.result["provider"], {"name": "Claude", "model": "claude-opus-5-5"})  # a tie: the earliest concept's

    def test_a_lesson_kept_whole_is_credited_to_the_model_that_built_it(self):
        class A(FakeProvider): id, name, model = "a", "Claude", "claude-opus-5-5"
        class B(FakeProvider): id, name, model = "b", "OpenAI", "gpt-6.1-sol"
        self.build(A())
        job, provider = self.build(B())
        self.assertEqual(provider.calls, 0)
        self.assertEqual(job.result["provider"], {"name": "Claude", "model": "claude-opus-5-5"})
        self.assertEqual([m["name"] for m in job.result["made_with"]], ["Claude"])

    def test_a_concept_saved_without_its_model_is_built_again(self):
        self.build()
        for cid, entry in self.saved.load().items():  # as an earlier format saved them
            entry.pop("made_with")
            self.saved.save(cid, entry)
        _, provider = self.build()
        self.assertEqual(drafted(provider), {c["id"] for c in self.outline["concepts"]})

    def test_what_continuing_would_keep_is_counted_without_building(self):
        self.build()
        self.saved.discard("why_regression")
        summary = generate.saved_summary(self.saved.load(), self.outline, SOURCE, "beginner")
        self.assertEqual(summary, {"kept": 2, "total": 3, "built_with": [{"name": "Fake", "model": "fake-1", "concepts": 2}]})
        self.assertEqual(generate.saved_summary(self.saved.load(), self.outline, SOURCE + " ", "beginner")["kept"], 0)  # other sources

    def test_a_build_without_a_store_saves_nothing(self):
        job = wait(generate.start(generate.Job("build"), generate.build_lesson, FakeProvider(), PAPER, self.outline, "beginner"))
        self.assertEqual(job.status, "done", job.error)
        self.assertFalse(self.saved.dir.exists())

    def test_a_concept_that_cant_be_saved_is_still_in_the_lesson(self):
        with patch.object(store.BuiltConcepts, "save", side_effect=OSError("disk full")), patch("sys.stderr"):
            job, _ = self.build()
        self.assertEqual(len(job.result["concepts"]), 3)


class ErrorPathTests(unittest.TestCase):
    """What happens when saved concepts can't be read, written or trusted: the build goes on, building them again."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = patch.dict(os.environ, {"LEMMA_HOME": self.tmp.name})
        self.env.start()
        self.outline = wait(generate.start(generate.Job("outline"), generate.make_outline, FakeProvider(), SOURCE, "")).result

    def tearDown(self):
        settle_threads()
        self.env.stop()
        self.tmp.cleanup()

    def build(self, saved, provider=None):
        provider = provider or FakeProvider()
        job = wait(generate.start(generate.Job("build"), generate.build_lesson, provider, PAPER, copy.deepcopy(self.outline), "beginner", "build1", saved))
        self.assertEqual(job.status, "done", job.error)
        return job, provider

    def test_a_folder_that_cant_be_read_means_building_everything(self):
        class Unreadable(store.BuiltConcepts):
            def load(self):
                raise PermissionError("no access")
        saved = Unreadable("build1")
        job, provider = self.build(saved)
        self.assertEqual(drafted(provider), {c["id"] for c in self.outline["concepts"]})
        self.assertEqual(sorted(p.stem for p in saved.dir.glob("*.json")), sorted(c["id"] for c in self.outline["concepts"]))  # still saved

    def test_a_stale_concept_that_cant_be_deleted_is_only_ignored(self):
        saved = store.BuiltConcepts("build1")
        self.build(saved)
        stale = saved.load()
        for entry in stale.values():
            entry["outline"] = "another version"
            saved.save(entry["concept"]["id"], entry)
        with patch.object(store.BuiltConcepts, "discard", side_effect=PermissionError("read-only")):
            job, provider = self.build(saved)
        self.assertEqual(drafted(provider), {c["id"] for c in self.outline["concepts"]})  # none fits, and the build goes on

    def test_a_saved_file_the_rules_trip_over_is_built_again(self):
        saved = store.BuiltConcepts("build1")
        self.build(saved)
        todo = [c for c in self.outline["concepts"] if not c.get("known")]
        version = generate.build_version(self.outline, SOURCE, "beginner")

        def rules(c, obj, base):
            if c["id"] == "mid_parent":
                raise RecursionError("a pathological saved file")
            return []
        with patch("sys.stderr") as err:
            kept = generate._fitting(saved.load(), version, todo, rules)
        self.assertEqual(sorted(kept), ["regression_line", "why_regression"])
        self.assertIn("saved concept mid_parent: RecursionError", "".join(str(c.args[0]) for c in err.write.call_args_list))

    def test_a_draft_that_isnt_an_object_is_reported_not_crashed_on(self):
        c = self.outline["concepts"][0]
        problems = generate._concept_rules(c, ["not", "an", "object"], None, L.normalize_for_match(SOURCE), {})
        self.assertTrue(problems)

    def test_saved_files_are_only_ever_named_by_concept_ids(self):
        saved = store.BuiltConcepts("build1")
        for bad in ("../escape", "", "a/b", None):
            with self.assertRaises(KeyError):
                saved.save(bad, {})
            saved.discard(bad)  # nothing to delete, and nothing outside the folder is touched
        self.assertFalse(saved.dir.exists())

    def test_a_saved_file_that_isnt_an_object_is_skipped(self):
        saved = store.BuiltConcepts("build1")
        saved.save("mid_parent", {"concept": {}})
        (saved.dir / "regression_line.json").write_text("[1, 2, 3]")
        self.assertEqual(list(saved.load()), ["mid_parent"])

    def test_a_build_whose_saved_concepts_cant_be_read_offers_the_choice_with_none_kept(self):
        sign_in()
        self.addCleanup(reset_server)
        record = {"id": "abcdefabcdef", "status": "interrupted", "outline": self.outline, "approved": generate.fingerprint(self.outline),
                  "paper": {"text": SOURCE}, "request": {"level": "beginner"}, "steps": [], "created": 0}
        store.save_request(record, TESTER)
        with patch.object(store.BuiltConcepts, "load", side_effect=PermissionError("no access")):
            self.assertEqual(server.api_request("abcdefabcdef")["resume"], {"kept": 0, "total": 3, "built_with": [], "excluded": []})


class Stops(MultiSourceProvider):
    """Finishes every concept but one, which hangs until the server stops and drops the connection."""

    def __init__(self, hang_on):
        super().__init__()
        self.hang_on, self.hanging, self.stopped = hang_on, threading.Event(), threading.Event()

    def reply(self, task, turn):
        if f'Its id must be "{self.hang_on}"' in task:
            self.hanging.set()
            self.stopped.wait(10)
            raise ProviderError("The connection closed.")
        return super().reply(task, turn)


class Other(MultiSourceProvider):
    """Another AI provider and model, as when the learner switched models between attempts."""

    id, name, model = "other", "Other", "other-2"


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.env = patch.dict(os.environ, {"LEMMA_HOME": self.tmp.name})
        self.env.start()
        sign_in()
        self.read = patch.object(server, "_first_readable", return_value=SimpleNamespace(title="Galton", url="https://example.org/paper", text=SOURCE))
        self.read.start()

    def tearDown(self):
        self.read.stop()
        server.REQUEST.body = {}
        reset_server()
        settle_threads()
        self.env.stop()
        self.tmp.cleanup()

    def settled(self, rid):
        for _ in range(1000):  # up to 10 s
            record = server.api_request(rid)
            if record["status"] != "running":
                return record
            time.sleep(.01)
        self.fail("request did not settle")

    def retry(self, rid, mode=None, provider=None):
        server.REQUEST.body = {"mode": mode} if mode else {}
        with patch.object(server, "_provider", return_value=provider or MultiSourceProvider()):
            return server.api_request_retry(rid)

    def outlined(self):
        with patch.object(server, "_provider", return_value=MultiSourceProvider()):
            rid = server.api_request_create({"sources": [{"url": "https://example.org/paper", "title": "Paper"}], "topic": "Regression"})["id"]
            record = self.settled(rid)
        self.assertEqual(record["status"], "awaiting_outline", record.get("error"))
        return rid, record["outline"]

    def stop_mid_build(self, rid, outline, hang_on="why_regression", cancel=False):
        """Approve the outline and build until every concept but `hang_on` is done, then stop the server (or, with
        `cancel`, cancel the build as the learner would)."""
        provider = Stops(hang_on)
        with patch.object(server, "_provider", return_value=provider):
            server.REQUEST.body = {"outline": outline}
            server.api_request_outline(rid)
        job = generate.JOBS[rid]
        self.assertTrue(provider.hanging.wait(10))
        for _ in range(1000):
            states = {s["id"]: s["state"] for s in store.load_request(rid, TESTER)["steps"]}
            if sum(states.get(c["id"]) == "done" for c in outline["concepts"]) == len(outline["concepts"]) - 1:
                break
            time.sleep(.01)
        if cancel:
            server.api_request_cancel(rid)
        else:  # the server stops: its memory is gone, and its threads never write again
            generate.JOBS.pop(rid)
            job.cancelled.set()
        provider.stopped.set()
        wait(job)
        return {c["id"] for c in outline["concepts"]} - {hang_on}

    def test_a_stopped_build_offers_the_choice_and_continuing_reuses_the_finished_concepts(self):
        rid, outline = self.outlined()
        finished = self.stop_mid_build(rid, outline)
        self.assertEqual(set(store.BuiltConcepts(rid, TESTER).load()), finished)
        stopped = server.api_request(rid)
        self.assertEqual((stopped["status"], stopped["error"]), ("interrupted", "The server stopped during this build."))
        self.assertEqual(stopped["resume"], {"kept": 2, "total": 3, "built_with": [{"name": "Fake", "model": "fake-1", "concepts": 2}], "excluded": []})
        self.assertEqual(server.api_requests({})[0]["resume"], stopped["resume"])  # the Library says the same
        self.assertNotIn("approved", stopped)
        step = next(s for s in stopped["steps"] if s["id"] == "why_regression")
        self.assertEqual((step["state"], step["detail"]), ("stopped", "Not built: the server stopped"))  # no longer looks active
        for mode in (None, "resume"):
            with self.assertRaises(server.ApiError) as e:  # the learner chooses; the server never guesses
                self.retry(rid, mode)
            self.assertEqual((e.exception.status, e.exception.message), (400, server.CHOOSE))
        again = MultiSourceProvider()
        self.retry(rid, "continue", again)
        done = self.settled(rid)
        self.assertEqual(done["status"], "done", done.get("error"))
        self.assertEqual(drafted(again), {"why_regression"})  # the outline isn't remade, and finished concepts aren't rebuilt
        self.assertNotIn("outline", again.tasks)
        lesson, _ = store.load_lesson(rid, TESTER)
        self.assertEqual([c["id"] for c in lesson["concepts"]], [c["id"] for c in outline["concepts"]])
        self.assertEqual(lesson["made_with"], [{"name": "Fake", "model": "fake-1", "concepts": [c["id"] for c in outline["concepts"]]}])
        self.assertEqual({s["id"] for s in done["steps"] if "kept from the earlier attempt" in s["detail"]}, finished)
        self.assertIsNone(done["resume"])
        self.assertFalse(store.BuiltConcepts(rid, TESTER).dir.exists())  # the saved lesson holds them now

    def test_continuing_with_another_model_credits_both(self):
        rid, outline = self.outlined()
        self.stop_mid_build(rid, outline)
        self.retry(rid, "continue", Other())
        self.assertEqual(self.settled(rid)["status"], "done")
        lesson, _ = store.load_lesson(rid, TESTER)
        self.assertEqual(lesson["made_with"], [{"name": "Fake", "model": "fake-1", "concepts": ["mid_parent", "regression_line"]},
                                               {"name": "Other", "model": "other-2", "concepts": ["why_regression"]}])
        self.assertEqual(lesson["provider"], {"name": "Fake", "model": "fake-1"})  # the model that built the most of it

    def test_starting_over_deletes_the_finished_concepts_even_for_the_same_outline(self):
        rid, outline = self.outlined()
        self.stop_mid_build(rid, outline)
        again = MultiSourceProvider()
        self.retry(rid, "start_over", again)
        self.assertFalse(store.BuiltConcepts(rid, TESTER).dir.exists())
        review = self.settled(rid)
        self.assertEqual(review["status"], "awaiting_outline")
        self.assertIn("outline", again.tasks)  # a new outline, from the sources already read
        self.assertEqual(generate.fingerprint(review["outline"]), generate.fingerprint(outline))  # which happens to be the same
        with patch.object(server, "_provider", return_value=again):
            server.REQUEST.body = {"outline": review["outline"]}
            server.api_request_outline(rid)
            self.assertEqual(self.settled(rid)["status"], "done")
        self.assertEqual(drafted(again), {c["id"] for c in outline["concepts"]})  # nothing reused: the learner started over

    def test_errored_and_cancelled_builds_offer_the_choice_too(self):
        rid, outline = self.outlined()
        self.stop_mid_build(rid, outline, cancel=True)
        cancelled = server.api_request(rid)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["resume"]["kept"], 2)
        step = next(s for s in cancelled["steps"] if s["id"] == "why_regression")
        self.assertEqual((step["state"], step["detail"]), ("stopped", "Not built: you cancelled the build"))
        self.assertEqual(cancelled["lesson"]["omitted"], [])  # cancelled, not left out for failing the checks
        with server._requests_lock:  # the job's thread saves once more after it settles: it mustn't land after this edit
            generate.JOBS.pop(rid, None)
        record = store.load_request(rid, TESTER)
        record.update(status="error", error="Something went wrong.")
        store.save_request(record, TESTER)
        self.assertEqual(server.api_request(rid)["resume"]["kept"], 2)
        again = MultiSourceProvider()
        self.retry(rid, "continue", again)
        self.assertEqual(self.settled(rid)["status"], "done")
        self.assertEqual(drafted(again), {"why_regression"})

    def test_a_retry_that_cant_start_deletes_nothing(self):
        rid, outline = self.outlined()
        finished = self.stop_mid_build(rid, outline)
        server.REQUEST.body = {"mode": "start_over"}
        with patch.object(server, "_provider", side_effect=server.ApiError(400, "Connect an AI provider.")), self.assertRaises(server.ApiError):
            server.api_request_retry(rid)
        with patch.object(server, "_provider", return_value=MultiSourceProvider()), \
                patch.object(server, "_new_job", side_effect=server.ApiError(429, "You already have lessons building.")), self.assertRaises(server.ApiError):
            server.api_request_retry(rid)
        self.assertEqual(set(store.BuiltConcepts(rid, TESTER).load()), finished)
        self.assertEqual(server.api_request(rid)["resume"]["kept"], 2)  # the choice is still there

    def test_a_build_stopped_before_its_outline_was_approved_gets_a_new_outline_without_a_choice(self):
        rid, outline = self.outlined()
        record = store.load_request(rid, TESTER)
        record["status"] = "running"  # stopped while the outline was being made
        store.save_request(record, TESTER)
        generate.JOBS.pop(rid)
        stopped = server.api_request(rid)
        self.assertEqual(stopped["status"], "interrupted")
        self.assertIn("start a new attempt", stopped["error"])
        self.assertIsNone(stopped["resume"])
        with self.assertRaises(server.ApiError) as e:
            self.retry(rid, "continue")
        self.assertEqual(e.exception.status, 409)
        again = MultiSourceProvider()
        self.retry(rid, provider=again)  # no choice to make: a retry needs no mode, as before
        self.assertEqual(self.settled(rid)["status"], "awaiting_outline")
        self.assertIn("outline", again.tasks)

    def test_deleting_a_stopped_build_deletes_its_saved_concepts(self):
        rid, outline = self.outlined()
        self.stop_mid_build(rid, outline)
        self.assertEqual(server.api_request(rid)["status"], "interrupted")
        self.assertTrue(store.BuiltConcepts(rid, TESTER).dir.exists())
        server.api_request_delete(rid)
        self.assertFalse(store.BuiltConcepts(rid, TESTER).dir.exists())
        self.assertEqual(server.api_requests({}), [])  # and nothing saved is mistaken for a build


if __name__ == "__main__":
    unittest.main()
