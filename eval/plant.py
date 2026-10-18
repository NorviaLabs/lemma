"""Copies of good lessons with one deliberate critical error each, to measure what the Jev eval catches.

Each kind plants a mistake Part C asks about, in one concept, and records where. The eval passes when it flags
that concept; run.py's summary reports the catch rate for each kind.
"""

from __future__ import annotations

import copy
import random
import re

KINDS = ("reversed_model", "misleading_quote", "wrong_answer", "fabricated_finding", "wrong_claim")
FABRICATED = " The paper reports that this effect was 47% stronger in its largest sample than in its smallest."
WRONG_CLAIM = " The paper concludes that this effect disappears entirely once the sample is large enough."


def _reverse(c: dict) -> str | None:
    """Mirror one slider in one output's formula, so raising it moves the output the other way."""
    m = c.get("model") or {}
    for o in m.get("outputs") or []:
        for ctl in m.get("controls") or []:
            if ctl.get("kind", "slider") == "slider" and re.search(rf"\b{re.escape(ctl['id'])}\b", o.get("expr", "")):
                mirror = f"({ctl['min']} + {ctl['max']} - {ctl['id']})"
                o["expr"] = re.sub(rf"\b{re.escape(ctl['id'])}\b", mirror, o["expr"])
                return f"output {o['id']} now falls as {ctl['id']} rises"
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
        else:
            raise ValueError(kind)
        if detail:
            return out, {"kind": kind, "concept": c["id"], "detail": detail}
    return None
