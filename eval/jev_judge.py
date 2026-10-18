"""Judges one lesson with TypeSafe's Jev, using the questions in questions.py.

Jev reads at most about 32k tokens per question, so it never gets the whole paper: each question gets the
part of the lesson it is about and the parts of the paper that bear on it (the quote in its context, the
passages that best match a concept, or the paper's opening and closing). What Jev saw is kept with every
answer, so a person reviewing a flag sees exactly what was judged.
"""

from __future__ import annotations

import math
import re

from lemma import jev
from lemma import lesson as L
from lemma.factcheck import concept_evidence, concept_text, edges, lesson_text, quote_context  # noqa: F401  (quote_context: for tests)

import questions as Q

NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])\d+\.\d+|(?<![\w.])\d{2,}")
NUMBER_WINDOW = 300  # characters of the paper on each side of a number it gives
NUMBERS_SHOWN = 8


def number_passages(text: str, paper: str) -> str:
    """Where the paper gives the numbers a text uses. The matched excerpts can miss a section that reports a number,
    which would make a real figure look invented; this shows each one in its place. Numbers the paper doesn't contain
    are left for the question to judge."""
    words = {w for w in re.findall(r"[a-z]{4,}", text.lower())}
    out, seen = [], set()
    for n in NUMBER.findall(text):
        if n in seen or len(out) >= NUMBERS_SHOWN:
            continue
        seen.add(n)
        at = _best_spot(n, words, paper)
        if at is not None:
            out.append(f"[{n}] ..." + paper[max(0, at - NUMBER_WINDOW):at + len(n) + NUMBER_WINDOW].replace("\n", " ") + "...")
    return ("\n\n=== WHERE THE PAPER GIVES THESE NUMBERS ===\n\n" + "\n\n".join(out)) if out else ""

LESSON_PAPER = 24000  # characters of paper the lesson-level questions see, shared between sources
PRIMER_CONTEXT = 1500  # characters around each quote in the paper in brief


