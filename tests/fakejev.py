"""A stand-in for TypeSafe's Jev during tests: Jev is essential, so every search and build asks it.

Importing this module installs it for the whole test run. It answers every question harmlessly: no critical
errors, an average relevance, and the first choice that isn't a rejection. Tests that need particular answers or
failures patch jev.ask themselves; REAL_ASK is the network client, for tests of that client.
"""
import os
from unittest.mock import patch

from lemma import jev

REAL_ASK = jev.ask
NOT_CHOSEN = ("off_topic", "other")


def answer(state, questions, timeout):
    out = {"_model": "jev-test"}
    for key, q in questions.items():
        if q.get("type") == "noul":
            out[key] = {"type": "noul", "noul": 0.05}
        elif q.get("type") == "score":
            out[key] = {"type": "score", "score": 2.0}
        else:
            choice = next(c for c in q["criteria"] if c not in NOT_CHOSEN)
            out[key] = {"type": "choice", "choice": choice, "confidence": 0.9, "probabilities": {choice: 0.9}}
    return out


os.environ.setdefault("TYPESAFE_API_KEY", "ts-test")
patch.object(jev, "ask", side_effect=answer).start()
