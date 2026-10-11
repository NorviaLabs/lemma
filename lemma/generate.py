"""Building lessons: outline a paper, then create and check each concept."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import lesson as L
from .llm import Provider, ProviderError

MAX_REPAIRS = 2
WORKERS = 3

PRINCIPLES = """\
You are Lemma. You turn a research paper into a short, hands-on lesson in the spirit of Brilliant.org and \
3Blue1Brown, for papers from any discipline. The learner understands each idea by playing with a live model \
of it before reading the explanation.

Principles you must follow:
1. Teach first, then practise. The learner has not read the paper and knows nothing of it. Before any exhibit \
they read "the paper in brief": what question it asks, what was done, what was found and why it matters. Each \
concept then teaches before it asks anything: a short narrated tour introduces the model (what the picture shows, \
what each control does), a narrated walkthrough teaches the idea on the model, and a plain explanation with the \
paper's own words follows. Only then does the learner practise with goals and apply the idea to a new case. \
Quizzes are the exception: only a concept marked hard gets a check.
2. Live models, not slides. Each model responds to its controls and can answer "what if?". Goals must need \
the learner to move controls. Reading a number off the screen is not enough.
3. One idea at a time. Each concept teaches exactly one mechanism.
4. Grounded and honest. Every concept quotes the paper word for word: copy one contiguous passage exactly as \
it appears in the paper text. You may repair spacing broken by PDF extraction, but never change, add, drop \
or reorder words. Models are teaching models: say how each is simplified, and never present invented numbers \
as the paper's results. If the paper reports a number, you may use it and say where it comes from.
5. Plain language. Short, clear sentences for the stated audience, without simplifying away scientific \
caveats such as sample limits, correlation versus causation, or uncertainty.
6. Prefer the visual type that shows the mechanism most directly. For populations, relationships and causes \
(common in psychology, sociology and economics), consider agents, network, causal and sampling visuals \
rather than forcing a curve.
7. Never mention Brilliant.org or 3Blue1Brown in a lesson.

Reply with JSON only: no prose before or after it, no comments inside it.
"""


def system_prompt() -> str:
    return PRINCIPLES + "\n\nLESSON FORMAT\n" + L.schema_guide()


def paper_document(text: str) -> str:
    return f"<paper>\n{text}\n</paper>"


OUTLINE_TASK = """\
Read the paper above. The lesson is for: {audience}

First find the paper's "aha": its single most surprising or satisfying result, the thing a newcomer would \
not expect. Then propose a path of {n_hint} concepts, from the prerequisites the audience needs up to that aha. \
Each concept teaches one mechanism that a live model can show, and adds one piece to the last.

Reply with this JSON:
{{
  "title": "A plain, inviting lesson title (not the paper title)",
  "source": {{"title": "The paper's exact title", "authors": "Authors as written", "year": 2020, "venue": "Journal or conference, if stated"}},
  "summary": "3–5 plain sentences: what question the paper asks, what it did, what it found, and its main limitation",
  "background": ["2–4 short pieces of helpful background, one sentence each"],
  "primer": [
    {{"heading": "The question", "body": "2–4 plain sentences", "quote": "An exact passage from the paper, or omit", "quote_where": "e.g. Introduction"}},
    {{"heading": "What they did", "body": "..."}},
    {{"heading": "What they found", "body": "...", "quote": "...", "quote_where": "..."}},
    {{"heading": "Why it matters", "body": "..."}}
  ],
  "aha": "The paper's most surprising result, in one plain sentence a newcomer would find striking",
  "concepts": [
    {{"id": "lower_snake_case", "title": "Short title", "idea": "The one mechanism, in one sentence",
      "role": "prerequisite | core | contribution", "visual": "curves | bars | table | agents | network | causal | sampling | geometry",
      "why": "Why this visual shows the mechanism",
      "builds_on": null, "hard": false}}
  ]
}}
The primer is "the paper in brief", read before the first concept by someone who has never heard of the paper: \
3–6 pages that tell its story in order (the question and why anyone cared, what was done, what was found, why it \
matters and its limits). Explain any idea it needs in plain words; don't save the result for later. At least two pages \
quote the paper word for word (copy one contiguous passage exactly).
Use null for unknown year or venue. Order concepts so each builds on the last; the final concept should deliver the aha.
Small steps: if an idea needs more than one mechanism, split it into 2–3 smaller concepts in a row, each adding one piece.
Reuse pictures: when a concept can be shown by an earlier concept's model plus at most one new control, set "builds_on" to \
that earlier concept's id and give it the same visual. Otherwise "builds_on" is null.
Add "hard": true to at most two concepts, the ones a newcomer is most likely to get wrong even after exploring (counterintuitive or multi-step); every other concept gets "hard": false. Only hard concepts get a quiz-style check."""


CONCEPT_TASK = """\
The lesson is for: {audience}
Lesson outline (for context; build only the concept marked ▶):
{outline}

