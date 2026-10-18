"""Normalize all non-Galton gallery source files to verified quotation excerpts.

The full ingested source must be available locally in the original evaluation run.
This command makes no network or provider calls and validates before writing.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lemma import lesson as L

PILOT_IDS = {"attention-2017": 1, "ioannidis-2005": 21, "wuhan-2020": 25,
             "opinion-dynamics-2002": 45, "gettier-1963": 50}


HEADER = "VERIFIED QUOTATION EXCERPTS — not the complete source."


def quotation_excerpts(lesson, source=None):
    """The lesson's quotes with where they come from. A multi-source lesson keeps its source bundle, each source
    holding only the quotes attributed to it, so attribution is still checked."""
    blocks = [*(lesson.get("primer") or []), *(c["understand"] for c in lesson["concepts"])]
    sources = L.source_map(source)
    if not sources:
        parts = [HEADER, lesson["source"]["title"], lesson["source"]["url"]]
        for block in blocks:
            if block.get("quote"):
                parts.extend((block.get("quote_where", ""), block["quote"]))
        return "\n\n".join(parts) + "\n"
    bundle = []
    for sid, s in sources.items():
        parts = [HEADER, s["title"], s["url"]]
        for block in blocks:
            if block.get("quote") and block.get("source_id") == sid:
                parts.extend((block.get("quote_where", ""), block["quote"]))
        bundle.append({**s, "text": "\n\n".join(parts) + "\n"})
    return json.dumps({"lemma_sources": bundle}, ensure_ascii=False) + "\n"  # unindented: how source_map recognises a bundle


def main():
    examples = ROOT / "lemma/examples"
    index_path = examples / "gallery/index.json"
    index = json.loads(index_path.read_text())
    prepared = []
    for entry in index:
        slug = entry["slug"]
        if slug == "galton-1886":
            continue
        lesson = json.loads((examples / f"gallery/{slug}.json").read_text())
        if slug in PILOT_IDS:
            source_path = ROOT / f"eval/results/pilot-claude/papers/{PILOT_IDS[slug]:02d}/source.txt"
        elif (ROOT / f"eval/results/gallery-coverage/{slug}/source.txt").exists():
            source_path = ROOT / f"eval/results/gallery-coverage/{slug}/source.txt"
        else:
            source_path = ROOT / f"eval/results/gallery-claude/{slug}/source.txt"
        source = source_path.read_text()
        errors = list(L.check_lesson(lesson, source))
        if errors:
            raise SystemExit(f"{slug}: original-source validation failed: {errors[0]}")
        excerpts = quotation_excerpts(lesson, source)
        errors = list(L.check_lesson(lesson, excerpts))
        if errors:
            raise SystemExit(f"{slug}: excerpt validation failed: {errors[0]}")
        entry["source_file"] = f"sources/{slug}.txt"
        prepared.append((examples / entry["source_file"], excerpts))
    for path, text in prepared:
        path.write_text(text, encoding="utf-8")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Normalized {len(prepared)} verified gallery source files; Galton unchanged.")


if __name__ == "__main__":
    main()
