"""Judges one lesson with TypeSafe's Jev, using the questions in questions.py.

Jev reads at most about 32k tokens per question, so it never gets the whole paper: each question gets the
part of the lesson it is about and the parts of the paper that bear on it (the quote in its context, the
passages that best match a concept, or the paper's opening and closing). What Jev saw is kept with every
answer, so a person reviewing a flag sees exactly what was judged.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter

from lemma import jev
from lemma import lesson as L

import questions as Q

TIMEOUT = 90  # a whole concept's questions in one request; the eval can wait, search can't
RETRIES = 5
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
    if m.get("note"):
        out.append(f"  NOTE: {m['note']}")
    return out


def concept_text(c: dict, n: int) -> str:
    """One concept in plain text: what a learner reads, plus the model's formulas in readable form."""
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
        out.append(f"GOAL {i}: {g.get('text', '')} (reached when {g.get('when', '')})")
        out += [f"  hint {j}: {h}" for j, h in enumerate(g.get("hints") or [], 1)]
    out += _exercise("USE IT", c.get("predict"))
    out += _exercise("CHECK", c.get("check"))
    conn = c.get("connect") or {}
    if conn.get("equation"):
        out.append("EQUATION: " + " ".join(str(p.get("text", "")) for p in conn["equation"]) + (f" ({conn.get('caption', '')})" if conn.get("caption") else ""))
    if c.get("recap"):
        out.append(f"RECAP: {c['recap']}")
    return "\n".join(out)


def _exercise(name: str, x: dict | None) -> list[str]:
    if not x:
        return []
    out = [f"{name}: {x.get('question') or x.get('task') or x.get('statement') or ''}"]
    for i, o in enumerate(x.get("options") or []):
        mark = " <- marked correct" if x.get("answer") == i or (isinstance(x.get("answer"), list) and i in x["answer"]) else ""
        why = (x.get("why") or [None] * (i + 1))[i] if i < len(x.get("why") or []) else None
        out.append(f"  option {i + 1}: {o}{mark}" + (f" (why: {why})" if why else ""))
    if x.get("options") is None and "answer" in x:
        out.append(f"  marked answer: {x['answer']}")
    if x.get("when"):
        out.append(f"  reached when {x['when']}")
    return out


def has_marked_answer(x: dict | None) -> bool:
    """An exercise whose correct answer is written down (a model-state check is proved by the lesson checks instead)."""
    return bool(x) and "answer" in x


def lesson_text(lesson: dict) -> str:
    intro, primer = lesson.get("intro") or {}, lesson.get("primer") or []
    out = [f"LESSON: {lesson.get('title', '')}", f"AUDIENCE: {lesson.get('audience', '')}", f"SUMMARY: {intro.get('summary', '')}"]
    out += [f"BACKGROUND: {b}" for b in intro.get("background") or []]
    if intro.get("aha"):
        out.append(f"THE BIG SURPRISE: {intro['aha']}")
    out += ["THE PAPER IN BRIEF:"] + [f"  {p.get('heading', '')}: {p.get('body', '')}" + (f" Quote: \"{p['quote']}\"" if p.get("quote") else "") for p in primer]
    out += [concept_text(c, i) for i, c in enumerate(lesson.get("concepts") or [], 1)]
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


# ---------------------------------------------------------------- asking


def _ask(state: str, questions: dict) -> dict:
    """Jev's answers, waiting and retrying when it is busy or rate-limited."""
    for attempt in range(RETRIES):
        try:
            return jev.ask(state, questions, TIMEOUT)
        except jev.JevError as e:
            if attempt == RETRIES - 1 or not any(s in str(e) for s in ("429", "529", "50", "Timeout", "URLError")):
                raise
            time.sleep(2 ** attempt * 3)
    raise jev.JevError("unreachable")


def _choice(key_ask: str) -> dict:
    return {"type": "choice", "instructions": key_ask, "criteria": Q.ANSWERS}


def _noul(key_ask: str) -> dict:
    return {"type": "noul", "instructions": key_ask}


def judge_lesson(lesson: dict, paper: str) -> dict:
    """Every question, asked through every lens, with the text each was asked about. Raises jev.JevError."""
    paper = L.source_document(paper)
    requests = []

    def run(name: str, state: str, questions: dict):
        if questions:
            requests.append({"name": name, "state": state, "questions": questions, "answers": _ask(state, questions)})

    for i, c in enumerate(lesson.get("concepts") or [], 1):
        cid = c["id"]
        text, evidence = concept_text(c, i), concept_evidence(c, paper)
        with_paper, teaching = {}, {}
        for lens, lead in Q.LENSES.items():
            for item, spec in Q.PART_A.items():
                (with_paper if spec["paper"] else teaching)[f"{cid}|A|{item}|{lens}"] = _choice(lead + spec["ask"])
            for kind, ask in Q.CRITICAL.items():
                with_paper[f"{cid}|C|{kind}|{lens}"] = _noul(lead + ask)
            for ex in ("predict", "check"):
                if has_marked_answer(c.get(ex)):
                    label = "the 'Use it' question" if ex == "predict" else "the check"
                    with_paper[f"{cid}|C|wrong_answer:{ex}|{lens}"] = _noul(f"{lead}Look at {label}. {Q.WRONG_ANSWER}")
        run(f"{cid} with the paper", f"{text}\n\n=== FROM THE PAPER ===\n\n{evidence}", with_paper)
        run(f"{cid} as taught", text, teaching)

    whole, opening = lesson_text(lesson), edges(paper)
    with_paper, teaching = {}, {}
    for lens, lead in Q.LENSES.items():
        for dim, spec in Q.PART_B.items():
            for j, check in enumerate(spec["checks"]):
                (with_paper if spec["paper"] else teaching)[f"lesson|B|{dim}.{j}|{lens}"] = _noul(lead + check)
    run("lesson with the paper", f"{whole}\n\n=== THE PAPER'S OPENING AND CLOSING ===\n\n{opening}", with_paper)
    run("lesson as taught", whole, teaching)
    model = next((r["answers"].get("_model") for r in requests), jev.MODEL)
    return {"questions_version": Q.VERSION, "model": model, "requests": requests}


