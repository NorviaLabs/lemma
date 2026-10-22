"""Checks a drafted concept for critical errors with TypeSafe's Jev, before a learner sees it.

The build's quality checks (lesson.py) prove what rules can prove: quotes appear word for word, models give finite
numbers, goals are reachable. They can't tell whether a claim is true to the paper. Jev can judge that, from the
concept in readable form (with a table of what its model does) and the parts of the paper it is about. A confident
flag becomes a repair request to the model that wrote the concept; it never removes a concept on its own.

Only the error kinds the eval showed Jev confirms reliably are asked during a build (BUILD_KINDS). The eval
(eval/jev_judge.py) shows Jev the same text and asks the same questions, plus the ones not yet reliable enough here.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter

from . import jev, levels
from . import lesson as L

TIMEOUT = 30
WINDOW = 2000  # characters of the paper on each side of a quote
PASSAGE = 1500  # characters per paper passage
PASSAGES = 3  # passages matched to each concept
EDGE = 4000  # characters of the paper's opening and of its closing, for whole-lesson questions
STOP_WORDS = set("that this with from have which their there were been than then they them these those when what where while also into "
                 "only more most such each other some your about would could should because between does doesn".split())



# ---------------------------------------------------------------- the lesson, as a reader sees it


def _model(m: dict) -> list[str]:
    out = [f"MODEL: {m.get('title', '')}"]
    for c in m.get("controls") or []:
        rng = f"from {c.get('min')} to {c.get('max')}" if c.get("kind", "slider") == "slider" else c.get("kind", "")
        out.append(f"  control {c['id']} = {c.get('label', '')} ({rng}, starts at {c.get('default')})")
    for o in m.get("outputs") or []:
        out.append(f"  output {o['id']} = {o.get('label', '')}: computed as {o.get('expr', '')}")
    out += _behaviour(m)
    if m.get("note"):
        out.append(f"  NOTE: {m['note']}")
    return out


def _shown(o: dict, v) -> str:
    """An output's value as the learner sees it: scaled, rounded, with its unit."""
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        return "undefined"
    v = v * float(o.get("scale", 1) or 1)
    d = o.get("decimals")
    text = f"{v:.{int(d)}f}" if isinstance(d, int) else f"{v:.4g}"
    return text + (o.get("unit") or "")


def _behaviour(m: dict) -> list[str]:
    """What the model actually does: each slider at its low, middle and high end, the others at their defaults.
    A reversed direction or a wrong growth rate shows in these numbers even when the formula hides it."""
    outputs = [o for o in m.get("outputs") or [] if o.get("id")]
    lines = []
    for c in m.get("controls") or []:
        if c.get("kind", "slider") != "slider" or not isinstance(c.get("min"), (int, float)) or not isinstance(c.get("max"), (int, float)):
            continue
        lo, hi = float(c["min"]), float(c["max"])
        try:
            runs = [L.compute(m, {c["id"]: v}) for v in (lo, (lo + hi) / 2, hi)]
        except Exception:  # a model the checks would reject; the formula is still shown above
            continue
        moved = [f"{o.get('label') or o['id']} {' -> '.join(_shown(o, r.get(o['id'])) for r in runs)}" for o in outputs
                 if len({_shown(o, r.get(o["id"])) for r in runs}) > 1]
        if moved:
            lines.append(f"  raising {c['id']} through {lo:g}, {(lo + hi) / 2:g}, {hi:g} moves: " + "; ".join(moved))
    return (["  WHAT THE MODEL DOES (others at their defaults):"] + lines) if lines else []


