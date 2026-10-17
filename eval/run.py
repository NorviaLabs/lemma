"""Build lessons from eval/papers.json, have three judges score them, and summarise the results.

    uv run python eval/run.py build   --run R --builder claude:claude-opus-5-5
    uv run python eval/run.py judge   --run R --judge referee=claude:claude-opus-5-5 \\
                                              --judge teacher=openai:gpt-6.1-sol \\
                                              --judge newcomer=opencode-go:<model>
    uv run python eval/run.py summary --run R

Keys come from the environment, one per provider: LEMMA_EVAL_KEY_CLAUDE, LEMMA_EVAL_KEY_OPENAI and
LEMMA_EVAL_KEY_OPENCODE_GO. `--papers 1-5,9` picks papers. Each step skips work it has already
saved, so a run interrupted by a usage limit carries on where it stopped; `--redo` does it again.

Everything is written under eval/results/<run>/: run.json (who built and judged, and Lemma's commit)
and, for each paper, papers/<id>/ with source.txt, outline.json, lesson.json, build.json and one
judge-<name>.json per judge. `summary` writes summary.json and summary.md.

The lessons are built exactly as a learner's would be, from the outline the model proposes with no
review, so "passed without edits" means no concept was left out. Judges see the lesson without the
`provider` field, so they don't know which model built it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lemma import generate, ingest, lesson as L  # noqa: E402
from lemma.llm import PROVIDERS, ProviderError, make_provider  # noqa: E402

EVAL = Path(__file__).resolve().parent
PAPERS = json.loads((EVAL / "papers.json").read_text())
AUDIENCE = "A curious adult with no background in this field"
JUDGES = ("referee", "teacher", "newcomer")
ITEMS = ("A1", "A2", "A3", "A4", "A5", "A6")
SCALES = ("B1", "B2", "B3", "B4", "B5", "B6")
VERDICTS = ("ship", "ship_with_fixes", "dont_ship")  # least to most cautious


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


# ---------------------------------------------------------------- judge


def blind(lesson: dict) -> str:
    """The lesson as a judge sees it: without which model built it."""
    return json.dumps({k: v for k, v in lesson.items() if k not in ("provider", "created")}, indent=1, ensure_ascii=False)


def ask_json(conv, message: str) -> tuple[dict, str]:
    """Sends a message and parses the one JSON object it should get back, asking once more if it doesn't."""
    reply = conv.send(message)
    try:
        return _parse(reply), reply.text
    except ValueError as e:
        reply = conv.send(f"That reply couldn't be used ({e}). Reply again with only the JSON object, as compact as the rubric allows.")
    try:
        return _parse(reply), reply.text
    except ValueError as e:
        raise ValueError(f"{e}; reply began: {reply.text[:300]!r}") from None


def _parse(reply) -> dict:
    if reply.stop_reason == "max_tokens":
        raise ValueError("the reply was cut off")
    obj = generate.extract_json(reply.text)
    if not isinstance(obj, dict):
        raise ValueError("the reply was not a JSON object")
    return obj


def judge(args):
    specs = {}
    for spec in args.judge:
        name, _, rest = spec.partition("=")
        if name not in JUDGES or not rest:
            sys.exit(f"--judge takes name=provider:model, with name one of {', '.join(JUDGES)}")
        specs[name] = provider_for(rest)
    rubric = (EVAL / "rubric.md").read_text()
    personas = {n: (EVAL / "judges" / f"{n}.md").read_text() for n in specs}
    record_run(args.run, judges={n: {"provider": p.id, "model": p.model} for n, p in specs.items()}, judged=time.strftime("%Y-%m-%dT%H:%M:%S"))

    def one(paper):
        d = folder(args.run, paper)
        lesson = load(d / "lesson.json")
        if not lesson:
            return say(paper, "no lesson to judge")
        text = L.source_document((d / "source.txt").read_text())
        intro = f"PAPER ID: {paper['id']}\n\nAUDIENCE: {lesson.get('audience') or AUDIENCE}\n\nLESSON:\n{blind(lesson)}"
        for name, provider in specs.items():
            out = d / f"judge-{name}.json"
            if out.exists() and not args.redo:
                continue
            if STOP.is_set():
                return
            say(paper, f"{name} judging with {provider.model}")
            started = time.time()
            result = {"judge": name, "provider": provider.id, "model": provider.model}
            try:
                if name == "newcomer":
                    conv = provider.conversation(personas[name], intro)
                    turn1, raw1 = ask_json(conv, "This is Turn 1. Go through the lesson as the learner and reply with only the Turn 1 JSON.")
                    obj, raw = ask_json(conv, f"This is Turn 2. Here is the rubric, then the paper.\n\nRUBRIC:\n{rubric}\n\nPAPER:\n{text}\n\n"
                                              "Answer the whole rubric as the Newcomer, and reply with only the JSON object.")
                    obj.setdefault("lens", {})["turn1"] = turn1  # exactly as the judge gave it, whatever it copied
                    result["raw_turn1"] = raw1
                else:
                    conv = provider.conversation(personas[name] + "\n\n" + rubric, f"{intro}\n\nPAPER:\n{text}")
                    obj, raw = ask_json(conv, "Judge this lesson against the paper, following the rubric. Reply with only the JSON object.")
                conv.close()
                obj["judge"], obj["paper_id"] = name, paper["id"]
                result.update(status="done", judgement=obj, raw=raw)
            except ProviderError as e:
                note_account_fault(str(e))
                result.update(status="failed" if lesson_fault(str(e)) else "interrupted", error=str(e))
            except ValueError as e:  # the judge's reply couldn't be used
                result.update(status="failed", error=str(e))
            result["seconds"] = round(time.time() - started)
            if result["status"] != "interrupted":  # interrupted judgements are tried again on the next run
                save(out, result)
            say(paper, f"{name} {result['status']}" + (f": {result['error'][:100]}" if result.get("error") else f", verdict {result['judgement'].get('verdict')}"))

    each(pick(args.papers), one, args.parallel)


