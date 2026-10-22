"""Make an outline for each of the 25 labelled searches from the sources search recommended, and score it.

    set -a; . ./deploy/lemma.env; set +a          # TYPESAFE_API_KEY: Jev checks every outline
    uv run python eval/outline_check.py --provider chatgpt --model gpt-6.1-sol --variant old
    uv run python eval/outline_check.py --provider chatgpt --model gpt-6.1-sol --variant new

It costs money: each outline is one call on the provider you name that reads every recommended source in full,
plus a few Jev calls. The sources come from a saved search run (--search, default search-2026-10-22-e) and are
read once, into eval/results/outline-<run>/sources/; outlines are saved per variant and a saved one isn't made
again, so a rerun only rescores.

"old" is the outline prompt without the search (the lesson as it was before Stage D); "new" gives the outline the
question, field, subjects and what no source covers. Scores per variant:
  answers    Jev reads the question against the outline: "answers", "partly" or "no"
  taught     labelled prerequisites named in a concept's title, idea or subject
  accounted  taught, or named in the outline's "assumes"
  order      concepts teaching a prerequisite subject placed after a core or contribution concept
  bridge     concepts marked as connecting a two-field question's fields
  failed     outlines that didn't pass their checks
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lemma import generate, ingest
from lemma.llm import ProviderError, make_provider

sys.path.insert(0, str(Path(__file__).parent))
from search_check import TESTS, found  # noqa: E402

EVAL = Path(__file__).parent


def search_context(result: dict) -> dict:
    """What the browser sends with a lesson request made from these search results."""
    graph = result.get("graph") or {}
    return {"query": result["query"], "field": (result.get("field") or {}).get("ids"),
            "subjects": [{k: s[k] for k in ("title", "need", "relation")} for s in graph.get("subjects", [])],
            "not_covered": graph.get("not_covered", [])}


def sources(out: Path, test: dict, result: dict) -> str | None:
    """The recommended sources' text, bundled as a lesson request bundles them; read once and kept."""
    path = out / "sources" / f"{test['id']:02d}.json"
    if path.exists():
        return path.read_text() or None
    bundle = []
    for i, r in enumerate((r for r in result["results"] if r.get("recommended")), 1):
        try:
            paper = ingest.first_readable(r.get("urls") or [r["url"]], budget=60)
        except ingest.IngestError as e:
            print(f"{test['id']:>2}. couldn't read {r['title']}: {e}", flush=True)
            continue
        bundle.append({"id": f"s{i}", "title": r["title"], "url": paper.url, "authors": r.get("authors", ""), "year": r.get("year"), "text": paper.text})
    text = json.dumps({"lemma_sources": bundle}, ensure_ascii=False) if bundle else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text or None


def score(test: dict, outline: dict | None, answer: str | None) -> dict:
    row = {"id": test["id"], "query": test["query"], "prerequisites": len(test["prerequisites"]), "failed": outline is None,
           "answer": answer, "taught": 0, "accounted": 0, "order": 0, "bridges": 0}
    if outline is None:
        return row
    concepts = [c for c in outline.get("concepts", []) if isinstance(c, dict)]
    said = [f"{c.get('title', '')} {c.get('idea', '')} {c.get('subject') or ''}" for c in concepts]  # the subject a concept says it teaches counts
    assumed = [a for a in outline.get("assumes") or [] if isinstance(a, str)]
    row["taught"] = sum(found(p, said) for p in test["prerequisites"])
    row["accounted"] = sum(found(p, said) or found(p, assumed) for p in test["prerequisites"])
    kinds = {s["title"]: s.get("relation") for s in outline.get("subjects") or []}
    core = [i for i, c in enumerate(concepts) if c.get("role") in ("core", "contribution")]
    row["bridges"] = sum(1 for c in concepts if c.get("bridge") is True)
    row["order"] = sum(1 for i, c in enumerate(concepts) if kinds.get(c.get("subject")) == "prerequisite" and core and i > core[0])
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--provider", required=True, help="claude, openai, opencode or chatgpt")
    ap.add_argument("--model", default="")
    ap.add_argument("--variant", choices=("old", "new"), required=True)
    ap.add_argument("--search", default="search-2026-10-22-e", help="the saved search run whose recommendations are read")
    ap.add_argument("--run", default="outline-" + time.strftime("%Y-%m-%d"))
    ap.add_argument("--only", type=int, nargs="*", help="search ids to run (default: all 25)")
    ap.add_argument("--parallel", type=int, default=2)
    args = ap.parse_args()
    provider = make_provider(args.provider, os.environ.get("LEMMA_PROVIDER_KEY", ""), args.model)
    ok, why = provider.available()
    if not ok:
        print(why, file=sys.stderr)
        return 2
    out = EVAL / "results" / args.run
    (out / args.variant).mkdir(parents=True, exist_ok=True)
    tests = [t for t in TESTS if not args.only or t["id"] in args.only]

    def one(test):
        path = out / args.variant / f"{test['id']:02d}.json"
        if path.exists() and json.loads(path.read_text())["outline"]:  # a failed one is tried again
            return json.loads(path.read_text())
        result = json.loads((EVAL / "results" / args.search / f"{test['id']:02d}.json").read_text())
        record = {"outline": None, "answer": None, "error": ""}
        text = sources(out, test, result)
        if not text:
            record["error"] = "no recommended source could be read"
        else:
            search = search_context(result) if args.variant == "new" else None
            try:
                outline = generate.make_outline(generate.Job("eval"), provider, text, test["level"], search=search) if search \
                    else generate.make_outline(generate.Job("eval"), provider, text, test["level"])
                record["outline"] = outline
                record["answer"] = generate.answers_question(test["query"], outline)
            except (generate.GenerationError, ProviderError) as e:
                record["error"] = str(e)
        path.write_text(json.dumps(record, indent=1, ensure_ascii=False))
        print(f"{test['id']:>2}. {test['query'][:50]:<50} {record['answer'] or 'FAILED ' + record['error'][:80]}", flush=True)
        return record

    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        records = list(pool.map(one, tests))
    rows = [score(t, r["outline"], r["answer"]) for t, r in zip(tests, records)]
    total = sum(r["prerequisites"] for r in rows)
    summary = {"variant": args.variant, "provider": provider.label, "searches": len(rows),
               "answers": sum(r["answer"] == "answers" for r in rows), "partly": sum(r["answer"] == "partly" for r in rows),
               "no": sum(r["answer"] == "no" for r in rows), "taught": sum(r["taught"] for r in rows),
               "accounted": sum(r["accounted"] for r in rows), "prerequisites": total,
               "order": sum(r["order"] for r in rows), "failed": sum(r["failed"] for r in rows)}
    (out / f"summary-{args.variant}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    for r in rows:
        print(f"{r['id']:>2}. {r['query'][:50]:<50} {r['answer'] or 'FAILED':<8} taught {r['taught']}/{r['prerequisites']}"
              f"  accounted {r['accounted']}/{r['prerequisites']}" + (f"  bridge {r['bridges']}" if r["bridges"] else "")
              + (f"  ORDER {r['order']}" if r["order"] else ""))
    print(f"\n{args.variant}: answers {summary['answers']}, partly {summary['partly']}, no {summary['no']} of {len(rows)}; "
          f"taught {summary['taught']}/{total}, accounted {summary['accounted']}/{total}; order problems {summary['order']}; failed {summary['failed']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
