"""Judges one lesson with TypeSafe's Jev, using the questions in questions.py.

Jev reads at most about 32k tokens per question, so it never gets the whole paper: each question gets the
part of the lesson it is about and the parts of the paper that bear on it (the quote in its context, the
passages that best match a concept, or the paper's opening and closing). What Jev saw is kept with every
answer, so a person reviewing a flag sees exactly what was judged.
"""

from __future__ import annotations

import time

from lemma import jev
from lemma import lesson as L
from lemma.factcheck import concept_evidence, concept_text, edges, has_marked_answer, lesson_text, quote_context  # noqa: F401

import questions as Q

TIMEOUT = 90  # a whole concept's questions in one request; the eval can wait, search can't
RETRIES = 5


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
            sure = [v for v in vs if v["p"] >= Q.CONFIRM_AT]
            certainty = round(max(v["p"] for v in vs), 3)
            if len(sure) * 2 > len(vs):
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