Build concept ▶ "{title}" as one JSON object in the LESSON FORMAT.
Its id must be "{id}". Its idea: {idea}
Suggested visual: {visual}

Make sure that:
- teach first: the learner knows nothing yet. The "animation" tour introduces the picture and each control (use "focus"); \
the "understand.walkthrough" then teaches the idea on the model step by step, ending in a state worth looking at; the \
explanation says it again in plain words and tells what the paper did to show it. Nothing is asked before all three;
- the goals come after the teaching: they let the learner practise the idea by reproducing it on the model;
- the predict question comes last: it applies the idea to a new case or variation, so it is not answered by repeating the explanation;
- "predict.why" has one line per option saying why someone would pick it and what the idea says instead, so a wrong answer still teaches;
- each goal has 2–3 "hints" that get more specific: a nudge, then a pointer, then a partial answer;
- show it before naming it: the tour and the model's labels use plain words only; list each technical term in "terms" and name it \
first in the walkthrough, once the learner has seen what it means;
- the tour is short and lively (about 15–25 seconds in all); the walkthrough takes its time (5–8 steps) and builds to a moment worth seeing;
- {check_rule}{extra}
- every goal and model check is false at the controls' defaults and true at its `solution`, and each solution value \
lies on its slider's step grid (min + k × step);
- every expression gives a finite number over the whole range of every control;
- the quote is copied word for word from the paper and supports the explanation;
- the equation is the paper's own where it has one (otherwise the model's rule, and the caption says so), with \
at least one part linked to a control or output;
- the model's note says how it is simplified and whether its numbers are illustrative."""


REPAIR_TASK = """\
Lemma's quality checks found these problems:
{problems}

Fix every problem and reply with the complete corrected JSON object only."""


class GenerationError(Exception):
    pass


def extract_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in the reply")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj


# ---------------------------------------------------------------- jobs


class Job:
    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.status = "running"
        self.steps: list[dict] = []
        self.result = None
        self.error = ""
        self.lesson: dict | None = None
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.created = time.time()

    def step(self, sid: str, label: str, state: str = "waiting", detail: str = ""):
        with self.lock:
            for s in self.steps:
                if s["id"] == sid:
                    s.update(label=label or s["label"], state=state, detail=detail)
                    return
            self.steps.append({"id": sid, "label": label, "state": state, "detail": detail})

    def update(self, sid: str, state: str, detail: str = ""):
        self.step(sid, "", state, detail)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "status": self.status,
                "steps": [dict(s) for s in self.steps],
                "result": self.result,
                "error": self.error,
                "lesson": json.loads(json.dumps(self.lesson)) if self.lesson else None,
            }


JOBS: dict[str, Job] = {}


def start(job: Job, fn, *args):
    JOBS[job.id] = job
    for old in [j for j in JOBS.values() if j.status != "running" and time.time() - j.created > 6 * 3600]:
        JOBS.pop(old.id, None)

    def run():
        try:
            job.result = fn(job, *args)
            with job.lock:
                job.status = "cancelled" if job.cancelled.is_set() else "done"
        except (GenerationError, ProviderError) as e:
            with job.lock:
                job.status, job.error = "error", str(e)
        except Exception as e:  # keep the server alive and tell the learner honestly
            with job.lock:
                job.status, job.error = "error", f"Unexpected error: {e.__class__.__name__}: {e}"

    threading.Thread(target=run, daemon=True).start()
    return job


# ---------------------------------------------------------------- outline