def concept_text(c: dict, n: int, conditions: bool = True) -> str:
    """One concept in plain text: what a learner reads, plus the model's formulas in readable form. `conditions`
    shows each goal's and check's success condition, which a learner never sees; judging the teaching leaves it out."""
    out = [f"CONCEPT {n}: {c.get('title', '')}", f"IDEA: {c.get('idea', '')}"]
    out += _model(c.get("model") or {})
    steps = (c.get("animation") or {}).get("steps") or []
    out += ["TOUR:"] + [f"  - {s.get('say', '')}" for s in steps if s.get("say")]
    u = c.get("understand") or {}
    out += [f"EXPLANATION: {u.get('explanation', '')}", f"QUOTE ({u.get('quote_where', '')}): \"{u.get('quote', '')}\""]
    out += ["WALKTHROUGH:"] + [f"  - {s.get('say', '')}" for s in (u.get("walkthrough") or {}).get("steps") or [] if s.get("say")]
    for t in c.get("terms") or []:
        out.append(f"TERM: {t.get('term', '')}: {t.get('definition', t.get('def', ''))}")
    for i, g in enumerate((c.get("explore") or {}).get("goals") or [], 1):
        out.append(f"GOAL {i}: {g.get('text', '')}" + (f" (reached when {g.get('when', '')})" if conditions else ""))
        out += [f"  hint {j}: {h}" for j, h in enumerate(g.get("hints") or [], 1)]
    out += _exercise("USE IT", c.get("predict"), conditions)
    out += _exercise("CHECK", c.get("check"), conditions)
    conn = c.get("connect") or {}
    if conn.get("equation"):
        out.append("EQUATION: " + " ".join(str(p.get("text", "")) for p in conn["equation"]) + (f" ({conn.get('caption', '')})" if conn.get("caption") else ""))
    for activity in c.get("activities") or []:
        out += _activity(activity)
    if c.get("recap"):
        out.append(f"RECAP: {c['recap']}")
    return "\n".join(out)


def _activity(a: dict) -> list[str]:
    """A teaching or response block as the learner meets it, with its marked answers, so Jev can judge it."""
    kind = a.get("kind")
    tag = " (a labelled hypothetical case)" if a.get("hypothetical") else ""
    if kind == "explain":
        return [f"TEACHING: {a['text']}"] if a.get("text") else []
    if kind == "worked":
        return [f"WORKED EXAMPLE{tag}: {a.get('title', '')}"] + [f"  step {i}: {s.get('text', '')}" + (f" -> {s['result']}" if s.get("result") else "")
                                                                for i, s in enumerate(a.get("steps") or [], 1)] + [f"  takeaway: {a.get('takeaway', '')}"]
    if kind == "stages":
        return [f"STAGED EVIDENCE{tag}: {a.get('prompt', '')}"] + [f"  stage {i} ({s.get('label', '')}): {s.get('text', '')}" for i, s in enumerate(a.get("stages") or [], 1)] + [f"  takeaway: {a.get('takeaway', '')}"]
    if kind == "compare":
        return [f"COMPARISON{tag}: {a.get('prompt', '')}"] + [f"  case {c.get('label', '')}: " + (c.get("text") or "") + (f" (model set to {json.dumps(c['values'])})" if c.get("values") else "")
                                                               for c in a.get("cases") or []] + [f"  takeaway: {a.get('takeaway', '')}"]
    if kind == "choice":
        answers = a.get("answers") if a.get("multi") else [a.get("answer")]
        out = [f"ACTIVITY ({a.get('mode')}){tag}: {a.get('question', '')}"]
        for i, option in enumerate(a.get("options") or []):
            marked = " [answer]" if a.get("mode") == "determinate" and i in (answers or []) else ""
            out.append(f"  {i + 1}. {option.get('text', '')}{marked}: {option.get('feedback', '')}")
        return out
    if kind == "match":
        return [f"MATCHING{tag}: {a.get('prompt', '')}"] + [f"  {p.get('text', '')} -> {p.get('target', '')} ({p.get('feedback', '')})" for p in a.get("pairs") or []]
    if kind == "order":
        return [f"ORDERING{tag}: {a.get('prompt', '')}", "  correct order: " + " -> ".join(a.get("items") or []), f"  why: {a.get('explanation', '')}"]
    if kind == "trace":
        names = {n.get("id"): n.get("label", "") for n in a.get("nodes") or []}
        return [f"TRACING{tag}: {a.get('prompt', '')}", "  links: " + "; ".join(f"{names.get(e.get('from'))} -> {names.get(e.get('to'))}" for e in a.get("edges") or []),
                "  marked answer: " + " -> ".join(names.get(x, x) for x in a.get("answer") or []), f"  why: {a.get('explanation', '')}"]
    if kind == "passage":
        return [f"SUPPORTING PASSAGE: {a.get('question', '')}"] + [f"  {i + 1}. \"{o.get('quote', '')}\"" + (" [answer]" if a.get("answer") == i else "") + f": {o.get('feedback', '')}"
                                                                  for i, o in enumerate(a.get("options") or [])]
    if kind == "estimate":
        return [f"ESTIMATE{tag}: {a.get('question', '')}", f"  marked answer: {a.get('answer')} ± {a.get('tolerance')} {a.get('unit', '')}", f"  why: {a.get('explanation', '')}"]
    if kind in ("sort", "construction", "inheritance"):
        return ["INTERACTIVE TEACHING: " + json.dumps(a, ensure_ascii=False)]
    return []