# ---------------------------------------------------------------- summary


def majority(answers: list[str]) -> tuple[str | None, bool]:
    """The answer most judges gave, ignoring cannot_judge, and whether it needs a person to look."""
    votes = [a for a in answers if a in ("yes", "partly", "no")]
    if not votes:
        return None, bool(answers)
    best = max(set(votes), key=votes.count)
    if votes.count(best) * 2 > len(votes):
        return best, False
    return "partly", True  # no majority


def median_verdict(verdicts: list[str]) -> str | None:
    """The median verdict; with two judges, the more cautious of them."""
    ranks = sorted(VERDICTS.index(v) for v in verdicts if v in VERDICTS)
    return VERDICTS[ranks[len(ranks) // 2]] if ranks else None


def where(path: str) -> str:
    """The part of the lesson a path points into, so two judges' reports of one error can be matched."""
    m = re.match(r"\s*(concepts\[\d+\]|primer(\[\d+\])?|intro)", path or "")
    return m.group(1) if m else (path or "").split(".")[0]


def alpha(units: list[list[float]]) -> float | None:
    """Krippendorff's alpha with the interval metric; each unit is the scores the judges gave one item."""
    units = [u for u in units if len(u) >= 2]
    values = [v for u in units for v in u]
    n = len(values)
    if n < 2:
        return None
    observed = sum(sum((a - b) ** 2 for a, b in combinations(u, 2)) * 2 / (len(u) - 1) for u in units)
    expected = sum((a - b) ** 2 for a, b in combinations(values, 2)) * 2
    return None if expected == 0 else round(1 - (n - 1) * observed / expected, 3)


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}% ({part}/{whole})" if whole else "n/a"


def summary(args):
    rows, a_all, a_agree, a_total, b_units, reviews = [], {i: [] for i in ITEMS}, 0, 0, [], []
    built = passed = first_draft = drafted = 0
    for paper in pick(args.papers):
        d = EVAL / "results" / args.run / "papers" / f"{paper['id']:02d}"
        b = load(d / "build.json")
        if not b:
            continue
        built += b["status"] != "interrupted"
        passed += bool(b.get("passed_without_edits"))
        for c in b.get("concepts", []):
            drafted += 1
            first_draft += c.get("repairs") == 0
        drafted += len(b.get("omitted", []))
        js = {n: (load(d / f"judge-{n}.json") or {}) for n in JUDGES}
        js = {n: j["judgement"] for n, j in js.items() if j.get("status") == "done"}
        row = {"id": paper["id"], "field": paper["field"], "title": paper["title"], "build": b["status"], "error": b.get("error", ""),
               "concepts": len(b.get("concepts", [])), "omitted": len(b.get("omitted", [])), "judges": sorted(js)}
        if js:
            concept_ids = [c["id"] for c in b.get("concepts", [])]
            items = {}
            for cid in concept_ids:
                for item in ITEMS:
                    answers = [next(((c.get(item) or {}).get("answer") for c in j.get("concepts", []) if isinstance(c, dict) and c.get("id") == cid), None)
                               for j in js.values()]
                    answers = [a for a in answers if a]
                    verdict, review = majority(answers)
                    items[f"{cid}.{item}"] = verdict
                    if verdict:
                        a_all[item].append(verdict)
                    if review:
                        reviews.append({"paper": paper["id"], "what": f"{cid} {item}", "answers": answers})
                    graded = [a for a in answers if a != "cannot_judge"]
                    if len(graded) == 3:
                        a_total += 1
                        a_agree += len(set(graded)) == 1
            scales = {}
            for s in SCALES:
                scores = [((j.get("lesson") or {}).get(s) or {}).get("score") for j in js.values()]
                scores = [float(x) for x in scores if isinstance(x, (int, float))]
                b_units.append(scores)
                scales[s] = statistics.median(scores) if scores else None
            reported = {}
            for n, j in js.items():
                for e in j.get("critical_errors") or []:
                    reported.setdefault((e.get("type"), where(e.get("path", ""))), []).append({"judge": n, **e})
            def doubted_by(w, reporters):
                """Other judges who rated the concept at `w` less than yes on a faithfulness or fairness item."""
                m = re.fullmatch(r"concepts\[(\d+)\]", w)
                if not m or int(m.group(1)) >= len(concept_ids):
                    return []
                cid = concept_ids[int(m.group(1))]
                return [n for n, j in js.items() if n not in reporters and any(
                    (c.get(i) or {}).get("answer") in ("partly", "no")
                    for c in j.get("concepts", []) if isinstance(c, dict) and c.get("id") == cid for i in ("A1", "A2", "A3", "A6"))]

            confirmed = []
            for (t, w), es in reported.items():
                reporters = sorted({e["judge"] for e in es})
                backing = doubted_by(w, reporters) if len(reporters) < 2 else []
                if len(reporters) >= 2 or backing:
                    confirmed.append({"type": t, "where": w, "judges": reporters, "backed_by": backing, "reports": es})
                else:
                    reviews.append({"paper": paper["id"], "what": f"critical error ({t}) at {w}, reported only by {reporters[0]}", "report": es[0]})
            row.update(items=items, scales=scales, critical_errors=confirmed, verdict=median_verdict([j.get("verdict") for j in js.values()]),
                       verdicts={n: j.get("verdict") for n, j in js.items()},
                       teach_back_right=js.get("newcomer", {}).get("lens", {}).get("teach_back_was_right"))
            if confirmed and row["verdict"] != "dont_ship":
                row["verdict"] = "dont_ship"  # a confirmed critical error means it can't be shown as it is
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
    agreement = {"part_a_all_three_agree": pct(a_agree, a_total), "part_b_krippendorff_alpha": alpha(b_units)}
    per_item = {i: {a: v.count(a) for a in ("yes", "partly", "no")} for i, v in a_all.items()}
    out = {"run": load(EVAL / "results" / args.run / "run.json"), "targets": targets, "agreement": agreement, "per_item": per_item, "papers": rows, "needs_review": reviews}
    save(EVAL / "results" / args.run / "summary.json", out)

    md = [f"# Evaluation run {args.run}", "", "## Targets", "", "| Measure | Result |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in targets.items()]
    md += ["", "## Judge agreement", "", f"- All three agree on a Part A item: {agreement['part_a_all_three_agree']}",
           f"- Krippendorff's alpha on Part B: {agreement['part_b_krippendorff_alpha']}", "",
           "## Part A, by item (majority answers)", "", "| Item | yes | partly | no |", "|---|---|---|---|"]
    md += [f"| {i} | {c['yes']} | {c['partly']} | {c['no']} |" for i, c in per_item.items()]
    md += ["", "## Papers", "", "| # | Field | Build | Concepts | Left out | " + " | ".join(SCALES) + " | Critical | Verdict | Judges |",
           "|---|---|---|---|---|" + "---|" * len(SCALES) + "---|---|---|"]
    for r in rows:
        scales = " | ".join(f"{r['scales'][s]:g}" if r.get("scales", {}).get(s) is not None else "" for s in SCALES)
        md.append(f"| {r['id']} | {r['field']} | {r['build']} | {r['concepts']} | {r['omitted']} | {scales} | "
                  f"{len(r.get('critical_errors', []))} | {r.get('verdict') or ''} | {', '.join(f'{n}: {v}' for n, v in r.get('verdicts', {}).items())} |")
    failed = [r for r in rows if r["error"]]
    if failed:
        md += ["", "## Builds that didn't finish", ""] + [f"- **{r['id']}. {r['title']}** ({r['build']}): {r['error'][:300]}" for r in failed]
    md += ["", f"## Needs a person to look ({len(reviews)})", ""] + [f"- Paper {x['paper']}: {x['what']}" for x in reviews]
    (EVAL / "results" / args.run / "summary.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:md.index("## Part A, by item (majority answers)")]))
    print(f"\nWrote {EVAL / 'results' / args.run / 'summary.md'}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eval/run.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="step", required=True)
    for name, fn in (("build", build), ("judge", judge), ("summary", summary)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("--run", default=time.strftime("%Y-%m-%d"), help="name of the results folder (default: today's date)")
        p.add_argument("--papers", help="paper ids, such as 1-5,9 (default: all)")
        if name != "summary":
            p.add_argument("--parallel", type=int, default=1, help="papers worked on at once (default 1; each build already runs concepts in parallel)")
            p.add_argument("--redo", action="store_true", help="redo work already saved")
        if name == "build":
            p.add_argument("--builder", required=True, help="provider:model that builds the lessons, such as claude:claude-opus-5-5")
        if name == "judge":
            p.add_argument("--judge", action="append", required=True, help="name=provider:model, once per judge")
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
