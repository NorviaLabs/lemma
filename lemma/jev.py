"""TypeSafe's Jev: typed decisions (a choice, a score, a yes or no) about text, with calibrated probabilities.

A hosted Lemma pays for it with the server's TYPESAFE_API_KEY. Every use is optional: without the key, or when
Jev fails, the caller carries on with its own rules. Lemma sends Jev text to judge, never a learner's key or
who they are.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request

from . import __version__

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"  # pinned, so the thresholds Lemma applies keep their meaning


class JevError(Exception):
    pass


def available() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY"))


def ask(state, questions: dict, timeout: float) -> dict:
    """Jev's answers, keyed like ``questions``."""
    if not available():
        raise JevError("No TypeSafe key on this server")
    req = urllib.request.Request(os.environ.get("TYPESAFE_URL", ENDPOINT), method="POST",
                                 data=json.dumps({"model": MODEL, "state": state, "questions": questions}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["TYPESAFE_API_KEY"],
                                          "User-Agent": f"Lemma/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            reply = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise JevError(f"Jev answered {e.code}") from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as e:
        raise JevError(f"Couldn't use Jev ({e.__class__.__name__})") from None
    if not isinstance(reply, dict) or not isinstance(reply.get("answers"), dict):
        raise JevError("Jev sent a reply Lemma couldn't read")
    reply["answers"]["_model"] = reply.get("model") or MODEL
    return reply["answers"]
