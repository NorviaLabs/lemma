"""Copies of good lessons with one deliberate critical error each, to measure what the Jev eval catches.

Each kind plants a mistake Part C asks about, in one concept, and records where. wrong_task_answer needs a
lesson with scored activity blocks (choice, match, order, passage, estimate or trace); lessons without them are
skipped for that kind. The eval passes when it flags
that concept; run.py's summary reports the catch rate for each kind.
"""

from __future__ import annotations

import copy
import random
import re

KINDS = ("reversed_model", "misleading_quote", "wrong_answer", "fabricated_finding", "wrong_claim", "wrong_task_answer")
FABRICATED = " The paper reports that this effect was 47% stronger in its largest sample than in its smallest."
WRONG_CLAIM = " The paper concludes that this effect disappears entirely once the sample is large enough."


def _reverse(c: dict) -> str | None:
    """Mirror one slider in one output's formula, so raising it moves the output the other way. Prefers an output the
    teaching talks about and a slider that moves it one way, as a real mistake would matter, and checks it did reverse."""
    import jev_judge  # the same direction finder the eval uses
    m = c.get("model") or {}
    before = {(d["control"], d["output"]): d["model"] for d in jev_judge.model_directions(c)}
    outputs = {o.get("id"): o for o in m.get("outputs") or []}
    for (ctl_id, out_id), way in before.items():
        o, ctl = outputs.get(out_id), next((k for k in m.get("controls") or [] if k.get("id") == ctl_id), None)
        if not o or not ctl or not re.search(rf"\b{re.escape(ctl_id)}\b", o.get("expr", "")):
            continue
        old = o["expr"]
        o["expr"] = re.sub(rf"\b{re.escape(ctl_id)}\b", f"({ctl['min']} + {ctl['max']} - {ctl_id})", old)
        after = {(d["control"], d["output"]): d["model"] for d in jev_judge.model_directions(c)}
        if after.get((ctl_id, out_id)) not in (None, way):
            return f"output {out_id} now {after[(ctl_id, out_id)]} as {ctl_id} rises (it {way})"
        o["expr"] = old  # it didn't reverse cleanly; try the next pair
    return None


def _swap_quote(c: dict, paper: str, rng: random.Random) -> str | None:
    """Replace the quote with a sentence from somewhere else in the paper: real words, beside the point."""
    quote = (c.get("understand") or {}).get("quote", "")
    at = paper.find(quote[:60]) if quote else -1
    sentences = [(m.start(), m.group().strip()) for m in re.finditer(r"[A-Z][^.!?\n]{80,260}[.!?]", paper)]
    far = [s for pos, s in sentences if at < 0 or abs(pos - at) > 8000]
    if not far:
        return None
    c["understand"]["quote"] = rng.choice(far)
    return "the quote is now an unrelated sentence from elsewhere in the paper"


def _wrong_answer(c: dict) -> str | None:
    p = c.get("predict") or {}
    if not isinstance(p.get("answer"), int) or len(p.get("options") or []) < 2:
        return None
    old, new = p["answer"], (p["answer"] + 1) % len(p["options"])
    p["answer"] = new
    why = p.get("why") or []
    if len(why) > max(old, new):
        why[old], why[new] = why[new], why[old]  # the reasons follow, as a model that got it wrong would write them
    return f"'Use it' now marks option {new + 1} correct instead of option {old + 1}"


def _wrong_task(c: dict) -> str | None:
    """Break the answer key of one activity block, as a model that got it wrong would write it."""
    for a in c.get("activities") or []:
        kind, name = a.get("kind"), a.get("title") or a.get("id")
        if kind == "choice" and a.get("mode") == "determinate":
            n = len(a.get("options") or [])
            if a.get("multi") and n > 1:
                a["answers"] = sorted({(x + 1) % n for x in a["answers"]})
                return f"multi choice {name} now marks different options as supported"
            if isinstance(a.get("answer"), int) and n > 1:
                a["answer"] = (a["answer"] + 1) % n
                return f"choice {name} now marks option {a['answer'] + 1} correct"
        elif kind == "match" and len(a.get("pairs") or []) >= 2:
            p0, p1 = a["pairs"][0], a["pairs"][1]
            p0["target"], p1["target"] = p1["target"], p0["target"]
            return f"match {name} now pairs '{p0['text']}' and '{p1['text']}' with each other's targets"
        elif kind == "order" and len(a.get("items") or []) >= 3:
            a["items"][0], a["items"][-1] = a["items"][-1], a["items"][0]
            return f"order {name} now puts its first and last steps the other way round"
        elif kind == "passage" and len(a.get("options") or []) >= 2:
            a["answer"] = (a["answer"] + 1) % len(a["options"])
            return f"passage {name} now marks passage {a['answer'] + 1} as the support"
        elif kind == "estimate" and isinstance(a.get("answer"), (int, float)):
            a["answer"] = a["answer"] * 3 + 10
            return f"estimate {name} now expects {a['answer']}"
        elif kind == "trace" and len(a.get("answer") or []) >= 2 and not a.get("path"):
            a["answer"] = [n["id"] for n in a.get("nodes") or [] if n["id"] not in a["answer"]][:len(a["answer"])] or a["answer"]
            return f"trace {name} now expects the nodes it should exclude"
    return None


def _add(c: dict, sentence: str, what: str) -> str:
    c["understand"]["explanation"] = c["understand"].get("explanation", "") + sentence
    return what


def plant(lesson: dict, paper: str, kind: str, seed: int = 0) -> tuple[dict, dict] | None:
    """A copy of the lesson with one planted error of this kind, and where it is; None if no concept fits."""
    rng = random.Random(seed)
    order = list(range(len(lesson.get("concepts") or [])))
    rng.shuffle(order)
    for i in order:
        out = copy.deepcopy(lesson)
        c = out["concepts"][i]
        if kind == "reversed_model":
            detail = _reverse(c)
        elif kind == "misleading_quote":
            detail = _swap_quote(c, paper, rng)
        elif kind == "wrong_answer":
            detail = _wrong_answer(c)
        elif kind == "fabricated_finding":
            detail = _add(c, FABRICATED, "the explanation now claims an invented 47% finding")
        elif kind == "wrong_claim":
            detail = _add(c, WRONG_CLAIM, "the explanation now claims the effect disappears in large samples")
        elif kind == "wrong_task_answer":
            detail = _wrong_task(c)
        else:
            raise ValueError(kind)
        if detail:
            return out, {"kind": kind, "concept": c["id"], "detail": detail}
    return None