def _exercise(name: str, x: dict | None, conditions: bool = True) -> list[str]:
    if not x:
        return []
    out = [f"{name}: {x.get('question') or x.get('task') or x.get('statement') or ''}"]
    for i, o in enumerate(x.get("options") or []):
        mark = " <- marked correct" if x.get("answer") == i or (isinstance(x.get("answer"), list) and i in x["answer"]) else ""
        why = (x.get("why") or [None] * (i + 1))[i] if i < len(x.get("why") or []) else None
        out.append(f"  option {i + 1}: {o}{mark}" + (f" (why: {why})" if why else ""))
    if x.get("options") is None and "answer" in x:
        out.append(f"  marked answer: {x['answer']}")
    if x.get("when") and conditions:
        out.append(f"  reached when {x['when']}")
    return out


def has_marked_answer(x: dict | None) -> bool:
    """An exercise whose correct answer is written down (a model-state check is proved by the lesson checks instead)."""
    return bool(x) and "answer" in x


def lesson_text(lesson: dict, conditions: bool = True) -> str:
    intro, primer = lesson.get("intro") or {}, lesson.get("primer") or []
    # Lessons saved before levels name an audience instead.
    learner = f"LEVEL: {levels.describe(lesson['level'])}" if lesson.get("level") else f"AUDIENCE: {lesson.get('audience', '')}"
    out = [f"LESSON: {lesson.get('title', '')}", learner, f"SUMMARY: {intro.get('summary', '')}"]
    out += [f"BACKGROUND: {b}" for b in intro.get("background") or []]
    if intro.get("aha"):
        out.append(f"THE BIG SURPRISE: {intro['aha']}")
    out += ["THE PAPER IN BRIEF:"] + [f"  {p.get('heading', '')}: {p.get('body', '')}" + (f" Quote: \"{p['quote']}\"" if p.get("quote") else "") for p in primer]
    out += [concept_text(c, i, conditions) for i, c in enumerate(lesson.get("concepts") or [], 1)]
    omitted = lesson.get("omitted") or []
    out.append("OMITTED CONCEPTS: " + ("; ".join(str(o.get("title", o) if isinstance(o, dict) else o) for o in omitted) if omitted else "none"))
    return "\n\n".join(out)


# ---------------------------------------------------------------- the paper, in the parts that matter


def _norm(text: str) -> tuple[str, list[int]]:
    """Lowercased text with runs of spaces collapsed, and where each character came from."""
    out, where, space = [], [], False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not space:
                out.append(" ")
                where.append(i)
            space = True
        else:
            out.append(ch.lower())
            where.append(i)
            space = False
    return "".join(out), where


