"""Build lessons from eval/papers.json, judge them with TypeSafe's Jev, and summarise the results.

    uv run python eval/run.py build   --run R --builder claude:claude-opus-5-5
    uv run python eval/run.py judge   --run R
    uv run python eval/run.py plant   --run R --into R-planted
    uv run python eval/run.py summary --run R

Building uses an AI model, with its key from the environment: LEMMA_EVAL_KEY_CLAUDE, LEMMA_EVAL_KEY_OPENAI or
LEMMA_EVAL_KEY_OPENCODE_GO. Judging uses Jev with TYPESAFE_API_KEY, and asks the questions in questions.py
(see jev_judge.py for what Jev is shown). `plant` copies a run's lessons with one deliberate critical error
each, so judging that run measures what the eval catches. `--papers 1-5,9` picks papers. Each step skips work
it has already saved, so an interrupted run carries on where it stopped; `--redo` does it again.

Everything is written under eval/results/<run>/: run.json (who built and judged, and Lemma's commit) and,
for each lesson, papers/<id>/ with source.txt, outline.json, lesson.json, build.json and judge-jev.json.
Judging and summary work on any run folder with lesson.json and source.txt, built here or not. `summary`
writes summary.json and summary.md.

The lessons are built exactly as a learner's would be, from the outline the model proposes with no
review, so "passed without edits" means no concept was left out.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lemma import generate, ingest, jev, lesson as L  # noqa: E402
from lemma.llm import PROVIDERS, ProviderError, make_provider  # noqa: E402

import jev_judge  # noqa: E402
import plant as plant_mod  # noqa: E402
import questions as Q  # noqa: E402

EVAL = Path(__file__).resolve().parent
PAPERS = json.loads((EVAL / "papers.json").read_text())
AUDIENCE = "A curious adult with no background in this field"
PLANT_KINDS = plant_mod.KINDS


# ---------------------------------------------------------------- helpers


def provider_for(spec: str):
    """`claude:claude-opus-5-5` -> a provider using LEMMA_EVAL_KEY_CLAUDE."""
    pid, _, model = spec.partition(":")
    if pid not in PROVIDERS:
        sys.exit(f"Unknown provider {pid!r}. Choose from: {', '.join(PROVIDERS)}")
    env = "LEMMA_EVAL_KEY_" + pid.upper().replace("-", "_")
    key = os.environ.get(env, "")
    if not key and pid != "chatgpt":
        sys.exit(f"Set {env} to use {pid}.")
    return make_provider(pid, key, model)


def pick(spec: str | None) -> list[dict]:
    if not spec:
        return PAPERS
    ids: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        ids.update(range(int(a), int(b or a) + 1))
    return [p for p in PAPERS if p["id"] in ids]


def folder(run: str, paper: dict) -> Path:
    d = EVAL / "results" / run / "papers" / f"{paper['id']:02d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def load(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def say(paper: dict, msg: str):
    print(f"{time.strftime('%H:%M:%S')}  {paper['id']:>2}. {paper['title'][:50]:<50}  {msg}", flush=True)


def record_run(run: str, **fields):
    path = EVAL / "results" / run / "run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    info = load(path) or {}
    try:
        info["lemma_commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        pass
    info.update(fields)
    save(path, info)


# A provider error counts against the lesson only when it is about the paper: too long for the model, or declined.
# Anything else (limits, billing, keys, outages) is the run's problem, so that work is retried on the next run.
LESSON_FAULTS = ("too long for", "declined")
# These mean the account can't be used at all, so the run stops rather than meeting the same error on every paper.
ACCOUNT_FAULTS = ("credit balance", "rejected the key", "can't use", "doesn't offer", "Sign in", "sign-in")
STOP = threading.Event()


def lesson_fault(message: str) -> bool:
    return any(f in message for f in LESSON_FAULTS)


def note_account_fault(message: str):
    if any(f in message for f in ACCOUNT_FAULTS) and not STOP.is_set():
        STOP.set()
        print(f"\nStopping: the provider account can't be used ({message[:200]}). Fix it and run the same command again.\n", flush=True)


class Watched:
    """A provider that notes every error it raises, including the ones a build turns into a left-out concept."""

    def __init__(self, provider):
        self.provider, self.errors = provider, []

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def conversation(self, system, document):
        conv = self.provider.conversation(system, document)
        send = conv.send

        def watched(*args, **kwargs):
            try:
                return send(*args, **kwargs)
            except ProviderError as e:
                self.errors.append(str(e))
                note_account_fault(str(e))
                raise

        conv.send = watched
        return conv


class RecordingJob(generate.Job):
    """A build job that keeps every problem the checks found, so a run shows why drafts needed fixing."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.problem_log: dict[str, list[list[str]]] = {}

    def update(self, sid, state, detail="", quiet=False, **extra):
        found = extra.get("problems")
        log = self.problem_log.setdefault(sid, [])
        if found and not quiet and (not log or log[-1] != found):
            log.append(list(found))
        super().update(sid, state, detail, quiet, **extra)


