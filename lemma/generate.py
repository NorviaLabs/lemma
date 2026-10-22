"""Building lessons: outline a paper, then create and check each concept."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import factcheck, jev, levels
from . import lesson as L
from . import logs, metrics
from .llm import Provider, ProviderError

MAX_REPAIRS = 2
WORKERS = 3

MULTI_SOURCE_TASK = """
The document contains labelled sources. Teach one cohesive, standard-depth lesson, not one section per source.
Order the concepts by what each relies on, never by source: an idea from a later source that an earlier concept
needs comes first, and "needs" may name concepts drawn from any source.
Cover the central ideas and essential prerequisites within the existing concept limit. Identify gaps and
suggest deeper follow-up topics in the summary. Explain meaningful disagreements and uncertainty explicitly;
never invent consensus or claim exhaustive coverage. Every primer page and every concept's understand object
must include source_ids (a nonempty list of supporting SOURCE IDs). Every quote must also have source_id,
identifying the single source containing that exact passage. Do not stitch quotes across sources.
"""

PRINCIPLES = """\
You are Lemma. You turn a research paper into a short, hands-on lesson in the spirit of Brilliant.org and \
3Blue1Brown, for papers from any discipline. The learner understands each idea by playing with a live model \
of it before reading the explanation.

Principles you must follow:
1. Teach first, then practise. The learner has not read the paper and knows nothing of it. Before any concept \
they read "the paper in brief": what question it asks, what was done, what was found and why it matters. Each \
concept then teaches before it asks anything: a short narrated tour introduces the model (what the picture shows, \
what each control does), a narrated walkthrough teaches the idea on the model, and a plain explanation with the \
paper's own words follows. Only then does the learner practise with goals and apply the idea to a new case. \
Quizzes are the exception: only a concept marked hard gets a check.
2. Live models where they fit, other activities where they don't. A model responds to its controls and can answer \
"what if?"; goals must need the learner to move controls, and reading a number off the screen is not enough. When an \
idea is a distinction, an argument, a legal test, a historical chain or a case, teach it with comparisons, staged \
evidence and classifying, matching, ordering or tracing tasks instead: never invent a quantity to make it a slider.
3. One idea at a time. Each concept teaches exactly one mechanism.
4. Grounded and honest. Every concept quotes the paper word for word: copy one contiguous passage exactly as \
it appears in the paper text. You may repair spacing broken by PDF extraction, but never change, add, drop \
or reorder words. Models are teaching models: say how each is simplified, and never present invented numbers \
as the paper's results. If the paper reports a number, you may use it and say where it comes from.
5. Plain language. Short, clear sentences for the learner's stated level, without simplifying away scientific \
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
Read the paper above. The learner's level: {level}

