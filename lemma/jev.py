"""TypeSafe's Jev: typed decisions (a choice, a score, a yes or no) about text, with calibrated probabilities.

Lemma pays for it with the server's TYPESAFE_API_KEY. Jev is essential, not optional: without the key, searches and
builds don't start, and when Jev fails, the step it was judging fails rather than carrying on unchecked. Lemma
sends Jev text to judge, never a learner's key or who they are.
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request

from . import __version__

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"  # pinned, so the thresholds Lemma applies keep their meaning
ATTEMPTS = 3
RETRY_WAIT = 1.0  # seconds before the second attempt, doubling after
RETRY_STATUSES = (429, 500, 502, 503, 504, 529)
MISSING = "This OpenLemma has no TypeSafe key (TYPESAFE_API_KEY), which search and lesson building need for Jev's checks."


class JevError(Exception):
    pass


def available() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY"))


def require():
    """Jev is part of every search and build: without a key, they don't start."""
    if not available():
        raise JevError(MISSING)


def ask(state, questions: dict, timeout: float) -> dict:
    """Jev's answers, keyed like ``questions``. A brief outage is retried; anything else raises JevError."""
    require()
    req = urllib.request.Request(os.environ.get("TYPESAFE_URL", ENDPOINT), method="POST",
                                 data=json.dumps({"model": MODEL, "state": state, "questions": questions}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["TYPESAFE_API_KEY"],
                                          "User-Agent": f"Lemma/{__version__}"})
    for attempt in range(ATTEMPTS):
        last = attempt == ATTEMPTS - 1
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                reply = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            if last or e.code not in RETRY_STATUSES:
                raise JevError(f"Jev answered {e.code}") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
            if last:
                raise JevError(f"Couldn't use Jev ({e.__class__.__name__})") from None
        except ValueError:
            raise JevError("Jev sent a reply OpenLemma couldn't read") from None
        time.sleep(RETRY_WAIT * 2 ** attempt)
    if not isinstance(reply, dict) or not isinstance(reply.get("answers"), dict):
        raise JevError("Jev sent a reply OpenLemma couldn't read")
    reply["answers"]["_model"] = reply.get("model") or MODEL
    return reply["answers"]
