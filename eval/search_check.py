"""Run the 25 labelled searches in eval/searches.json through Lemma's real search and score what it finds.

    set -a; . ./deploy/lemma.env; set +a          # TYPESAFE_API_KEY: every search asks Jev
    uv run python eval/search_check.py --provider chatgpt --model gpt-6.1-sol
    uv run python eval/search_check.py --fields      # only the field step: one Jev call per search, no provider
    LEMMA_PROVIDER_KEY=... uv run python eval/search_check.py --provider claude   # a provider with a key

It costs money: each search is one short call on the provider you name (under your key or subscription) and
one Jev ranking on the server's TypeSafe key. Results are saved to eval/results/search-<date>/, and a saved
search isn't run again, so a rerun only rescores.

A labelled prerequisite counts as found when one of its names appears, as whole words, in a result's title.
The stage passes when the results hold at least 56 of the 69 prerequisites (the stage-0 prototype's articles),
search 5 (Advanced) finds at least one of its own, and no off-topic subject is recommended.

A field is right when the first one picked is among the labelled fields; a bridge also needs both fields picked,
and both labelled. The field step passes at FIELD_BAR of 25 with every bridge right.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from lemma import categorize, search
from lemma.llm import make_provider

EVAL = Path(__file__).parent
TESTS = json.loads((EVAL / "searches.json").read_text())["searches"]
BAR = 56  # prerequisites the stage-0 prototype's resolved articles found
FIELD_BAR = 22


def _words(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9]+", text.lower().replace("'s", ""))) + " "


def found(names: list[str], titles: list[str]) -> bool:
    return any(_words(n) in _words(t) for n in names for t in titles)


def score(test: dict, result: dict) -> dict:
    titles = [r["title"] for r in result["results"]]
    chosen = [r["title"] for r in result["results"] if r.get("recommended")]
    pre = test["prerequisites"]
    return {"id": test["id"], "query": test["query"], "level": test["level"], "prerequisites": len(pre),
            "in_results": sum(found(p, titles) for p in pre), "recommended": sum(found(p, chosen) for p in pre),
            "off_topic_recommended": [o for o in test["off_topic"] if found([o], chosen)],
            "terms": result.get("plan", {}).get("terms", []), "unavailable": result.get("unavailable", [])}


def field_right(test: dict, field: dict) -> bool:
    if test["kind"] == "bridge":
        return field["kind"] == "both" and set(field["ids"]) <= set(test["fields"])
    return field["ids"][0] in test["fields"]


def fields(out: Path) -> int:
    """The field step alone, saved to fields.json; a saved run is rescored, not rerun."""
    path = out / "fields.json"
    picked = json.loads(path.read_text()) if path.exists() else {}
    right = bridges = 0
    for test in TESTS:
        if str(test["id"]) not in picked:
            try:
                picked[str(test["id"])] = categorize.question_field(test["query"])
            except categorize.CategorizeError as e:
                print(f"{test['id']:>2}. FAILED  {e}", flush=True)
                continue
            path.write_text(json.dumps(picked, indent=1))
        field = picked[str(test["id"])]
        ok = field_right(test, field)
        right += ok
        bridges += ok and test["kind"] == "bridge"
        print(f"{test['id']:>2}. {test['query'][:50]:<50} {'ok   ' if ok else 'WRONG'} {'+'.join(field['ids']):<34} "
              f"labelled {'/'.join(test['fields'])} ({test['kind']})", flush=True)
    total_bridges = sum(t["kind"] == "bridge" for t in TESTS)
    print(f"\nfields right {right}/{len(TESTS)} (bar {FIELD_BAR}), bridges {bridges}/{total_bridges}")
    passed = len(picked) == len(TESTS) and right >= FIELD_BAR and bridges == total_bridges
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--provider", help="claude, openai, opencode or chatgpt")
    ap.add_argument("--fields", action="store_true", help="run only the field step (Jev, no provider)")
    ap.add_argument("--model", default="")
    ap.add_argument("--run", default="search-" + time.strftime("%Y-%m-%d"))
    args = ap.parse_args()
    out = EVAL / "results" / args.run
    out.mkdir(parents=True, exist_ok=True)
    if args.fields:
        return fields(out)
    if not args.provider:
        ap.error("--provider is needed unless --fields")
    provider = make_provider(args.provider, os.environ.get("LEMMA_PROVIDER_KEY", ""), args.model)
    ok, why = provider.available()
    if not ok:
        print(why, file=sys.stderr)
        return 2
    rows = []
    for test in TESTS:
        path = out / f"{test['id']:02d}.json"
        if not path.exists():
            try:
                result = search.search(test["query"], test["level"], provider)
            except search.SearchError as e:
                print(f"{test['id']:>2}. FAILED  {e}", flush=True)
                continue
            path.write_text(json.dumps(result, indent=1))
        row = score(test, json.loads(path.read_text()))
        rows.append(row)
        print(f"{row['id']:>2}. {row['query'][:50]:<50} {row['level']:<12} results {row['in_results']}/{row['prerequisites']}"
              f"  recommended {row['recommended']}/{row['prerequisites']}"
              + (f"  OFF-TOPIC {row['off_topic_recommended']}" if row["off_topic_recommended"] else ""), flush=True)
    total = sum(r["prerequisites"] for r in rows)
    in_results, recommended = sum(r["in_results"] for r in rows), sum(r["recommended"] for r in rows)
    advanced = next((r for r in rows if r["id"] == 5), None)
    off = sum(len(r["off_topic_recommended"]) for r in rows)
    summary = {"provider": provider.label, "searches": len(rows), "prerequisites": total, "in_results": in_results,
               "recommended": recommended, "advanced_found": advanced and advanced["in_results"], "off_topic_recommended": off}
    (out / "summary.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(f"\nprerequisites in results {in_results}/{total} (bar {BAR}), recommended {recommended}/{total}, "
          f"search 5 (Advanced) {summary['advanced_found']}/3, off-topic recommended {off}")
    passed = len(rows) == len(TESTS) and in_results >= BAR and (advanced or {}).get("in_results", 0) > 0 and off == 0
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