def each(papers, fn, parallel: int):
    def unless_stopped(paper):
        if not STOP.is_set():
            fn(paper)

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        list(pool.map(unless_stopped, papers))


# ---------------------------------------------------------------- build


def build(args):
    provider = provider_for(args.builder)
    record_run(args.run, builder={"provider": provider.id, "model": provider.model}, audience=AUDIENCE, built=time.strftime("%Y-%m-%dT%H:%M:%S"))

    def one(paper):
        d = folder(args.run, paper)
        done = load(d / "build.json")
        if done and done["status"] in ("done", "failed") and not args.redo:
            return say(paper, f"already built ({done['status']})")
        started = time.time()
        watched = Watched(provider)
        record = {"paper_id": paper["id"], "status": "failed", "stage": "read", "error": "", "builder": {"provider": provider.id, "model": provider.model}}
        job = RecordingJob("eval")
        try:
            say(paper, "reading")
            source = d / "source.txt"
            if not source.exists() or args.redo:
                source.write_text(ingest.first_readable(paper["urls"], budget=120).text)
            text = source.read_text()
            record["stage"] = "outline"
            say(paper, "outlining")
            outline = generate.make_outline(job, watched, text, AUDIENCE)
            save(d / "outline.json", outline)
            record["stage"] = "concepts"
            say(paper, f"building {len(outline['concepts'])} concepts")
            built = generate.build_lesson(job, watched, {"text": text, "title": paper["title"], "url": paper["urls"][0]}, outline, AUDIENCE, f"eval-{paper['id']:02d}")
            save(d / "lesson.json", built)
            record.update(status="done", stage="done")
        except (ingest.IngestError, generate.GenerationError, ProviderError) as e:
            record["error"] = str(e)
        lesson = job.lesson or {}
        if any(not lesson_fault(e) for e in watched.errors):
            record["status"] = "interrupted"
            record["provider_errors"] = watched.errors
        repairs = getattr(job, "repairs", {})
        record.update(
            seconds=round(time.time() - started),
            outline_repairs=repairs.get("outline"),
            concepts=[{"id": c["id"], "title": c["title"], "repairs": repairs.get(c["id"])} for c in lesson.get("concepts", [])],
            omitted=lesson.get("omitted", []),
            passed_without_edits=record["status"] == "done" and not lesson.get("omitted"),
            problems_fixed={sid: rounds for sid, rounds in job.problem_log.items() if rounds},  # each round's problems, in order
            steps=[{k: s.get(k) for k in ("id", "label", "state", "detail")} for s in job.steps],
        )
        save(d / "build.json", record)
        say(paper, record["status"] + (f": {record['error'][:100]}" if record["error"] else f", {len(record['concepts'])} concepts, {len(record['omitted'])} left out"))

    each(pick(args.papers), one, args.parallel)


# ---------------------------------------------------------------- judge (Jev)


