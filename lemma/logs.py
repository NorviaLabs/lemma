"""Error reports for whoever runs Lemma. Lemma keeps no usage logs; when something breaks, it writes
where it broke to stderr, so a host's `docker compose logs` can show it.

A report has the exception's type and the lines of Lemma's code it passed through, but never its
message, the request, the paper or a key: an exception's message can repeat any of them.
"""

from __future__ import annotations

import sys
import time
import traceback
import uuid


def report(where: str, exc: BaseException) -> str:
    """Writes one error report and returns its id, which the learner can quote to whoever runs Lemma."""
    eid = uuid.uuid4().hex[:8]
    frames = "".join(traceback.format_list(traceback.extract_tb(exc.__traceback__)))
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"{stamp} error {eid} in {where}: {exc.__class__.__name__}\n{frames}", end="", file=sys.stderr, flush=True)
    return eid
