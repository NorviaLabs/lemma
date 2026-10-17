"""Check that Lemma can read the full text of every paper in eval/papers.json.

    uv run python eval/check.py

Prints one line per paper: whether it was read, its length and pages, and the title Lemma found,
so a wrong link shows up as a title that doesn't match.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lemma import ingest

PAPERS = json.loads((Path(__file__).parent / "papers.json").read_text())


def check(paper: dict) -> tuple[dict, str]:
    try:
        p = ingest.first_readable(paper["urls"], budget=90)
    except ingest.IngestError as e:
        return paper, f"FAIL  {e}"
    return paper, f"ok    {len(p.text):>8,} chars {p.pages or '-':>4} pages  found: {p.title[:70]}"


def main() -> int:
    failed = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for paper, line in pool.map(check, PAPERS):
            failed += line.startswith("FAIL")
            print(f"{paper['id']:>2}. {paper['title'][:60]:<60}  {line}", flush=True)
    print(f"\n{len(PAPERS) - failed} of {len(PAPERS)} readable")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