def units(run: str, spec: str | None) -> list[tuple[Path, dict]]:
    """Every lesson folder in a run, with its paper's details: papers/01, or a planted copy such as papers/01-wrong_answer."""
    base = Path(run) if Path(run, "papers").is_dir() else EVAL / "results" / run
    ids = {p["id"] for p in pick(spec)} if spec else None
    out = []
    for d in sorted((base / "papers").glob("*")):
        num = re.match(r"\d+", d.name)
        pid = int(num.group()) if num else None
        if (d / "lesson.json").exists() and (ids is None or pid in ids):
            out.append((d, next((p for p in PAPERS if p["id"] == pid), {"id": pid or 0, "title": d.name, "field": ""})))
    return out


def judge(args):
    if not jev.available():
        sys.exit("Set TYPESAFE_API_KEY to judge with Jev.")
    record_run(args.run, judge={"with": "jev", "model": jev.MODEL, "questions": Q.VERSION}, judged=time.strftime("%Y-%m-%dT%H:%M:%S"))

    def one(unit):
        d, paper = unit
        out = d / "judge-jev.json"
        if out.exists() and not args.redo:
            return say(paper, f"{d.name}: already judged")
        if STOP.is_set():
            return
        say(paper, f"{d.name}: judging with Jev")
        started, lesson = time.time(), load(d / "lesson.json")
        try:
            judged = jev_judge.judge_lesson(lesson, (d / "source.txt").read_text())
        except jev.JevError as e:
            if "401" in str(e) and not STOP.is_set():
                STOP.set()
                print(f"\nStopping: Jev rejected the key ({e}). Fix TYPESAFE_API_KEY and run the same command again.\n", flush=True)
            return say(paper, f"{d.name}: interrupted ({e}); it will be tried again on the next run")
        result = jev_judge.combine(lesson, judged)
        save(out, {"status": "done", "seconds": round(time.time() - started), **judged, "result": result})
        say(paper, f"{d.name}: {result['verdict']}, {len(result['critical_errors'])} critical, {len(result['needs_review'])} to review")

    each(units(args.run, args.papers), one, args.parallel)


def plant_errors(args):
    """Copies of a run's lessons into another run, each with one planted critical error."""
    made = 0
    for d, paper in units(args.run, args.papers):
        if "-" in d.name:
            continue  # already a planted copy
        lesson, source = load(d / "lesson.json"), (d / "source.txt").read_text()
        for kind in args.kinds or PLANT_KINDS:
            planted = plant_mod.plant(lesson, L.source_document(source), kind, seed=paper["id"])
            if not planted:
                say(paper, f"no concept fits {kind}")
                continue
            copy_, where_ = planted
            to = EVAL / "results" / args.into / "papers" / f"{d.name}-{kind}"
            to.mkdir(parents=True, exist_ok=True)
            save(to / "lesson.json", copy_)
            (to / "source.txt").write_text(source)
            save(to / "planted.json", where_)
            made += 1
    record_run(args.into, planted_from=args.run)
    print(f"Planted {made} errors into eval/results/{args.into}. Judge them with: eval/run.py judge --run {args.into}")


# ---------------------------------------------------------------- summary


def _critical_flags(result: dict, concept: str) -> tuple[set, set]:
    """The critical-error types most lenses confirmed at a concept, and those any lens raised there."""
    confirmed = {c["type"] for c in result["critical_errors"] if c["where"] == concept}
    raised = {x["what"].split(" ", 1)[1].split(":")[0] for x in result["needs_review"]
              if x["what"].startswith(concept + " ") and x["why"].startswith(("a critical", "a possible"))}
    return confirmed, confirmed | raised


