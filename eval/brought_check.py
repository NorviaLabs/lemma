"""Bring each of the ten labelled papers in eval/brought.json on its own, and score what the lesson builds on.

    set -a; . ./deploy/lemma.env; set +a          # TYPESAFE_API_KEY: Jev sorts and rates every source
    uv run python eval/brought_check.py --provider chatgpt --model gpt-6.1-sol --variant old
    uv run python eval/brought_check.py --provider chatgpt --model gpt-6.1-sol --variant new

It costs money: each paper is read once (kept in eval/results/<run>/sources/), sorted into its category by Jev,
and for "new" its subjects are named by the provider and rated by Jev (kept in subjects/); each variant then makes
one outline per paper on the provider. A saved outline is reused; a failed one is tried again.

"old" outlines the paper alone, as before Stage E; "new" gives the outline what the paper builds on. Scores:
  subjects   labelled prerequisites among the subjects the step found (new only)
  taught     labelled prerequisites named in a concept's title, idea or subject
  accounted  taught, or named in the outline's "assumes"
  core       concepts on the paper's own ideas (core or contribution): the new prompt must not crowd them out
  failed     outlines that didn't pass their checks
It passes when subjects reach 60% of the labels, accounted reaches 70% and beats old, no more outlines fail than
old, and the new outlines keep at least as many core concepts as old.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lemma import categorize, generate, ingest, search
from lemma.llm import ProviderError, make_provider

sys.path.insert(0, str(Path(__file__).parent))
from search_check import found  # noqa: E402

EVAL = Path(__file__).parent
PAPERS = json.loads((EVAL / "brought.json").read_text())["papers"]


def cached(path: Path, make):
    if path.exists():
        return json.loads(path.read_text())
    value = make()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, ensure_ascii=False))
    return value


def paper_text(out: Path, paper: dict) -> str:
    """The paper bundled as one brought source, as a lesson request bundles it."""
    def read():
        p = ingest.first_readable(paper["urls"], budget=120)
        return {"lemma_sources": [{"id": "s1", "title": p.title or paper["id"], "url": p.url, "authors": "", "year": None, "text": p.text}]}
    return json.dumps(cached(out / "sources" / f"{paper['id']}.json", read), ensure_ascii=False)


def context(out: Path, provider, paper: dict, text: str) -> dict:
    """What the server's request runner works out before outlining brought sources (server._source_context)."""
    def work():
        category = categorize.categorize({"title": paper["id"], "text": text})
        field = [c["id"] for c in (category["primary"], category["secondary"]) if c and c["id"] != "other"]
        sources = list(generate.L.source_map(text).values())
        return {"query": None, "about": sources[0]["title"], "field": field or None,
                **search.source_subjects(provider, sources, paper["level"], field)}
    return cached(out / "subjects" / f"{paper['id']}.json", work)


def score(paper: dict, outline: dict | None, subjects: list[dict]) -> dict:
    pre = paper["prerequisites"]
    row = {"id": paper["id"], "prerequisites": len(pre), "failed": outline is None,
           "subjects": sum(found(p, [s["title"] for s in subjects]) for p in pre), "taught": 0, "accounted": 0, "core": 0}
    if outline is None:
        return row
    concepts = [c for c in outline.get("concepts", []) if isinstance(c, dict)]
    said = [f"{c.get('title', '')} {c.get('idea', '')} {c.get('subject') or ''}" for c in concepts]
    assumed = [a for a in outline.get("assumes") or [] if isinstance(a, str)]
    row["taught"] = sum(found(p, said) for p in pre)
    row["accounted"] = sum(found(p, said) or found(p, assumed) for p in pre)
    row["core"] = sum(c.get("role") in ("core", "contribution") for c in concepts)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--provider", required=True, help="claude, openai, opencode or chatgpt")
    ap.add_argument("--model", default="")
    ap.add_argument("--variant", choices=("old", "new"), required=True)
    ap.add_argument("--run", default="brought-" + time.strftime("%Y-%m-%d"))
    ap.add_argument("--only", nargs="*", help="paper ids to run (default: all ten)")
    ap.add_argument("--parallel", type=int, default=2)
    args = ap.parse_args()
    provider = make_provider(args.provider, os.environ.get("LEMMA_PROVIDER_KEY", ""), args.model)
    ok, why = provider.available()
    if not ok:
        print(why, file=sys.stderr)
        return 2
    out = EVAL / "results" / args.run
    (out / args.variant).mkdir(parents=True, exist_ok=True)
    papers = [p for p in PAPERS if not args.only or p["id"] in args.only]

    def one(paper):
        path = out / args.variant / f"{paper['id']}.json"
        if path.exists() and json.loads(path.read_text())["outline"]:
            return json.loads(path.read_text())
        record = {"outline": None, "subjects": [], "error": ""}
        try:
            text = paper_text(out, paper)
            ctx = context(out, provider, paper, text) if args.variant == "new" else None
            record["subjects"] = (ctx or {}).get("subjects", [])
            record["outline"] = generate.make_outline(generate.Job("eval"), provider, text, paper["level"], search=ctx) if ctx \
                else generate.make_outline(generate.Job("eval"), provider, text, paper["level"])
        except (ingest.IngestError, generate.GenerationError, ProviderError, search.SearchError, categorize.CategorizeError) as e:
            record["error"] = str(e)
        path.write_text(json.dumps(record, indent=1, ensure_ascii=False))
        print(f"{paper['id']:<24} {'outlined' if record['outline'] else 'FAILED ' + record['error'][:90]}", flush=True)
        return record

    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        records = list(pool.map(one, papers))
    rows = [score(p, r["outline"], r["subjects"]) for p, r in zip(papers, records)]
    total = sum(r["prerequisites"] for r in rows)
    summary = {"variant": args.variant, "provider": provider.label, "papers": len(rows), "prerequisites": total,
               **{k: sum(r[k] for r in rows) for k in ("subjects", "taught", "accounted", "core", "failed")}}
    (out / f"summary-{args.variant}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    for r in rows:
        print(f"{r['id']:<24} {'FAILED' if r['failed'] else '':<7}" + (f"subjects {r['subjects']}/{r['prerequisites']}  " if args.variant == "new" else "")
              + f"taught {r['taught']}/{r['prerequisites']}  accounted {r['accounted']}/{r['prerequisites']}  core {r['core']}")
    print(f"\n{args.variant}: " + (f"subjects {summary['subjects']}/{total}, " if args.variant == "new" else "")
          + f"taught {summary['taught']}/{total}, accounted {summary['accounted']}/{total}, core concepts {summary['core']}, failed {summary['failed']}")
    old_path = out / "summary-old.json"
    if args.variant == "new" and old_path.exists():
        old = json.loads(old_path.read_text())["summary"]
        passed = (summary["subjects"] >= 0.6 * total and summary["accounted"] >= 0.7 * total and summary["accounted"] > old["accounted"]
                  and summary["failed"] <= old["failed"] and summary["core"] >= old["core"])
        print(f"against old: accounted {old['accounted']}, core {old['core']}, failed {old['failed']}\n" + ("PASS" if passed else "FAIL"))
        return 0 if passed else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