# ---------------------------------------------------------------- combining the three lenses


def _votes(judged: dict) -> dict:
    """{(target, part, item): [{lens, answer, p, request}]} from every answer Jev gave."""
    out = {}
    for ri, r in enumerate(judged["requests"]):
        for key, a in r["answers"].items():
            if key == "_model":
                continue
            target, part, item, lens = key.split("|")
            if a.get("type") == "noul" or "noul" in a:
                p = float(a.get("noul", 0))
                vote = {"lens": lens, "answer": "yes" if p >= .5 else "no", "p": round(p, 3)}
            else:
                probs = a.get("probabilities") or {}
                vote = {"lens": lens, "answer": a.get("choice"), "p": round(float(probs.get(a.get("choice"), 0)), 3)}
            out.setdefault((target, part, item), []).append({**vote, "request": ri})
    return out


def majority(answers: list[str]) -> tuple[str | None, bool]:
    """The answer most lenses gave, ignoring cannot_judge, and whether it needs a person to look."""
    votes = [a for a in answers if a in ("yes", "partly", "no")]
    if not votes:
        return None, bool(answers)
    best = max(set(votes), key=votes.count)
    if votes.count(best) * 2 > len(votes):
        return best, len(set(votes)) > 1  # a split vote goes to a person even when there's a majority
    return "partly", True


def combine(lesson: dict, judged: dict) -> dict:
    """Part A answers, Part B scores, critical errors, the verdict and what needs a person, from Jev's answers."""
    votes = _votes(judged)
    concepts = [c["id"] for c in lesson.get("concepts") or []]
    items, review, critical, failed = {}, [], [], []

    def flag(target, part, item, why, certainty):
        vs = votes[(target, part, item)]
        review.append({"what": f"{target} {item}", "why": why, "certainty": certainty, "votes": [{k: v[k] for k in ("lens", "answer", "p")} for v in vs],
                       "question": judged["requests"][vs[0]["request"]]["questions"][f"{target}|{part}|{item}|{vs[0]['lens']}"]["instructions"],
                       "state": judged["requests"][vs[0]["request"]]["state"]})

    for cid in concepts:
        for item in Q.PART_A:
            vs = votes.get((cid, "A", item), [])
            answer, split = majority([v["answer"] for v in vs])
            items[f"{cid}.{item}"] = answer
            certainty = round(sum(v["p"] for v in vs if v["answer"] == answer) / max(1, len(vs)), 3)
            if split:
                flag(cid, "A", item, "the three lenses disagree", certainty)
            if answer in ("partly", "no"):
                failed.append({"what": f"{cid} {item} ({Q.PART_A[item]['name']}): {answer}", "certainty": certainty, "item": item, "answer": answer})
        for (target, part, kind), vs in votes.items():
            if target != cid or part != "C":
                continue
            yes = [v for v in vs if v["answer"] == "yes"]
            certainty = round(max(v["p"] for v in vs), 3)
            if len(yes) * 2 > len(vs):
                critical.append({"type": kind.split(":")[0], "where": cid, "exercise": kind.split(":")[1] if ":" in kind else None,
                                 "certainty": certainty, "votes": [{k: v[k] for k in ("lens", "answer", "p")} for v in vs]})
                flag(cid, "C", kind, "a critical error, confirmed by most lenses", certainty)
            elif yes:
                flag(cid, "C", kind, f"a possible critical error, seen by {', '.join(v['lens'] for v in yes)}", certainty)

    scales = {}
    for dim, spec in Q.PART_B.items():
        passed = 0
        for j, check in enumerate(spec["checks"]):
            vs = votes.get(("lesson", "B", f"{dim}.{j}"), [])
            answer, split = majority([v["answer"] for v in vs])
            passed += answer == "yes"
            if split:
                flag("lesson", "B", f"{dim}.{j}", "the three lenses disagree", round(max((v["p"] for v in vs), default=0), 3))
            if answer != "yes":
                failed.append({"what": f"{dim} ({spec['name']}): {check}", "certainty": round(1 - min((v["p"] for v in vs), default=1), 3), "item": dim, "answer": "no"})
        scales[dim] = round(passed / len(spec["checks"]), 2)

    verdict = verdict_for(items, scales, critical)
    failed.sort(key=lambda f: -f["certainty"])
    review.sort(key=lambda r: (not r["why"].startswith(("a critical", "a possible")), -r["certainty"]))
    return {"items": items, "scales": scales, "critical_errors": critical, "verdict": verdict,
            "top_problems": [f["what"] for f in failed[:3]], "needs_review": review}


def verdict_for(items: dict, scales: dict, critical: list) -> str:
    """dont_ship: a confirmed critical error, or a quote or model judged plainly wrong. ship_with_fixes: anything else failed."""
    if critical or any(a == "no" and k.endswith((".A1", ".A2")) for k, a in items.items()):
        return "dont_ship"
    if any(a in ("partly", "no") for a in items.values()) or any(s < Q.B_PASS for s in scales.values()):
        return "ship_with_fixes"
    return "ship"