def caught(planted: dict, result: dict, original_run: str | None, unit: str) -> dict:
    """Whether judging found the planted error: a flag at its concept that the original lesson didn't have."""
    at, kind = planted["concept"], planted["kind"]
    before_confirmed, before_raised = set(), set()
    orig = load(EVAL / "results" / original_run / "papers" / unit.split("-")[0] / "judge-jev.json") if original_run else None
    if orig and orig.get("status") == "done":
        before_confirmed, before_raised = _critical_flags(orig["result"], at)
    confirmed, raised = _critical_flags(result, at)
    return {"unit": unit, "kind": kind, "concept": at, "detail": planted["detail"], "verdict": result["verdict"],
            "flagged": bool(raised - before_raised or confirmed - before_confirmed), "confirmed": bool(confirmed - before_confirmed),
            "same_type": kind in confirmed - before_confirmed,
            "masked": kind in before_raised}


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}% ({part}/{whole})" if whole else "n/a"


def summary(args):
    base = Path(args.run) if Path(args.run, "papers").is_dir() else EVAL / "results" / args.run
    rows, a_all, reviews, catches = [], {i: [] for i in Q.PART_A}, [], []
    built = passed = first_draft = drafted = 0
    original = (load(base / "run.json") or {}).get("planted_from")  # planted copies are scored against their original's flags
    for d, paper in units(args.run, args.papers):
        b = load(d / "build.json") or {}
        if b:
            built += b["status"] != "interrupted"
            passed += bool(b.get("passed_without_edits"))
            drafted += len(b.get("concepts", [])) + len(b.get("omitted", []))
            first_draft += sum(c.get("repairs") == 0 for c in b.get("concepts", []))
        j = load(d / "judge-jev.json") or {}
        row = {"unit": d.name, "id": paper["id"], "field": paper.get("field", ""), "title": paper.get("title", ""),
               "build": b.get("status", ""), "error": b.get("error", ""), "concepts": len((load(d / "lesson.json") or {}).get("concepts", []))}
        if j.get("status") == "done":
            r = j["result"]
            for k, a in r["items"].items():
                if a:
                    a_all[k.rsplit(".", 1)[1]].append(a)
            row.update(scales=r["scales"], critical=r["critical_errors"], verdict=r["verdict"], top=r["top_problems"])
            reviews += [{"unit": d.name, **x} for x in r["needs_review"]]
            if (planted := load(d / "planted.json")):
                catches.append(caught(planted, r, original, d.name))
        rows.append(row)

    judged = [r for r in rows if r.get("verdict")]
    targets = {
        "quotes_support (A1 yes, target 90%)": pct(a_all["A1"].count("yes"), len(a_all["A1"])),
        "models_faithful (A2 yes, target 85%)": pct(a_all["A2"].count("yes"), len(a_all["A2"])),
        "passed_without_edits (target 80%)": pct(passed, built),
        "concepts_passing_first_draft": pct(first_draft, drafted),
        "verdict_ship": pct(sum(r["verdict"] == "ship" for r in judged), len(judged)),
        "verdict_ship_or_fixes": pct(sum(r["verdict"] in ("ship", "ship_with_fixes") for r in judged), len(judged)),
    }
    per_item = {i: {a: v.count(a) for a in ("yes", "partly", "no")} for i, v in a_all.items()}
    by_kind = {}
    for c in catches:
        k = by_kind.setdefault(c["kind"], {"planted": 0, "confirmed": 0, "flagged": 0, "same_type": 0})
        k["planted"] += 1
        for f in ("confirmed", "flagged", "same_type"):
            k[f] += c[f]
    out = {"run": load(base / "run.json"), "targets": targets, "per_item": per_item, "papers": rows, "planted": catches, "catch_rate": by_kind,
           "needs_review": reviews}
    save(base / "summary.json", out)

    md = [f"# Evaluation run {Path(args.run).name}", "", f"Judged by Jev ({(out['run'] or {}).get('judge', {}).get('model', jev.MODEL)}), "
          f"questions {Q.VERSION}. Each question is asked three ways; the majority decides.", "", "## Targets", "", "| Measure | Result |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in targets.items()]
    md += ["", "## Part A, by item (majority answers)", "", "| Item | yes | partly | no |", "|---|---|---|---|"]
    md += [f"| {i} {Q.PART_A[i]['name']} | {c['yes']} | {c['partly']} | {c['no']} |" for i, c in per_item.items()]
    if by_kind:
        md += ["", "## Planted errors caught", "", "Only flags the original lesson didn't already have count. Flagged: a new critical-error flag at the "
               "planted concept reached a person (confirmed, or raised by one lens). Confirmed: most lenses called it critical. "
               "As the right type: confirmed as the kind that was planted.", "", "| Kind | Planted | Flagged | Confirmed | As the right type |", "|---|---|---|---|---|"]
        md += [f"| {k} | {v['planted']} | {pct(v['flagged'], v['planted'])} | {pct(v['confirmed'], v['planted'])} | {pct(v['same_type'], v['planted'])} |"
               for k, v in by_kind.items()]
        missed = [c for c in catches if not c["flagged"]]
        md += [""] + [f"- Missed: **{c['unit']}** ({c['concept']}): {c['detail']}" + (" (the original was already flagged for this, which hides it)" if c["masked"] else "")
                      for c in missed]
    dims = list(Q.PART_B)
    md += ["", "## Lessons", "", "| Lesson | Field | Build | Concepts | " + " | ".join(dims) + " | Critical | Verdict | Top problems |",
           "|---|---|---|---|" + "---|" * len(dims) + "---|---|---|"]
    for r in rows:
        scales = " | ".join(f"{r['scales'][s]:.0%}" if r.get("scales") else "" for s in dims)
        md.append(f"| {r['unit']} | {r['field']} | {r['build']} | {r['concepts']} | {scales} | {len(r.get('critical', []))} | {r.get('verdict') or 'not judged'} | "
                  + "; ".join(r.get("top", [])).replace("|", "/") + " |")
    failed = [r for r in rows if r["error"]]
    if failed:
        md += ["", "## Builds that didn't finish", ""] + [f"- **{r['unit']}. {r['title']}** ({r['build']}): {r['error'][:300]}" for r in failed]
    md += ["", f"## Needs a person to look ({len(reviews)})", "", "Critical-error flags first, then by how sure Jev was. Each shows exactly what Jev was given.", ""]
    for x in reviews:
        votes = ", ".join(f"{v['lens']}: {v['answer']} ({v['p']:.2f})" for v in x["votes"])
        md += [f"### {x['unit']}: {x['what']}", "", f"{x['why'][0].upper() + x['why'][1:]}. Votes: {votes}.", "", f"> {x['question']}", "",
               "<details><summary>What Jev saw</summary>", "", "```text", x["state"], "```", "", "</details>", ""]
    (base / "summary.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:md.index("## Part A, by item (majority answers)")]))
    for k, v in by_kind.items():
        print(f"planted {k}: flagged {pct(v['flagged'], v['planted'])}, confirmed {pct(v['confirmed'], v['planted'])}")
    print(f"\nWrote {base / 'summary.md'}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eval/run.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="step", required=True)
    for name, fn in (("build", build), ("judge", judge), ("plant", plant_errors), ("summary", summary)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("--run", default=time.strftime("%Y-%m-%d"), help="name of the results folder, or a path to one (default: today's date)")
        p.add_argument("--papers", help="paper ids, such as 1-5,9 (default: all)")
        if name in ("build", "judge"):
            p.add_argument("--parallel", type=int, default=1, help="lessons worked on at once (default 1)")
            p.add_argument("--redo", action="store_true", help="redo work already saved")
        if name == "build":
            p.add_argument("--builder", required=True, help="provider:model that builds the lessons, such as claude:claude-opus-5-5")
        if name == "plant":
            p.add_argument("--into", required=True, help="the run to write the planted copies into")
            p.add_argument("--kinds", nargs="*", choices=PLANT_KINDS, help=f"which errors to plant (default: all of {', '.join(PLANT_KINDS)})")
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