First find the paper's "aha": its single most surprising or satisfying result, the thing a newcomer would \
not expect. Then propose a path of {n_hint} concepts, from the prerequisites this learner needs up to that aha. \
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
      "role": "prerequisite | core | contribution", "visual": "curves | bars | table | agents | network | causal | sampling | geometry | none",
      "why": "Why this visual (or no model) teaches the idea",
      "plans": [{{"blocks": ["watch", "walk", "explain", "goal", "predict", "reveal", "connect"], "why": "What the learner does and why it fits"}},
                {{"blocks": ["explain", "stages", "choice"], "why": "..."}}],
      "needs": [], "builds_on": null, "hard": false}}
  ]
}}
The primer is "the paper in brief", read before the first concept by someone who has never heard of the paper: \
3–6 pages that tell its story in order (the question and why anyone cared, what was done, what was found, why it \
matters and its limits). Explain any idea it needs in plain words; don't save the result for later. At least two pages \
quote the paper word for word (copy one contiguous passage exactly).
Use null for unknown year or venue. Order concepts so each builds on the last; the final concept should deliver the aha.
The learner meets the concepts in this order and can only use what came before. "needs" lists the ids of the earlier \
concepts this one relies on: the ideas, terms or results a learner must already have to follow it ([] if none). \
Everything in "needs" and "builds_on" must come earlier in the list, so prerequisites come before the ideas that use them.
Small steps: if an idea needs more than one mechanism, split it into 2–3 smaller concepts in a row, each adding one piece.
Reuse pictures: when a concept can be shown by an earlier concept's model plus at most one new control, set "builds_on" to \
that earlier concept's id and give it the same visual. Otherwise "builds_on" is null.
"visual": "none" teaches the concept without a live model, for ideas that are distinctions, arguments, legal tests, \
cases or history rather than quantities; it cannot be built on. "plans" gives 2–3 different ways to teach the concept, \
each an ordered list of ACTIVITIES block kinds (see LESSON FORMAT) that teaches before it asks, with one line on what \
the learner does and why it fits; a plan for a concept with no model uses no model blocks. The best one is chosen later.
Add "hard": true to at most two concepts, the ones a newcomer is most likely to get wrong even after exploring (counterintuitive or multi-step); every other concept gets "hard": false. Only hard concepts get a quiz-style check."""

QUESTION_TASK = """
The learner came with a question: «{question}»{field}
This lesson answers it. The "aha" is the sources' answer to that question, and the last concept delivers it; if the \
sources answer only part of it, the summary says so plainly.
What an answer builds on, most needed first, as the search found it:
{subjects}
Teach one of these as a concept only where a source covers it. List the ones the lesson takes as known instead, and \
every one marked "no source", in "assumes": a list of their titles, exactly as written above. Give every concept a \
"subject": the title above that it teaches, or null if it teaches none of them. A concept that teaches something to \
learn first comes before every core or contribution concept.
"""
SOURCES_TASK = """
What these sources build on, most needed first, as Jev rated it for this learner:
{subjects}
Teach one of these as a concept only where a source covers it, and only as far as the sources' own ideas need it; \
the sources' own content comes first, so at most {most} concepts teach these. List the ones the lesson takes as known instead, and every one marked "no \
source", in "assumes": a list of their titles, exactly as written above. Give every concept a "subject": the title \
above that it teaches, or null if it teaches none of them. A concept that teaches something to learn first comes \
before every core or contribution concept.
"""
BRIDGE_TASK = """\
The question needs both {fields}: mark the one concept that connects them with "bridge": true (every other concept \
leaves it out). Teach the connection only as far as a source states it; where the sources don't state it, that concept \
says plainly that these sources don't establish the link.
"""
BROUGHT_BACKGROUND = 2  # concepts a lesson from brought sources may spend on what they build on (brought-2026-10-23)
NEED_WORDS = ((4.0, "needed"), (3.0, "helps"), (0.0, "nice to know"))  # need on Jev's 1 to 5 scale, as search reports it
RELATION_WORDS = {"prerequisite": "learn first", "part": "part of the answer", "explains": "connects the two fields"}


def search_subjects(search: dict, paper_text: str) -> list[dict]:
    """The search's subjects, each with the id of a chosen source that is its own article (or None), then the
    subjects no source was found for."""
    sources = L.source_map(paper_text)
    key = lambda t: re.sub(r"[^a-z0-9]", "", str(t).lower())
    out = []
    for subject in search.get("subjects", []):
        own = next((sid for sid, src in sources.items() if key(src.get("title", "")).startswith(key(subject["title"]))), None)
        out.append(dict(subject, source=own))
    return out + [{"title": t, "need": None, "relation": None, "source": None} for t in search.get("not_covered", [])]


def _question_task(search: dict, subjects: list[dict]) -> str:
    field = field_names(search)
    lines = []
    for s in subjects:
        need = next((w for at, w in NEED_WORDS if (s["need"] or 0) >= at), "") if s["need"] is not None else "needed"
        what = ", ".join(filter(None, [need, RELATION_WORDS.get(s["relation"])]))
        where = f"a source covers it: {s['source']}" if s["source"] else "no source"
        lines.append(f"- {s['title']} ({what}; {where})")
    if not search.get("query"):  # sources the learner brought: what they build on, with no question to answer
        return SOURCES_TASK.format(subjects="\n".join(lines), most=BROUGHT_BACKGROUND)
    task = QUESTION_TASK.format(question=search["query"], field=f" (field: {field})" if field else "",
                                subjects="\n".join(lines) or "- (none found)")
    return task + (BRIDGE_TASK.format(fields=field) if len(search.get("field") or []) == 2 else "")


def field_names(search: dict | None) -> str:
    from .categorize import CATEGORIES  # categorize imports lesson, which generate imports first
    return " and ".join(CATEGORIES[f][0] for f in (search or {}).get("field") or [] if f in CATEGORIES)


CONCEPT_TASK = """\
The learner's level: {level}
Lesson outline (for context; build only the concept marked ▶):
{outline}

Build concept ▶ "{title}" as one JSON object in the LESSON FORMAT.
Its id must be "{id}". Its idea: {idea}
Suggested visual: {visual}

Make sure that:
- teach first: the learner knows nothing yet. The "animation" tour introduces the picture and each control (use "focus"; \
to point at a curve, bar, point, marker or line, give it an "id" and focus on that id); \
the "understand.walkthrough" then teaches the idea on the model step by step, ending in a state worth looking at; the \
explanation says it again in plain words and tells what the paper did to show it. Nothing is asked before all three;
- follow the outline's order: the learner has just done the concepts above ▶ and knows their ideas and terms, so \
build on them (especially the ones it relies on) without teaching them again, and never rely on an idea from a \
concept below ▶, which the learner hasn't met yet;
- the goals come after the teaching: they let the learner practise the idea by reproducing it on the model;
- the predict question comes last: it applies the idea to a new case or variation, so it is not answered by repeating the explanation;
- "predict.why" has one line per option saying why someone would pick it and what the idea says instead, so a wrong answer still teaches;
- a goal needs the idea: the learner has to reason about what the model will do, not just push one slider to an end or \
copy a setting from the walkthrough. Its text says what to achieve, never which values to set (no "set the range to 0.12 or less");
- each goal has 2–3 "hints" that get more specific: a nudge, then a pointer, then one that narrows it down. No goal text \
or hint states the value its solution sets: finding it is the practice, and Show me gives the answer;
- show it before naming it: the tour and the model's labels use plain words only; list each technical term in "terms" and name it \
first in the walkthrough, once the learner has seen what it means;
- the tour is short and lively (about 15–25 seconds in all); the walkthrough takes its time (5–8 steps) and builds to a moment worth seeing;
- {check_rule}{extra}
- every goal and model check is false at the controls' defaults and true at its `solution`, and each solution value \
lies on its slider's step grid (min + k × step);
- every expression gives a finite number over the whole range of every control;
- the quote is copied word for word from the paper and is the paper's own statement of what the explanation claims: \
a finding, a mechanism or an argument. Not just the definition of a term, and not an intuition the paper goes on to qualify;
- the model follows the paper exactly for the case it shows: where the paper gives different rules or rates for \
different variants (say, two kinds of layer or two update rules), use the one for the variant the lesson names, and \
say which it is. If a simulation kernel only approximates the paper's model, the note says how, and the tour and \
walkthrough describe only behaviour the kernel actually shows;
- the equation is the paper's own where it has one (otherwise the model's rule, and the caption says so), with \
at least one part linked to a control or output;
- the model's note says how it is simplified and whether its numbers are illustrative;
- "activities" lists the learner's screens in order (see ACTIVITIES): {plan_rule}"""