def _ends(text: str, budget: int) -> str:
    """A text's opening and the end of its body (before any reference list), within a budget."""
    refs = max(text.rfind("\nReferences"), text.rfind("\nREFERENCES"), text.rfind("\nBibliography"))
    body = text[:refs] if refs > len(text) // 2 else text
    return body if len(body) <= budget else body[:budget // 2] + "\n[...]\n" + body[-budget // 2:]


def _best_spot(n: str, words: set, paper: str) -> int | None:
    """Where the paper gives a number, choosing the place most about the text that uses it (reference lists come first)."""
    spots = [m.start() for m in re.finditer(rf"(?<![\w.]){re.escape(n)}(?![\w])", paper)][:30]
    window = lambda at: paper[max(0, at - NUMBER_WINDOW):at + len(n) + NUMBER_WINDOW]
    return max(spots, key=lambda at: len(words & set(re.findall(r"[a-z]{4,}", window(at).lower())))) if spots else None


def brief_numbers(lesson: dict, paper: str) -> list[dict]:
    """Each number in the paper in brief, with the sentence that uses it and the passage where the paper gives it
    (None when the paper never prints it)."""
    brief = " ".join([(lesson.get("intro") or {}).get("summary", "")] + [pg.get("body", "") for pg in lesson.get("primer") or []])
    out, seen = [], set()
    for sentence in re.split(r"(?<=[.!?])\s+", brief):
        words = {w for w in re.findall(r"[a-z]{4,}", sentence.lower())}
        for n in NUMBER.findall(sentence):
            if n in seen or len(out) >= Q.NUMBERS_CHECKED:
                continue
            seen.add(n)
            at = _best_spot(n, words, paper)
            out.append({"number": n, "sentence": sentence.strip(),
                        "passage": paper[max(0, at - NUMBER_WINDOW):at + len(n) + NUMBER_WINDOW].replace("\n", " ") if at is not None else None})
    return out


def lesson_evidence(lesson: dict, raw: str) -> str:
    """What the lesson-level questions see of the paper: each source's opening and closing (a combined lesson's
    sources share the budget, so none is left out), the passages around each quote in the paper in brief, and where
    the paper gives the numbers the brief uses."""
    sources = L.source_map(raw)
    doc = L.source_document(raw)
    if sources:
        each = LESSON_PAPER // len(sources)
        parts = [f"--- SOURCE {sid}: {src.get('title', '')} (opening and closing) ---\n{_ends(src.get('text', ''), each)}" for sid, src in sources.items()]
    else:
        parts = [f"--- THE PAPER'S OPENING AND CLOSING ---\n{_ends(doc, LESSON_PAPER // 3)}"]
    quoted = [pg["quote"] for pg in lesson.get("primer") or [] if pg.get("quote")]
    if quoted:
        parts.append("--- WHERE THE PAPER IN BRIEF'S QUOTES APPEAR ---\n" + "\n\n".join(
            quote_context(doc, q)[:PRIMER_CONTEXT] for q in quoted))
    brief = " ".join([(lesson.get("intro") or {}).get("summary", "")] + [pg.get("body", "") for pg in lesson.get("primer") or []])
    return "\n\n".join(parts) + number_passages(brief, doc)


def data_checks(lesson: dict) -> dict:
    """{check: {concept: share from 0 to 1}}, measured from the lesson itself (see questions.STEP_WORDS and the M groups).
    A concept a check doesn't apply to (no narration, no tasks) is left out of that check."""
    out = {"signaling": {}, "contiguity": {}, "apprehension": {}, "constructive": {}}
    for c in lesson.get("concepts") or []:
        cid = c["id"]
        steps = [*((c.get("animation") or {}).get("steps") or []), *(((c.get("understand") or {}).get("walkthrough") or {}).get("steps") or [])]
        steps = [st for st in steps if isinstance(st, dict) and st.get("say")]
        if steps and c.get("model"):
            out["signaling"][cid] = sum(1 for st in steps if st.get("focus")) / len(steps)
            changing = [st for st in steps if any(w in st["say"].lower() for w in Q.CHANGE_WORDS)]
            if changing:
                out["contiguity"][cid] = sum(1 for st in changing if st.get("set")) / len(changing)
        if steps:
            def takes_in(st):
                # How long player.js keeps a step up: max(1200, ms or 2400) × 0.75, plus × 0.45 while it moves the model.
                words, ms = len(st["say"].split()), max(1200, st.get("ms") or 2400)
                shown = ms * 0.75 + (ms * 0.45 if st.get("set") else 0)
                return words <= Q.STEP_WORDS and shown >= Q.MS_PER_WORD * words
            out["apprehension"][cid] = sum(1 for st in steps if takes_in(st)) / len(steps)
        kinds = {a.get("kind") for a in c.get("activities") or []} or ({"predict"} if c.get("predict") else set()) | ({"check"} if c.get("check") else set())
        if kinds & set(Q.CONSTRUCTIVE) or (c.get("explore") or {}).get("goals"):
            out["constructive"][cid] = 1.0 if kinds & set(Q.CONSTRUCTIVE) else 0.0
    return out


def model_directions(c: dict) -> list[dict]:
    """Which way each output moves as each slider rises (others at their defaults), where it moves one way only.
    The pairs the concept's teaching talks about come first, up to DIRECTION_PAIRS."""
    m = c.get("model") or {}
    u = c.get("understand") or {}
    teaching = " ".join([u.get("explanation", ""), c.get("idea", ""), *(s.get("say", "") for s in (u.get("walkthrough") or {}).get("steps") or []),
                         *(s.get("say", "") for s in (c.get("animation") or {}).get("steps") or [])]).lower()
    pairs = []
    for ctl in m.get("controls") or []:
        if ctl.get("kind", "slider") != "slider" or not all(isinstance(ctl.get(k), (int, float)) for k in ("min", "max")):
            continue
        lo, hi = float(ctl["min"]), float(ctl["max"])
        try:
            runs = [L.compute(m, {ctl["id"]: lo + (hi - lo) * t}) for t in (0, .25, .5, .75, 1)]
        except Exception:
            continue
        for o in m.get("outputs") or []:
            vals = [r.get(o.get("id")) for r in runs]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vals):
                continue
            steps = [b - a for a, b in zip(vals, vals[1:])]
            tol = 1e-9 * max(1.0, max(abs(v) for v in vals))
            if all(d > tol for d in steps):
                way = "rises"
            elif all(d < -tol for d in steps):
                way = "falls"
            else:
                continue  # flat, or up and down: no single direction to check
            words = [w for w in re.findall(r"[a-z]{4,}", (o.get("label") or "").lower())]
            talked = sum(w in teaching for w in words) / max(1, len(words))
            pairs.append({"control": ctl["id"], "output": o["id"], "control_label": ctl.get("label") or ctl["id"],
                          "output_label": o.get("label") or o["id"], "model": way, "talked": talked})
    pairs.sort(key=lambda p: -p["talked"])
    return pairs[:Q.DIRECTION_PAIRS]