def quote_context(paper: str, quote: str) -> str:
    """The paper around a quote. The checks proved the quote is there, so its place can be found."""
    norm, where = _norm(paper)
    q = _norm(quote)[0].strip()
    for size in (len(q), 120, 60, 30):  # the whole quote, then shorter openings of it
        at = norm.find(q[:size]) if q else -1
        if at >= 0:
            start, end = where[at], where[min(at + len(q), len(where) - 1)]
            return paper[max(0, start - WINDOW):end + WINDOW]
    return ""


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9_]{3,}", text.lower()) if w not in STOP_WORDS]


def passages(paper: str, about: str, n: int = PASSAGES) -> list[str]:
    """The paper passages that share the most (rarer) words with `about`, in the paper's order."""
    chunks, at = [], 0
    while at < len(paper):
        end = paper.rfind("\n", at + PASSAGE // 2, at + PASSAGE)
        end = end if end > at else at + PASSAGE
        chunks.append(paper[at:end])
        at = end
    seen = [set(_words(c)) for c in chunks]
    df = Counter(w for s in seen for w in s)
    want = set(_words(about))
    score = [sum(math.log(len(chunks) / df[w]) for w in want & s) for s in seen]
    best = sorted(sorted(range(len(chunks)), key=lambda i: -score[i])[:n])
    return [chunks[i].strip() for i in best if score[i] > 0]


def edges(paper: str) -> str:
    """The paper's opening (title, abstract, introduction) and the end of its body (conclusion)."""
    refs = max(paper.rfind("\nReferences"), paper.rfind("\nREFERENCES"), paper.rfind("\nBibliography"))
    body = paper[:refs] if refs > len(paper) // 2 else paper
    if len(body) <= 2 * EDGE:
        return body
    return body[:EDGE] + "\n[...]\n" + body[-EDGE:]


def concept_evidence(c: dict, paper: str) -> str:
    u = c.get("understand") or {}
    m = c.get("model") or {}
    about = " ".join([c.get("title", ""), c.get("idea", ""), u.get("explanation", "")]
                     + [x.get("label", "") for x in (m.get("controls") or []) + (m.get("outputs") or [])])
    parts = [f"THE QUOTE IN ITS CONTEXT:\n{quote_context(paper, u.get('quote', '')) or '(the quote could not be located)'}"]
    parts += [f"PAPER PASSAGE {i}:\n{p}" for i, p in enumerate(passages(paper, about), 1)]
    return "\n\n".join(parts)


# ---------------------------------------------------------------- the questions

# Each question is asked through three lenses; most must answer yes, at least CONFIRM_AT surely, to confirm an error.
LENSES = {
    "referee": "You are a strict referee checking a lesson against the research it teaches. ",
    "teacher": "You are an experienced teacher of this subject, reviewing a lesson before students use it. ",
    "newcomer": "You are a curious adult new to this field, working through this lesson. ",
}
# On the 2026-10-18 eval pilot, 0.7 kept 14 of 25 planted errors and no yes on the unmodified lessons; at 0.5 the
# unmodified lessons got 11 of 140.
CONFIRM_AT = 0.7
CRITICAL = {  # yes = an error was found
    "wrong_claim": "Does anything in this concept (explanation, narration, hints, note, recap) state that the paper found or argued something "
                   "the paper excerpt doesn't support, or teach something it contradicts?",
    "reversed_model": "Look at WHAT THE MODEL DOES: how each output moves as each control rises. Does any of it go against what the paper "
                      "excerpt says: an effect in the wrong direction, the wrong growth rate (for example logarithmic where the paper says "
                      "linear) or the wrong rule?",
    "fabricated_finding": "Does the concept state that the paper found or reported a specific number or result that the paper excerpt "
                          "doesn't contain? Example values in a teaching model, and numbers the model's note calls illustrative, are not "
                          "findings: answer no for those.",
    "misleading_quote": "Read in its context in the paper excerpt, does the quote say something different from what the concept uses it for?",
}
WRONG_ANSWER = "Is the answer this exercise marks as correct actually wrong, given the model and what the concept teaches?"
# Asked only of the concept that connects a question's two fields ("bridge" in the outline).
UNSUPPORTED_LINK = ("Does this concept state a connection between {link} that the paper excerpt doesn't support, without saying "
                    "plainly that the sources don't establish it?")
# The kinds the eval confirmed on 4 or 5 of 5 planted errors; reversed_model and misleading_quote weren't reliable yet.
BUILD_KINDS = ("wrong_claim", "fabricated_finding", "wrong_answer")

# What the model that wrote the concept is told when a kind is confirmed. Jev gives no reasons, so each says where
# to look and what a fix looks like.
REPAIR = {
    "wrong_claim": "an independent check is fairly sure something in this concept says the paper found or argued what it doesn't. "
                   "Check every statement about the paper (explanation, narration, hints, note, recap) against the paper's text, and "
                   "correct or remove any it doesn't support.",
    "fabricated_finding": "an independent check is fairly sure this concept presents a number or result as the paper's that the paper "
                          "doesn't contain. Find it; quote the paper's real figure, or say plainly that it is an illustrative value of the "
                          "teaching model, not a finding.",
    "wrong_answer": "an independent check is fairly sure the answer marked correct in this concept's {exercise} is wrong. Recheck it "
                    "against the model and the explanation, and fix the marked answer and its reasons, or the question.",
    "unsupported_link": "an independent check is fairly sure this concept states the connection between the question's two fields "
                        "without a source for it. Quote the passage that states the link, or say plainly that these sources don't "
                        "establish it.",
}


class Flag(str):
    """A repair request from Jev: sent to the model like any problem, but never a reason to leave a concept out."""

    def __new__(cls, text: str, kind: str, certainty: float):
        s = super().__new__(cls, text)
        s.kind, s.certainty = kind, certainty
        return s


def questions_for(c: dict, kinds=BUILD_KINDS, link: str | None = None) -> dict:
    """The yes/no questions about one concept, keyed kind|lens (wrong answers: wrong_answer:predict|lens). ``link``
    names the two fields a bridge concept connects."""
    qs = {}
    for lens, lead in LENSES.items():
        if link:
            qs[f"unsupported_link|{lens}"] = {"type": "noul", "instructions": lead + UNSUPPORTED_LINK.format(link=link)}
        for kind in kinds:
            if kind != "wrong_answer":
                qs[f"{kind}|{lens}"] = {"type": "noul", "instructions": lead + CRITICAL[kind]}
        if "wrong_answer" in kinds:
            for ex in ("predict", "check"):
                if has_marked_answer(c.get(ex)):
                    label = "the 'Use it' question" if ex == "predict" else "the check"
                    qs[f"wrong_answer:{ex}|{lens}"] = {"type": "noul", "instructions": f"{lead}Look at {label}. {WRONG_ANSWER}"}
    return qs


def confirmed(answers: dict) -> dict:
    """{kind: certainty} for each kind most lenses answered yes at CONFIRM_AT or more."""
    by_kind = {}
    for key, a in answers.items():
        if "|" in key and isinstance(a, dict):
            by_kind.setdefault(key.split("|")[0], []).append(float(a.get("noul", 0)))
    return {k: round(max(ps), 3) for k, ps in by_kind.items() if sum(p >= CONFIRM_AT for p in ps) * 2 > len(ps)}


def check_concept(c: dict, paper: str, n: int = 1, link: str | None = None) -> list[Flag]:
    """Repair requests for the critical errors Jev confirms in a drafted concept. Raises jev.JevError when Jev
    can't check it, so an unchecked concept is never shown."""
    if not isinstance(c, dict):
        return []
    paper = L.source_document(paper)
    state = f"{concept_text(c, n)}\n\n=== FROM THE PAPER ===\n\n{concept_evidence(c, paper)}"
    found = confirmed(jev.ask(state, questions_for(c, link=link), TIMEOUT))
    flags = []
    for kind, certainty in found.items():
        base, _, exercise = kind.partition(":")
        text = REPAIR[base].format(exercise="'Use it' question" if exercise == "predict" else "check")
        flags.append(Flag(f"concept: {text}", base, certainty))
    return flags