CONCEPT_TASK_NO_MODEL = """\
The learner's level: {level}
Lesson outline (for context; build only the concept marked ▶):
{outline}

Build concept ▶ "{title}" as one JSON object in the LESSON FORMAT, as A CONCEPT WITHOUT A MODEL.
Its id must be "{id}". Its idea: {idea}
Why it has no model: {visual}

Make sure that:
- teach first: the learner knows nothing yet. Teaching blocks (explain, worked, compare, stages) come before any
response block, except an "opening" choice, an unscored first judgment the learner may revisit later;
- follow the outline's order: build on the concepts above ▶ without teaching them again, and never rely on one below it;
- "activities" lists the learner's screens in order: {plan_rule}
- every response block gives prepared feedback for every option, card or step, so a wrong answer still teaches;
determinate tasks have one supported answer; interpretive ones explain each reading's support and limits and never
grade agreement; factual mistakes and misattributions are still corrected;
- every case, number or person that is not in the paper is marked "hypothetical": true, and nothing invented is
presented as the paper's evidence, finding or quotation;
- "understand" holds the explanation (3–6 plain sentences) and a quote copied word for word from the paper that is
its own statement of the idea, with quote_where; every "passage" option is also copied word for word;
- show it before naming it: list each technical term in "terms" and introduce it in a teaching block first.{extra}"""


PLAN_TIMEOUT = 30  # seconds for Jev to choose every concept's activity plan


def plan_rule(choice: dict | None) -> str:
    """The instruction for one concept's activities: Jev's chosen plan, or the model's own choice."""
    plan = (choice or {}).get("plan")
    if plan:
        return ("follow this plan, chosen as the best way to teach this concept: " + " → ".join(plan["blocks"]) +
                f" ({plan.get('why', '')}). Use these block kinds in this order; repeat a kind where the content needs it.")
    return "choose the blocks that best fit the reasoning this concept involves, teaching before asking."