def teaching_text(c: dict) -> str:
    """What the concept says in words, without its model's formulas or table, for asking what direction it teaches."""
    u = c.get("understand") or {}
    out = [f"CONCEPT: {c.get('title', '')}", f"IDEA: {c.get('idea', '')}", f"EXPLANATION: {u.get('explanation', '')}"]
    out += ["TOUR:"] + [f"  - {s.get('say', '')}" for s in (c.get("animation") or {}).get("steps") or [] if s.get("say")]
    out += ["WALKTHROUGH:"] + [f"  - {s.get('say', '')}" for s in (u.get("walkthrough") or {}).get("steps") or [] if s.get("say")]
    return "\n".join(out)


TIMEOUT = 90  # a whole concept's questions in one request; the eval can wait, search can't


# ---------------------------------------------------------------- asking


def _ask(state: str, questions: dict) -> dict:
    """Jev's answers. jev.ask already retries a brief outage; anything else stops this lesson's judging."""
    return jev.ask(state, questions, TIMEOUT)


def _choice(key_ask: str) -> dict:
    return {"type": "choice", "instructions": key_ask, "criteria": Q.ANSWERS}


def _noul(key_ask: str) -> dict:
    return {"type": "noul", "instructions": key_ask}


def judge_lesson(lesson: dict, paper: str) -> dict:
    """Every question that applies, asked through every lens, with the text each was asked about. Raises jev.JevError."""
    raw, paper = paper, L.source_document(paper)
    requests = []

    def run(name: str, state: str, questions: dict, **extra):
        if questions:
            requests.append({"name": name, "state": state, "questions": questions, "answers": _ask(state, questions), **extra})

    for i, c in enumerate(lesson.get("concepts") or [], 1):
        cid = c["id"]
        evidence = concept_evidence(c, paper)
        with_paper, teaching = {}, {}
        for lens, lead in Q.LENSES.items():
            for item, spec in Q.PART_A.items():
                if Q.applies(item, c, lesson):
                    (with_paper if spec["paper"] else teaching)[f"{cid}|A|{item}|{lens}"] = _choice(lead + spec["ask"])
            for kind, ask in Q.CRITICAL.items():
                if kind in ("reversed_model",) and not c.get("model"):
                    continue
                with_paper[f"{cid}|C|{kind}|{lens}"] = _noul(lead + ask)
            for key, label in Q.scored_tasks(c):
                with_paper[f"{cid}|C|wrong_answer:{key}|{lens}"] = _noul(f"{lead}Look at {label}. {Q.WRONG_ANSWER}")
        text = concept_text(c, i)
        run(f"{cid} with the paper", f"{text}\n\n=== FROM THE PAPER ===\n\n{evidence}{number_passages(text, paper)}", with_paper)
        run(f"{cid} as taught", concept_text(c, i, conditions=False), teaching)  # as a learner sees it: no success conditions
        # The direction check: one plain factual question per control–output pair, asked of the paper (without the
        # model, so Jev can't anchor on it) and of the concept's own words; the code compares the answers with the model.
        pairs = model_directions(c)
        if pairs:
            ways = {}
            for source, state in (("paper", f"IDEA: {c.get('idea', '')}\n\n=== FROM THE PAPER ===\n\n{evidence}"), ("text", teaching_text(c))):
                questions = {}
                for pr in pairs:
                    item = f"dir_{source}:{pr['control']}:{pr['output']}"
                    questions[f"{cid}|D|{item}|direct"] = {"type": "choice", "criteria": Q.DIRECTION_ANSWERS,
                                                           "instructions": Q.DIRECTION_ASK[source].format(control=pr["control_label"], output=pr["output_label"])}
                    ways[item] = pr["model"]
                run(f"{cid} directions ({source})", state, questions, directions=dict(ways))

    with_paper, teaching = {}, {}
    for lens, lead in Q.LENSES.items():
        for dim, spec in Q.PART_B.items():
            for j, check in enumerate(spec["checks"]):
                if Q.check_applies(check, lesson):
                    (with_paper if spec["paper"] else teaching)[f"lesson|B|{dim}.{j}|{lens}"] = _noul(lead + check["ask"])
    evidence = lesson_evidence(lesson, raw)
    run("lesson with the paper", f"{lesson_text(lesson)}\n\n=== FROM THE PAPER ===\n\n{evidence}", with_paper)
    # The paper in brief's numbers, one question each, beside where the paper gives them.
    items = brief_numbers(lesson, paper)
    if items:
        blocks = [f"[{i}] THE PAPER IN BRIEF SAYS: {x['sentence']}\n    THE PAPER, WHERE IT GIVES {x['number']}: "
                  + (f"...{x['passage']}..." if x["passage"] else "(the paper never prints this number; see the excerpt below)") for i, x in enumerate(items, 1)]
        state = "\n\n".join(blocks) + ("\n\n=== FROM THE PAPER ===\n\n" + evidence if any(not x["passage"] for x in items) else "")
        run("the paper in brief's numbers", state, {f"lesson|N|num:{i}|direct": _noul(Q.NUMBER_ASK.format(i=i, number=x["number"])) for i, x in enumerate(items, 1)})
    run("lesson as taught", lesson_text(lesson, conditions=False), teaching)
    model = next((r["answers"].get("_model") for r in requests), jev.MODEL)
    return {"questions_version": Q.VERSION, "model": model, "requests": requests, "data": data_checks(lesson)}


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
            if not vs:
                continue  # the item doesn't apply to this concept
            answer, split = majority([v["answer"] for v in vs])
            if Q.PART_A[item].get("passed_when") == "no":  # a problem-finding item: "no problem" is a pass
                answer = {"yes": "no", "no": "yes"}.get(answer, answer)
            items[f"{cid}.{item}"] = answer
            certainty = round(sum(v["p"] for v in vs if v["answer"] == answer) / max(1, len(vs)), 3)
            if split:
                flag(cid, "A", item, "the three lenses disagree", certainty)
            if answer in ("partly", "no"):
                failed.append({"what": f"{cid} {item} ({Q.PART_A[item]['name']}): {answer}", "certainty": certainty, "item": item, "answer": answer})
        for (target, part, kind), vs in votes.items():
            if target != cid or part != "C":
                continue
            base = kind.split(":")[0]
            at = Q.CONFIRM_BY_KIND.get(base, Q.CONFIRM_AT)  # the eval's own thresholds, not the build's
            yes = [v for v in vs if v["answer"] == "yes" or at is not None and v["p"] >= at]
            sure = [v for v in vs if at is not None and v["p"] >= at]
            certainty = round(max(v["p"] for v in vs), 3)
            if len(sure) * 2 > len(vs):
                mean = sum(v["p"] for v in vs) / len(vs)
                critical.append({"type": base, "where": cid, "exercise": kind.split(":")[1] if ":" in kind else None,
                                 "certainty": certainty, "borderline": abs(mean - at) < Q.BORDERLINE,
                                 "votes": [{k: v[k] for k in ("lens", "answer", "p")} for v in vs]})
                flag(cid, "C", kind, "a critical error, confirmed by most lenses" + (" (borderline)" if critical[-1]["borderline"] else ""), certainty)
            elif yes:
                flag(cid, "C", kind, f"a possible critical error, seen by {', '.join(v['lens'] for v in yes)}", certainty)
        # A quote Jev plainly says doesn't support its claim is a misleading quote, whatever the dedicated question said.
        if items.get(f"{cid}.A1") == "no" and not any(c["type"] == "misleading_quote" and c["where"] == cid for c in critical):
            vs = votes[(cid, "A", "A1")]
            critical.append({"type": "misleading_quote", "where": cid, "exercise": None, "via": "A1", "borderline": False,
                             "certainty": round(max(v["p"] for v in vs if v["answer"] == "no"), 3), "votes": [{k: v[k] for k in ("lens", "answer", "p")} for v in vs]})
            flag(cid, "A", "A1", "a critical error: the quote doesn't support its claim", critical[-1]["certainty"])
        # The direction check: the model moves an output one way; the paper, or the concept's own words, say the other.
        for ri, r in enumerate(judged["requests"]):
            for key, a in r["answers"].items():
                if not key.startswith(cid + "|D|"):
                    continue
                item = key.split("|")[2]
                source, ctl, out = item.split(":")
                model_way = (r.get("directions") or {}).get(item)
                opposite = {"rises": "falls", "falls": "rises"}.get(model_way)
                p = float((a.get("probabilities") or {}).get(opposite, 0)) if opposite else 0
                at = Q.DIRECTION_AT[source.removeprefix("dir_")]
                if p >= at:
                    what = "the paper" if source == "dir_paper" else "the concept's own teaching"
                    critical.append({"type": "reversed_model", "where": cid, "exercise": None, "via": source, "certainty": round(p, 3),
                                     "borderline": p - at < Q.BORDERLINE,
                                     "detail": f"as {ctl} rises the model's {out} {model_way}; {what} says it {opposite}"})
                    review.append({"what": f"{cid} reversed_model", "why": f"a critical error: as {ctl} rises the model's {out} {model_way}, but {what} says it {opposite}",
                                   "certainty": round(p, 3), "votes": [{"lens": "direct", "answer": opposite, "p": round(p, 3)}],
                                   "question": r["questions"][key]["instructions"], "state": r["state"]})
                elif p >= Q.DIRECTION_REVIEW:
                    review.append({"what": f"{cid} reversed_model", "why": f"a possible critical error: {ctl} and {out} may move the other way ({source})",
                                   "certainty": round(p, 3), "votes": [{"lens": "direct", "answer": opposite, "p": round(p, 3)}],
                                   "question": r["questions"][key]["instructions"], "state": r["state"]})

    scales = {}
    for dim, spec in Q.PART_B.items():
        passed = asked = 0
        for j, check in enumerate(spec["checks"]):
            vs = votes.get(("lesson", "B", f"{dim}.{j}"), [])
            if not vs:
                continue  # a check that doesn't apply to this lesson
            asked += 1
            answer, split = majority([v["answer"] for v in vs])
            wanted = check.get("passed_when", "yes")  # a check that looks for a problem passes when the answer is no
            passed += answer == wanted
            if split:
                flag("lesson", "B", f"{dim}.{j}", "the three lenses disagree", round(max((v["p"] for v in vs), default=0), 3))
            if answer != wanted:
                ps = [v["p"] if wanted == "yes" else 1 - v["p"] for v in vs]
                failed.append({"what": f"{dim} ({spec['name']}): {check['ask']}", "certainty": round(1 - min(ps, default=1), 3), "item": dim, "answer": answer or "no"})
        scales[dim] = round(passed / asked, 2) if asked else None

    for r in judged["requests"]:
        for key, a in r["answers"].items():
            if key.startswith("lesson|N|") and float(a.get("noul", 1)) < .5:
                i = int(key.split("|")[2].split(":")[1])
                review.append({"what": f"lesson number {i}", "why": "the paper may not report this number as the paper in brief states it",
                               "certainty": round(1 - float(a["noul"]), 3), "votes": [{"lens": "direct", "answer": "no", "p": round(float(a["noul"]), 3)}],
                               "question": r["questions"][key]["instructions"], "state": r["state"]})
                failed.append({"what": f"The paper in brief: a number the paper may not report ({r['questions'][key]['instructions'].split('about ')[-1].rstrip('?')})",
                               "certainty": round(1 - float(a["noul"]), 3), "item": "N", "answer": "no"})

    verdict = verdict_for(items, scales, critical)
    failed.sort(key=lambda f: -f["certainty"])
    review.sort(key=lambda r: (not r["why"].startswith(("a critical", "a possible")), -r["certainty"]))
    # What the build's own Jev check found, kept apart: the eval's questions are independent of it.
    build = {"flags_left_for_review": lesson.get("flags") or [],
             "left_out_by_jev": [o for o in lesson.get("omitted") or [] if isinstance(o, dict) and "Jev" in str(o.get("reason", ""))]}
    return {"items": items, "scales": scales, "scores": scores(judged), "critical_errors": critical, "verdict": verdict,
            "top_problems": [f["what"] for f in failed[:3]], "needs_review": review, "build_check": build}