def check_outline(o, source_text: str | None = None) -> list[str]:
    """``source_text`` checks the primer's quotes against the paper; None skips that."""
    problems = []
    if not isinstance(o, dict):
        return ["the reply must be a JSON object"]
    norm = L.normalize_for_match(source_text) if source_text is not None else None
    problems += [p.removeprefix("lesson.") for p in L.check_primer(o.get("primer"), norm, "primer")]
    for key in ("title", "summary"):
        if not isinstance(o.get(key), str) or not o[key].strip():
            problems.append(f"needs '{key}'")
    if not isinstance(o.get("source"), dict) or not isinstance(o["source"].get("title"), str):
        problems.append("needs source.title")
    cs = o.get("concepts")
    if not isinstance(o.get("aha"), str) or not o["aha"].strip():
        problems.append("needs 'aha': the paper's most surprising result in one sentence")
    if not isinstance(cs, list) or not 2 <= len(cs) <= 8:
        problems.append("needs 2–8 concepts")
        return problems
    ids = set()
    for i, c in enumerate(cs):
        if not isinstance(c, dict):
            problems.append(f"concepts[{i}] must be an object")
            continue
        if not isinstance(c.get("id"), str) or not L.ID_RE.match(c["id"]) or c["id"] in ids:
            problems.append(f"concepts[{i}].id must be unique lower_snake_case")
        ids.add(c.get("id"))
        for key in ("title", "idea"):
            if not isinstance(c.get(key), str) or not c[key].strip():
                problems.append(f"concepts[{i}] needs '{key}'")
        if c.get("visual") not in L.VISUAL_TYPES:
            problems.append(f"concepts[{i}].visual must be one of {L.VISUAL_TYPES}")
        b = c.get("builds_on")
        if b is not None:
            base = next((x for x in cs[:i] if isinstance(x, dict) and x.get("id") == b), None)
            if base is None:
                problems.append(f"concepts[{i}].builds_on must be the id of an earlier concept, or null")
            elif base.get("visual") != c.get("visual"):
                problems.append(f"concepts[{i}] builds on '{b}', so it must use the same visual ('{base.get('visual')}')")
    if isinstance(cs, list) and sum(1 for c in cs if isinstance(c, dict) and c.get("hard") is True) > 2:
        problems.append("mark at most two concepts as hard")
    return problems


def _ask_json(job: Job, provider: Provider, document: str, task: str, check, sid: str):
    """Ask, check, and repair up to MAX_REPAIRS times in one conversation. Returns (obj, problems)."""
    conv = provider.conversation(system_prompt(), document)
    message = task
    problems: list[str] = []
    obj = None
    try:
        for attempt in range(MAX_REPAIRS + 1):
            if job.cancelled.is_set():
                raise GenerationError("Cancelled.")
            job.update(sid, "active", "Drafting" if attempt == 0 else f"Fixing {len(problems)} problem{'s' * (len(problems) != 1)} (attempt {attempt + 1} of {MAX_REPAIRS + 1})")
            reply = conv.send(message, cancelled=job.cancelled)
            if reply.stop_reason == "max_tokens":
                problems = ["the reply was cut off; make it more concise"]
            else:
                job.update(sid, "active", "Checking")
                try:
                    obj = extract_json(reply.text)
                    problems = check(obj)
                except ValueError as e:
                    obj, problems = None, [f"the reply was not valid JSON ({e})"]
            if not problems:
                return obj, []
            message = REPAIR_TASK.format(problems="\n".join(f"- {p}" for p in problems[:25]))
        return obj, problems
    finally:
        conv.close()


def make_outline(job: Job, provider: Provider, paper_text: str, audience: str) -> dict:
    job.step("outline", "Reading the paper, summarising it and proposing a path of concepts", "active")
    task = OUTLINE_TASK.format(audience=audience or "a curious learner with no special background", n_hint="three to seven")
    obj, problems = _ask_json(job, provider, paper_document(paper_text), task, lambda o: check_outline(o, paper_text), "outline")
    if problems:
        job.update("outline", "failed", "; ".join(problems[:3]))
        raise GenerationError("Couldn't produce a usable outline for this paper: " + "; ".join(problems[:3]))
    job.update("outline", "done", f"{len(obj['concepts'])} concepts proposed")
    return obj


# ---------------------------------------------------------------- concepts


def _outline_text(concepts: list[dict], current: str) -> str:
    lines = []
    for i, c in enumerate(concepts, 1):
        mark = "▶" if c["id"] == current else " "
        known = " (the learner already knows this; it is not in the lesson)" if c.get("known") else ""
        lines.append(f"{mark} {i}. {c['title']} [{c.get('role', 'core')}, {c.get('visual', '')}]: {c['idea']}{known}")
    return "\n".join(lines)