def choose_plans(job: Job, outline: dict, concepts: list[dict], level: str) -> dict:
    """Jev chooses, for each concept with candidate plans, the one that would best teach it, or none of them.
    Raises GenerationError when Jev can't, before any concept is drafted."""
    asking = [c for c in concepts if c.get("plans")]
    if not asking:
        return {}
    job.step("plans", "Choosing how to teach each concept", "active")
    titles = {c["id"]: c["title"] for c in concepts}
    state = {"learner": levels.describe(level), "lesson": outline.get("summary", ""),
             "concepts": [{"id": c["id"], "title": c["title"], "idea": c["idea"], "role": c.get("role", "core"),
                           "relies_on": [titles.get(n, n) for n in c.get("needs") or []],
                           "has_live_model": c.get("visual") != "none"} for c in concepts]}
    questions = {}
    for c in asking:
        criteria = {f"p{j}": f"{' → '.join(plan['blocks'])}: {plan.get('why', '')}" for j, plan in enumerate(c["plans"], 1)}
        criteria["none_suitable"] = "None of these plans would teach this concept well"
        questions[c["id"]] = {"type": "choice", "criteria": criteria,
                              "instructions": f"Concept '{c['title']}': {c['idea']} Which plan would best help this learner understand it, "
                                              "judged by what the learner would actually do on each screen? Prefer a live model only where its "
                                              "controls are meaningful quantities; prefer comparing, classifying, ordering or tracing for "
                                              "distinctions, arguments and cases. Choose none_suitable rather than a poor plan."}
    try:
        answers = jev.ask(state, questions, PLAN_TIMEOUT)
        chosen = {}
        for c in asking:
            pick = answers[c["id"]]["choice"]
            if pick != "none_suitable" and pick not in questions[c["id"]]["criteria"]:
                raise KeyError(pick)
            plan = None if pick == "none_suitable" else c["plans"][int(pick[1:]) - 1]
            chosen[c["id"]] = {"concept": c["id"], "chosen": pick, "plan": plan, "confidence": answers[c["id"]].get("confidence"), "model": answers.get("_model")}
    except jev.JevError as e:
        job.update("plans", "failed", str(e))
        raise GenerationError(f"Couldn't choose how to teach the concepts just now ({e}). Retry in a moment.") from None
    except (KeyError, TypeError, ValueError):
        job.update("plans", "failed", "The checking service's reply couldn't be read")
        raise GenerationError("Couldn't choose how to teach the concepts just now. Retry in a moment.") from None
    picked = sum(1 for x in chosen.values() if x["plan"])
    job.update("plans", "done", f"Plans chosen for {picked} of {len(asking)} concepts")
    return chosen


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
        self.owner: str | None = None  # the account it runs for, on a hosted Lemma
        self.lock = threading.Lock()
        self.created = time.time()
        self.updated = self.created
        self.on_change = None

    def changed(self):
        self.updated = time.time()
        if self.on_change:
            self.on_change(self)

    def step(self, sid: str, label: str, state: str = "waiting", detail: str = "", quiet: bool = False, **extra):
        """``quiet`` changes only what a live view sees, without saving: for progress ticks while a reply streams.
        ``extra`` adds fields to the step, such as "problems", the checks' findings while a concept is fixed."""
        with self.lock:
            for s in self.steps:
                if s["id"] == sid:
                    s.update(label=label or s["label"], state=state, detail=detail, **extra)
                    if state == "active":
                        s.setdefault("started", time.time())
                    if state in ("done", "failed"):
                        s["finished"] = time.time()
                    break
            else:
                self.steps.append({"id": sid, "label": label, "state": state, "detail": detail, **extra})
                if state == "active":
                    self.steps[-1]["started"] = time.time()
        if quiet:
            self.updated = time.time()
        else:
            self.changed()

    def update(self, sid: str, state: str, detail: str = "", quiet: bool = False, **extra):
        self.step(sid, "", state, detail, quiet, **extra)

    def snapshot(self) -> dict:
        with self.lock:
            concepts = [s for s in self.steps if s["label"].startswith("Concept ")]
            durations = [s["finished"] - s["started"] for s in concepts if s.get("finished") and s.get("started")]
            remaining = sum(s["state"] in ("waiting", "active") for s in concepts)
            # No invented initial ETA. The range spans parallel work through serial dependencies.
            estimate = sum(durations) / len(durations) * remaining if durations and remaining else None
            lesson = json.loads(json.dumps(self.lesson)) if self.lesson else None
            details = {s["id"]: s["detail"] for s in self.steps}
            for p in (lesson or {}).get("plan") or []:  # so the lesson can say how a concept still building is getting on
                p["detail"] = details.get(p["id"], "")
            return {
                "id": self.id,
                "kind": self.kind,
                "status": self.status,
                "now": time.time(),  # for elapsed times on the learner's clock, whatever the server's says
                "steps": [dict(s) for s in self.steps],
                "result": self.result,
                "error": self.error,
                "created": self.created,
                "updated": self.updated,
                "eta_seconds": [round(estimate / WORKERS * .7), round(estimate * 1.8)] if estimate else None,
                "lesson": lesson,
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
                if job.status == "running":
                    job.status = "cancelled" if job.cancelled.is_set() else "done"
        except (GenerationError, ProviderError) as e:
            with job.lock:
                job.status, job.error = ("cancelled" if job.cancelled.is_set() else "error"), str(e)
        except Exception as e:  # keep the server alive and tell the learner honestly
            with job.lock:
                job.status, job.error = "error", f"Unexpected error: {e.__class__.__name__}: {e} (error {logs.report(f'{job.kind} job', e)})"
        finally:
            job.changed()
            metrics.count(f"{job.kind}_{job.status}")  # e.g. build_done, build_error

    threading.Thread(target=run, daemon=True).start()
    return job


# ---------------------------------------------------------------- outline


def _relies_on(c: dict) -> list:
    """The concepts a concept relies on: the ones it needs and the one whose model it reuses."""
    deps = [n for n in c["needs"] if isinstance(n, str)] if isinstance(c.get("needs"), list) else []
    return deps + [c["builds_on"]] if isinstance(c.get("builds_on"), str) else deps


def order_outline(o):
    """Tidies a reviewed outline so every concept comes after the concepts it relies on.

    The learner may reorder, remove and restore concepts while reviewing. References to removed concepts are
    dropped, and a concept that ended up above something it relies on moves to just after it. Otherwise the
    learner's order is kept. A cycle is left in place for check_outline to report."""
    cs = o.get("concepts") if isinstance(o, dict) else None
    if not isinstance(cs, list) or not all(isinstance(c, dict) for c in cs):
        return o
    ids = {c.get("id") for c in cs}
    for c in cs:
        if isinstance(c.get("needs"), list):
            c["needs"] = [n for n in c["needs"] if n in ids and n != c.get("id")]
        if c.get("builds_on") is not None and c["builds_on"] not in ids:
            c["builds_on"] = None
    placed, rest = [], list(cs)
    while rest:
        done = {c.get("id") for c in placed}
        nxt = next((c for c in rest if all(d in done for d in _relies_on(c))), None)
        if nxt is None:
            placed += rest
            break
        placed.append(nxt)
        rest.remove(nxt)
    o["concepts"] = placed
    return o


def check_outline(o, source_text: str | None = None, require_needs: bool = False, subjects: list[dict] | None = None,
                  bridged: bool = False, brought: bool = False) -> list[str]:
    """``source_text`` checks the primer's quotes against the paper; None skips that. ``require_needs`` asks
    for every concept's "needs" (a fresh outline); outlines made before it existed may leave it out.
    ``subjects`` (a fresh outline for a question) checks "assumes", each concept's "subject", and that concepts
    teaching what to learn first come before the core ones. ``bridged`` (a question needing two fields) asks for
    exactly one concept marked "bridge". ``brought`` (sources the learner brought, no question) allows at most
    BROUGHT_BACKGROUND concepts on the listed subjects, so the sources' own content comes first."""
    problems = []
    if not isinstance(o, dict):
        return ["the reply must be a JSON object"]
    sources = L.source_map(source_text)
    norm = L.normalize_for_match(L.source_document(source_text)) if source_text is not None else None
    problems += [p.removeprefix("lesson.") for p in L.check_primer(o.get("primer"), norm, "primer")]
    if sources and isinstance(o.get("primer"), list):
        for i, page in enumerate(o["primer"]):
            if isinstance(page, dict):
                problems += L.check_attribution(page, sources, f"primer[{i}]")
    for key in ("title", "summary"):
        if not isinstance(o.get(key), str) or not o[key].strip():
            problems.append(f"needs '{key}'")
    # The finished lesson's intro limits (lesson.check_lesson), caught here before any concept is paid for.
    if isinstance(o.get("summary"), str) and len(o["summary"]) > 1500:
        problems.append(f"'summary' is too long ({len(o['summary'])} characters, limit 1500)")
    if isinstance(o.get("aha"), str) and len(o["aha"]) > 300:
        problems.append(f"'aha' is too long ({len(o['aha'])} characters): one sentence of at most 300")
    if not isinstance(o.get("source"), dict) or not isinstance(o["source"].get("title"), str):
        problems.append("needs source.title")
    cs = o.get("concepts")
    if not isinstance(o.get("aha"), str) or not o["aha"].strip():
        problems.append("needs 'aha': the paper's most surprising result in one sentence")
    if not isinstance(cs, list) or not 2 <= len(cs) <= 8:
        problems.append("needs 2–8 concepts")
        return problems
    ids = set()
    all_ids = {c.get("id") for c in cs if isinstance(c, dict)}
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
        if c.get("visual") not in L.OUTLINE_VISUALS:
            problems.append(f"concepts[{i}].visual must be one of {L.OUTLINE_VISUALS}")
        problems += _check_plans(c, f"concepts[{i}]", require_needs)
        b = c.get("builds_on")
        if b is not None:
            base = next((x for x in cs[:i] if isinstance(x, dict) and x.get("id") == b), None)
            if base is None:
                problems.append(f"concepts[{i}].builds_on must be the id of an earlier concept, or null")
            elif c.get("visual") == "none":
                problems.append(f"concepts[{i}] has no model, so it cannot build on another concept's model")
            elif base.get("visual") != c.get("visual"):
                problems.append(f"concepts[{i}] builds on '{b}', so it must use the same visual ('{base.get('visual')}')")
        needs = c.get("needs")
        if needs is None:
            if require_needs:
                problems.append(f"concepts[{i}] needs 'needs': the ids of earlier concepts it relies on ([] if none)")
        elif not isinstance(needs, list) or not all(isinstance(n, str) for n in needs):
            problems.append(f"concepts[{i}].needs must be a list of concept ids")
        else:
            earlier = {x.get("id") for x in cs[:i] if isinstance(x, dict)}
            for n in needs:
                if n in earlier:
                    continue
                if n in all_ids:
                    problems.append(f"concepts[{i}] relies on '{n}', which comes later; order the concepts so each comes after everything it relies on")
                else:
                    problems.append(f"concepts[{i}].needs names '{n}', which is not a concept in this outline")
    if isinstance(cs, list) and sum(1 for c in cs if isinstance(c, dict) and c.get("hard") is True) > 2:
        problems.append("mark at most two concepts as hard")
    if subjects is not None:
        problems += _check_subjects(o, [c for c in cs if isinstance(c, dict)], subjects)
        background = sum(1 for c in cs if isinstance(c, dict) and c.get("subject") is not None)
        if brought and background > BROUGHT_BACKGROUND:
            problems.append(f"{background} concepts teach what the sources build on; teach at most {BROUGHT_BACKGROUND} of them "
                            "and list the rest in \"assumes\", so the sources' own ideas come first")
        bridges = sum(1 for c in cs if isinstance(c, dict) and c.get("bridge") is True)
        if bridged and bridges != 1:
            problems.append(f"mark exactly one concept with \"bridge\": true, the one that connects the two fields (found {bridges})")
        elif not bridged and bridges:
            problems.append("this question needs one field, so no concept is a \"bridge\"; remove it")
    return problems


def _check_subjects(o: dict, cs: list[dict], subjects: list[dict]) -> list[str]:
    problems = []
    titles = {s["title"] for s in subjects}
    assumes = o.get("assumes")
    if not isinstance(assumes, list) or not all(isinstance(a, str) for a in assumes):
        problems.append("needs 'assumes': a list of the subjects the lesson takes as known ([] if none)")
    relation = {s["title"]: s["relation"] for s in subjects}
    first_core = next((i for i, c in enumerate(cs) if c.get("role") in ("core", "contribution")), len(cs))
    for i, c in enumerate(cs):
        subject = c.get("subject")
        if subject is not None and subject not in titles:
            problems.append(f"concepts[{i}].subject must be one of the listed subjects, written exactly as listed, or null")
        elif relation.get(subject) == "prerequisite" and i > first_core:
            problems.append(f"concepts[{i}] teaches '{subject}', which the learner needs first, so it must come before the core concepts")
    return problems


def _check_plans(c: dict, where: str, required: bool) -> list[str]:
    """2–3 candidate activity plans per concept (outlines made before plans existed may leave them out)."""
    plans = c.get("plans")
    if plans is None:
        return [f"{where} needs 'plans': 2–3 ways to teach it, each a list of activity block kinds"] if required else []
    if not isinstance(plans, list) or not 1 <= len(plans) <= 3:
        return [f"{where}.plans must list 2–3 plans"]
    problems = []
    for j, plan in enumerate(plans):
        w = f"{where}.plans[{j}]"
        blocks = plan.get("blocks") if isinstance(plan, dict) else None
        if not isinstance(blocks, list) or not 2 <= len(blocks) <= 12 or any(b not in L.ACTIVITY_KINDS for b in blocks):
            problems.append(f"{w}.blocks must be 2–12 activity kinds from {L.ACTIVITY_KINDS}")
            continue
        if c.get("visual") == "none" and any(b in L.MODEL_BLOCKS for b in blocks):
            problems.append(f"{w} uses model blocks, but the concept has no model")
        if not any(b in L.TEACHING_BLOCKS + ("watch", "walk") for b in blocks) or not any(b in L.RESPONSE_BLOCKS + ("goal", "predict", "check") for b in blocks):
            problems.append(f"{w} must teach and then ask the learner to do something")
        if not isinstance(plan.get("why"), str) or not plan["why"].strip() or len(plan["why"]) > 300:
            problems.append(f"{w} needs 'why': one line of at most 300 characters")
    return problems


PROGRESS_EVERY = 1.0  # seconds between progress ticks shown while a reply streams


def _written(chars: int) -> str:
    return f"{chars / 1000:.1f}k characters" if chars >= 1000 else f"{chars} characters"


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
            n = len(problems)
            doing = "Drafting" if attempt == 0 else f"Fixing {n} problem{'s' * (n != 1)} (attempt {attempt + 1} of {MAX_REPAIRS + 1})"
            # What the checks found stays on the step while it's fixed, so the learner can see why it's taking longer.
            found = [p.removeprefix("concept.") for p in problems[:5]]
            job.update(sid, "active", doing + " · waiting for the model", problems=found)
            last = [0.0]

            def progress(phase, chars, doing=doing, found=found):
                if time.monotonic() - last[0] >= PROGRESS_EVERY:
                    last[0] = time.monotonic()
                    job.update(sid, "active", f"{doing} · " + ("thinking" if phase == "thinking" and not chars else f"writing, {_written(chars)} so far"),
                               quiet=True, problems=found)

            reply = conv.send(message, cancelled=job.cancelled, on_progress=progress)
            if reply.stop_reason == "max_tokens":
                problems = ["the reply was cut off; make it more concise"]
            else:
                job.update(sid, "active", "Checking the quote, the model and every goal", problems=found)
                try:
                    obj = extract_json(reply.text)
                    problems = check(obj)
                except ValueError as e:
                    obj, problems = None, [f"the reply was not valid JSON ({e})"]
            if not problems:
                job.repairs = getattr(job, "repairs", {})
                job.repairs[sid] = attempt
                return obj, []
            message = REPAIR_TASK.format(problems="\n".join(f"- {p}" for p in problems[:25]))
        return obj, problems
    finally:
        conv.close()


ANSWERS_TIMEOUT = 20
ANSWERS = {"answers": "The lesson's path ends in an answer to the question the learner asked",
           "partly": "It answers part of the question, or a closely related one",
           "no": "It teaches something else and leaves the question unanswered"}


def answers_question(question: str, outline: dict) -> str:
    """Jev's reading of whether an outline answers the learner's question: "answers", "partly" or "no".
    Raises GenerationError when Jev can't say."""
    concepts = [c for c in outline.get("concepts") or [] if isinstance(c, dict)]
    state = {"question": question, "lesson": {"title": outline.get("title", ""), "summary": outline.get("summary", ""),
                                              "aha": outline.get("aha", ""),
                                              "concepts": [f"{c.get('title', '')}: {c.get('idea', '')}" for c in concepts]}}
    try:
        answer = jev.ask(state, {"answers": {"type": "choice", "criteria": ANSWERS,
                                             "instructions": "Does this lesson answer the question the learner asked?"}}, ANSWERS_TIMEOUT)["answers"]["choice"]
    except jev.JevError as e:
        raise GenerationError(f"Couldn't check the outline against your question just now ({e}). Retry in a moment.") from None
    except (KeyError, TypeError):
        raise GenerationError("Couldn't check the outline against your question just now. Retry in a moment.") from None
    if answer not in ANSWERS:
        raise GenerationError("Couldn't check the outline against your question just now. Retry in a moment.")
    return answer


def require_jev():
    try:
        jev.require()
    except jev.JevError as e:
        raise GenerationError(str(e)) from None


def make_outline(job: Job, provider: Provider, paper_text: str, level: str, search: dict | None = None) -> dict:
    """``search`` is the search a lesson was asked for from ({"query", "field", "subjects", "not_covered"}): the
    outline then has to answer its question, and says what it builds on and what it takes as known."""
    require_jev()  # before anything is paid for: the build that follows can't run without Jev
    if search and not search.get("query") and not (search.get("subjects") or search.get("not_covered")):
        search = None  # brought sources with nothing found that they build on: nothing to add to the task
    job.step("outline", "Reading your sources and proposing an outline", "active")
    task = OUTLINE_TASK.format(level=levels.describe(level), n_hint="three to seven")
    if L.source_map(paper_text):
        task += MULTI_SOURCE_TASK
    subjects = search_subjects(search, paper_text) if search else None
    if search:
        task += _question_task(search, subjects)

    def check(o):
        asked = bool(search and search.get("query"))
        problems = check_outline(o, paper_text, require_needs=True, subjects=subjects, bridged=asked and len(search.get("field") or []) == 2,
                                 brought=bool(search) and not asked)
        if asked and not problems and answers_question(search["query"], o) == "no":
            problems.append(f"the outline must answer the learner's question, «{search['query']}»: build the path to the "
                            "sources' answer to it, and make that answer the aha")
        return problems

    obj, problems = _ask_json(job, provider, paper_document(L.source_document(paper_text)), task, check, "outline")
    if problems:
        job.update("outline", "failed", "; ".join(problems[:3]))
        raise GenerationError("Couldn't produce a usable outline for this paper: " + "; ".join(problems[:3]))
    if search:
        obj["subjects"], obj["field"] = subjects, search.get("field")
        if search.get("query"):
            obj["question"] = search["query"]
    job.update("outline", "done", f"{len(obj['concepts'])} concepts proposed")
    return obj


# ---------------------------------------------------------------- concepts


def _outline_text(concepts: list[dict], current: str) -> str:
    lines = []
    for i, c in enumerate(concepts, 1):
        mark = "▶" if c["id"] == current else " "
        known = " (the learner already knows this; it is not in the lesson)" if c.get("known") else ""
        deps = [str(n) for n, x in enumerate(concepts, 1) if x["id"] in _relies_on(c)]
        after = f"; relies on {', '.join(deps)}" if deps else ""
        lines.append(f"{mark} {i}. {c['title']} [{c.get('role', 'core')}, {c.get('visual', '')}{after}]: {c['idea']}{known}")
    return "\n".join(lines)


def build_lesson(job: Job, provider: Provider, paper: dict, outline: dict, level: str, lesson_id: str | None = None) -> dict:
    """Builds concepts in parallel; each one is published to ``job.lesson`` as soon as it passes the checks."""
    require_jev()
    concepts = [c for c in outline["concepts"] if isinstance(c, dict)]
    todo = [c for c in concepts if not c.get("known")]
    if not todo:
        raise GenerationError("Every concept is marked as already known, so there is nothing to build.")
    src = outline.get("source") or {}
    lesson = {
        "version": 1,
        "id": lesson_id or uuid.uuid4().hex[:12],
        "title": outline.get("title") or paper.get("title") or "Lesson",
        "level": level,
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
            **({"assumes": [a for a in outline.get("assumes") or [] if isinstance(a, str)]} if isinstance(outline.get("subjects"), list) else {}),
            **({"question": outline["question"], "bridge": next((c["id"] for c in concepts if c.get("bridge") is True), None)}
               if isinstance(outline.get("question"), str) else {}),
        },
        "primer": outline.get("primer"),
        "provider": {"name": provider.name, "model": provider.model},
        "plan": [{"id": c["id"], "title": c["title"], "state": "waiting"} for c in todo],
        "concepts": [],
        "omitted": [],
    }
    sources = L.source_map(paper["text"])
    if sources:
        lesson["sources"] = [{k: v for k, v in s.items() if k != "text"} for s in sources.values()]
    choices = choose_plans(job, outline, todo, level)
    if choices:  # what Jev chose and from what, tied to this outline
        options = {c["id"]: c["plans"] for c in todo if c.get("plans")}
        lesson["activity_plans"] = [dict(x, options=options[cid]) for cid, x in choices.items()]
    job.lesson = lesson
    norm = L.normalize_for_match(L.source_document(paper["text"]))
    document = paper_document(L.source_document(paper["text"]))
    ready: dict[str, dict] = {}

    def publish():
        with job.lock:
            lesson["concepts"] = [ready[c["id"]] for c in todo if c["id"] in ready]

    def set_plan(cid, state):
        with job.lock:
            for p in lesson["plan"]:
                if p["id"] == cid:
                    p["state"] = state

    if len(todo) > 1:  # the concepts start together: cache the paper once first, or each writes its own copy
        try:
            provider.warm(system_prompt(), document)
        except ProviderError:
            pass  # only a saving; the concepts still build without it
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
        if lesson["intro"].get("question"):
            extra += f"\n- the learner asked: «{lesson['intro']['question']}». This concept's part in answering it: {c.get('subject') or c['idea']}"
        if lesson["intro"].get("assumes"):
            extra += ("\n- the lesson takes these as known, so use them with a one-line reminder at most, never teach them: "
                      + ", ".join(lesson["intro"]["assumes"]))
        if c["id"] == todo_ids[-1] and lesson["intro"].get("aha"):
            extra += "\n- this is the last concept: it must build to the lesson's aha, so the walkthrough ends on it: " + lesson["intro"]["aha"]
        no_model = c.get("visual") == "none"
        fields = dict(
            level=levels.describe(level),
            outline=_outline_text(concepts, c["id"]),
            title=c["title"],
            id=c["id"],
            idea=c["idea"],
            visual=f"{c.get('visual', '')} ({c.get('why', '')})" if not no_model else c.get("why", ""),
            plan_rule=plan_rule(choices.get(c["id"])),
            extra=extra,
        )
        if no_model:
            task = CONCEPT_TASK_NO_MODEL.format(**fields)
        else:
            task = CONCEPT_TASK.format(**fields, check_rule=(
                "this concept is marked hard: include one \"check\", preferably a model check" if c.get("hard") else
                "this concept is not marked hard: do not include a \"check\" key"))
        if sources:
            task += MULTI_SOURCE_TASK

        def check(obj):
            if isinstance(obj, dict):
                obj["id"] = c["id"]
                if not c.get("hard"):
                    obj.pop("check", None)  # quizzes are only for hard concepts
                    if isinstance(obj.get("activities"), list):
                        obj["activities"] = [a for a in obj["activities"] if not (isinstance(a, dict) and a.get("kind") == "check")]
                obj.pop("builds_on", None)
                if base:
                    obj["builds_on"] = base["id"]
            problems = list(L.check_concept(obj, norm, "concept"))
            if isinstance(obj, dict) and not obj.get("activities"):
                problems.append("concept: needs 'activities', the learner's screens in order (see ACTIVITIES)")
            if no_model and isinstance(obj, dict) and "model" in obj:
                problems.append("concept: this concept is taught without a model; remove 'model' and every model block")
            if sources and isinstance(obj, dict) and isinstance(obj.get("understand"), dict):
                problems += L.check_attribution(obj["understand"], sources, "concept.understand")
            if sources and isinstance(obj, dict):
                problems += L.check_activity_attribution(obj, sources, "concept")
            if base and isinstance(obj, dict) and not problems:
                problems = list(L.check_builds_on(obj, base, "concept"))
            if not problems:  # only a draft that passes the rules is worth Jev's judgement
                link = field_names(outline) if c.get("bridge") is True and len(outline.get("field") or []) == 2 else None
                problems = factcheck.check_concept(obj, paper["text"], todo_ids.index(c["id"]) + 1, link)
                passed_rules[0] = (obj, problems)
            return problems

        passed_rules = [None]  # the latest draft that passed every rule, with what Jev still flags in it
        try:
            obj, problems = _ask_json(job, provider, document, task, check, c["id"])
        except (ProviderError, GenerationError) as e:
            obj, problems = None, [str(e)]
        except jev.JevError as e:  # a concept Jev couldn't check is never shown unchecked
            obj, problems, passed_rules[0] = None, [f"the checks couldn't run on it ({e})"], None
        except Exception as e:  # a bug met by one concept leaves that concept out, not the whole lesson
            eid = logs.report(f"concept {c['id']}", e)
            obj, problems, passed_rules[0] = None, [f"an unexpected error while checking it ({e.__class__.__name__}, error {eid})"], None
        # Jev's flags ask for repairs but never leave a concept out: keep the last draft that passed the rules.
        if problems and passed_rules[0] and all(isinstance(p, factcheck.Flag) for p in passed_rules[0][1]):
            obj, problems = passed_rules[0]
        unresolved = [p for p in problems if isinstance(p, factcheck.Flag)]
        problems = [p for p in problems if not isinstance(p, factcheck.Flag)]
        if problems:
            set_plan(c["id"], "omitted")
            with job.lock:
                lesson["omitted"].append({"title": c["title"], "reason": problems[0]})
            job.update(c["id"], "failed", "Left out: it didn't pass the quality checks (" + problems[0][:160] + ")")
            return
        ready[c["id"]] = obj
        if unresolved:  # kept for whoever reviews the lesson; a learner isn't shown them
            with job.lock:
                lesson.setdefault("flags", []).extend({"concept": c["id"], "kind": f.kind, "certainty": f.certainty} for f in unresolved)
        set_plan(c["id"], "ready")
        publish()
        fixes = getattr(job, "repairs", {}).get(c["id"], len(unresolved) and MAX_REPAIRS)
        flagged = (f" The checker flagged {len(unresolved)} possible problem{'s' * (len(unresolved) != 1)} it couldn't confirm,"
                   " so read this concept against its source." if unresolved else "")
        ready_text = "Ready" + (f", after {fixes} round{'s' * (fixes != 1)} of fixes" if fixes else "")
        job.update(c["id"], "done", ready_text + ("." + flagged if flagged else ""), problems=[])

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