def _credit(answer: dict, passed_when: str | None = None) -> float | None:
    """How far one lens's answer passes, from 0 to 1, using Jev's probabilities rather than its single choice:
    a choice scores P(yes) + half P(partly), ignoring cannot_judge; a yes/no check scores P(pass)."""
    if "noul" in answer or answer.get("type") == "noul":
        p = float(answer.get("noul", 0))
        return p if passed_when in (None, "yes") else 1 - p
    probs = answer.get("probabilities") or {answer.get("choice"): 1.0}
    judged = sum(float(probs.get(k, 0)) for k in ("yes", "partly", "no"))
    if judged <= 0:
        return None
    good = "no" if passed_when == "no" else "yes"
    return (float(probs.get(good, 0)) + .5 * float(probs.get("partly", 0))) / judged


def scores(judged: dict) -> dict:
    """The scorecard for one lesson, each 0–100 (higher is better), from every lens's answers. Each score averages its
    groups (questions.SCORES), every group counting once: a concept group's credits are averaged per concept, then over
    concepts; a lesson group's over its checks. A critical-error group scores 1 − P(error). `overall` is the mean of the
    scores. Comparable only between runs judged with the same questions and Jev model."""
    concept, lesson = {}, {}  # concept: {group: {concept: [credits]}}; lesson: {group: [credits]}
    for r in judged["requests"]:
        for key, a in r["answers"].items():
            if key == "_model":
                continue
            target, part, item, _lens = key.split("|")
            if part == "B":
                dim, j = item.split(".")
                lesson.setdefault(dim, []).append(_credit(a, Q.PART_B[dim]["checks"][int(j)].get("passed_when", "yes")))
                continue
            if part == "N":  # a number in the paper in brief that the paper reports
                lesson.setdefault("N", []).append(_credit(a, "yes"))
                continue
            if part == "A":
                group, credit = item, _credit(a, Q.PART_A[item].get("passed_when"))
            elif part == "C":
                group, credit = "C:" + item.split(":")[0], _credit(a, "no")
            elif part == "D":  # a direction answer: credit is how unlikely it is that the text says the opposite of the model
                opposite = {"rises": "falls", "falls": "rises"}.get((r.get("directions") or {}).get(item))
                if not opposite:
                    continue
                group, credit = "D", 1 - float((a.get("probabilities") or {}).get(opposite, 0))
            else:
                continue
            concept.setdefault(group, {}).setdefault(target, []).append(credit)
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    group_credit = {}
    for group, by_concept in concept.items():
        per = [mean([c for c in cs if c is not None]) for cs in by_concept.values()]
        group_credit[group] = mean([x for x in per if x is not None])
    for group, cs in lesson.items():
        group_credit[group] = mean([c for c in cs if c is not None])
    for check, by_concept in (judged.get("data") or {}).items():  # the data checks, already shares per concept
        group_credit["M:" + check] = mean(list(by_concept.values()))
    out = {}
    for name, spec in Q.SCORES.items():
        parts = [group_credit[g] for g in spec["groups"] if group_credit.get(g) is not None]
        out[name] = round(100 * mean(parts), 1) if parts else None
    present = [v for v in out.values() if v is not None]
    out["overall"] = round(sum(present) / len(present), 1) if present else None
    return out


def verdict_for(items: dict, scales: dict, critical: list) -> str:
    """dont_ship: a confirmed critical error, or a quote or model judged plainly wrong. ship_with_fixes: anything else failed."""
    if critical or any(a == "no" and k.endswith((".A1", ".A2")) for k, a in items.items()):
        return "dont_ship"
    if any(a in ("partly", "no") for a in items.values()) or any(s is not None and s < Q.B_PASS for s in scales.values()):
        return "ship_with_fixes"
    return "ship"