def build_lesson(job: Job, provider: Provider, paper: dict, outline: dict, audience: str, lesson_id: str | None = None) -> dict:
    """Builds concepts in parallel; each one is published to ``job.lesson`` as soon as it passes the checks."""
    concepts = [c for c in outline["concepts"] if isinstance(c, dict)]
    todo = [c for c in concepts if not c.get("known")]
    if not todo:
        raise GenerationError("Every concept is marked as already known, so there is nothing to build.")
    src = outline.get("source") or {}
    lesson = {
        "version": 1,
        "id": lesson_id or uuid.uuid4().hex[:12],
        "title": outline.get("title") or paper.get("title") or "Lesson",
        "audience": audience,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": {
            "title": src.get("title") or paper.get("title", ""),
            "authors": src.get("authors") or "",
            "year": src.get("year"),
            "venue": src.get("venue") or "",
            "url": paper.get("url", ""),
        },
        "intro": {
            "summary": outline.get("summary", ""),
            "background": [b for b in outline.get("background", []) if isinstance(b, str)],
            "known": [c["title"] for c in concepts if c.get("known")],
            "aha": outline.get("aha") if isinstance(outline.get("aha"), str) else None,
        },
        "primer": outline.get("primer"),
        "provider": {"name": provider.name, "model": provider.model},
        "plan": [{"id": c["id"], "title": c["title"], "state": "waiting"} for c in todo],
        "concepts": [],
        "omitted": [],
    }
    job.lesson = lesson
    norm = L.normalize_for_match(paper["text"])
    document = paper_document(paper["text"])
    ready: dict[str, dict] = {}

    def publish():
        with job.lock:
            lesson["concepts"] = [ready[c["id"]] for c in todo if c["id"] in ready]

    def set_plan(cid, state):
        with job.lock:
            for p in lesson["plan"]:
                if p["id"] == cid:
                    p["state"] = state

    for i, c in enumerate(todo, 1):
        job.step(c["id"], f"Concept {i}: {c['title']}", "waiting", "Waiting to start")
    # A concept that builds on another waits for it, so it can reuse its finished model. Bases always come
    # earlier in the list and the pool runs tasks in order, so a waiting task never blocks its own base.
    finished = {c["id"]: threading.Event() for c in todo}
    todo_ids = [c["id"] for c in todo]

    def build_one(c):
        try:
            _build_one(c)
        finally:
            finished[c["id"]].set()

    def _build_one(c):
        if job.cancelled.is_set():
            return
        base = None
        b = c.get("builds_on")
        if b in finished and todo_ids.index(b) < todo_ids.index(c["id"]):
            job.update(c["id"], "waiting", "Waiting for the concept it builds on")
            finished[b].wait()
            base = ready.get(b)
        if job.cancelled.is_set():
            return
        set_plan(c["id"], "building")
        extra = ""
        if base:
            extra += ("\n- this concept builds on concept \"" + base["title"] + "\". Reuse its model exactly: the same visual type and every "
                      "control with the same id, label and range, adding at most one new control (outputs may change). The tour is "
                      "2–3 steps: remind the learner it's the same picture, then introduce only what's new. Its model was:\n"
                      + json.dumps(base["model"], ensure_ascii=False))
            done_terms = [t.get("term") for t in base.get("terms", []) if isinstance(t, dict)]
            if done_terms:
                extra += "\n- the learner already knows these terms, so they may be used freely: " + ", ".join(done_terms)
        if c["id"] == todo_ids[-1] and lesson["intro"].get("aha"):
            extra += "\n- this is the last concept: it must build to the lesson's aha, so the walkthrough ends on it: " + lesson["intro"]["aha"]
        task = CONCEPT_TASK.format(
            audience=audience or "a curious learner with no special background",
            outline=_outline_text(concepts, c["id"]),
            title=c["title"],
            id=c["id"],
            idea=c["idea"],
            visual=f"{c.get('visual', '')} ({c.get('why', '')})",
            check_rule=("this concept is marked hard: include one \"check\", preferably a model check" if c.get("hard") else
                        "this concept is not marked hard: do not include a \"check\" key"),
            extra=extra,
        )

        def check(obj):
            if isinstance(obj, dict):
                obj["id"] = c["id"]
                if not c.get("hard"):
                    obj.pop("check", None)  # quizzes are only for hard concepts
                obj.pop("builds_on", None)
                if base:
                    obj["builds_on"] = base["id"]
            problems = list(L.check_concept(obj, norm, "concept"))
            if base and isinstance(obj, dict) and not problems:
                problems = list(L.check_builds_on(obj, base, "concept"))
            return problems

        try:
            obj, problems = _ask_json(job, provider, document, task, check, c["id"])
        except (ProviderError, GenerationError) as e:
            obj, problems = None, [str(e)]
        if problems:
            set_plan(c["id"], "omitted")
            with job.lock:
                lesson["omitted"].append({"title": c["title"], "reason": problems[0]})
            job.update(c["id"], "failed", "Left out: it didn't pass the quality checks (" + problems[0][:160] + ")")
            return
        ready[c["id"]] = obj
        set_plan(c["id"], "ready")
        publish()
        job.update(c["id"], "done", "Ready")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(build_one, todo))

    if job.cancelled.is_set():
        raise GenerationError("Cancelled.")
    publish()
    if not lesson["concepts"]:
        reasons = "; ".join(o["reason"][:120] for o in lesson["omitted"][:2])
        raise GenerationError("No concept passed the quality checks, so there is no lesson to show. " + reasons)
    with job.lock:
        lesson.pop("plan", None)
    problems = L.check_lesson(lesson, paper["text"])
    if problems:
        raise GenerationError("The assembled lesson failed its final check: " + problems[0])
    return lesson
