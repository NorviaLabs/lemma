"""Replace the gallery with the lessons rebuilt on 2026-10-23 through the subject-graph pipeline, and add the first
lesson built from a question ("Why does stress make you sick?"), without changing generated lesson content.

Each lesson comes from eval/results/gallery-2026-10-23/<slug>/ and is checked against its complete sources; the
gallery ships no source text. Galton is left as it is: it is the built-in example the tests are written against.
Nothing is written unless every lesson passes. Ids and gallery entries carry over from the lessons they replace.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lemma import lesson as L  # noqa: E402
from lemma.server import gallery_cover  # noqa: E402

RUN = ROOT / "eval/results/gallery-2026-10-23"
GALLERY = ROOT / "lemma/examples/gallery"
KEEP = {"galton-1886"}
NEW = {"stress-sickness": {"field": "Biology", "after": "wuhan-2020"}}


def main():
    index = json.loads((GALLERY / "index.json").read_text())
    for slug, entry in NEW.items():
        if not any(e["slug"] == slug for e in index):
            at = next(i for i, e in enumerate(index) if e["slug"] == entry["after"]) + 1
            index.insert(at, {"slug": slug, "field": entry["field"]})
    prepared = []
    for entry in index:
        slug = entry["slug"]
        if slug in KEEP:
            continue
        folder = RUN / slug
        record = json.loads((folder / "build.json").read_text())
        if record.get("status") != "done":
            raise SystemExit(f"{slug}: not rebuilt ({record.get('error', '')[:120]}); nothing published")
        lesson = json.loads((folder / "lesson.json").read_text())
        bundle = json.loads((folder / "sources.json").read_text())
        source = json.dumps({"lemma_sources": bundle}, ensure_ascii=False)
        if lesson.get("omitted") or not lesson.get("concepts"):
            raise SystemExit(f"{slug}: omitted or missing concepts; nothing published")
        if errors := list(L.check_lesson(lesson, source)):
            raise SystemExit(f"{slug}: fails against its full sources ({errors[0]}); nothing published")
        old_path = GALLERY / f"{slug}.json"
        if old_path.exists():
            old = json.loads(old_path.read_text())
            lesson["id"] = old["id"]
            lesson["source"]["url"] = lesson["source"].get("url") or old["source"].get("url", "")
        else:
            lesson["id"] = "gallery-" + slug
        links = {s["id"]: s.get("url") for s in bundle}
        for s in lesson.get("sources") or []:
            s["url"] = s.get("url") or links.get(s["id"], "")
        built_by = lesson["provider"]  # the model that wrote the concepts; the step and outline may have used another
        lesson["generation"] = dict(provider="chatgpt" if "gpt" in built_by["model"] else "claude", model=built_by["model"],
                                    source_chars=len(source), omitted=0,
                                    pipeline=("search question → " if record.get("question") else "brought sources → ")
                                    + "subjects + make_outline + build_lesson (2026-10-23)")
        entry["cover"] = gallery_cover(lesson)["id"]
        entry.pop("cover_values", None)
        entry.pop("source_file", None)
        prepared.append((slug, lesson))
    for slug, lesson in prepared:
        (GALLERY / f"{slug}.json").write_text(json.dumps(lesson, ensure_ascii=False, indent=1) + "\n")
        print(f"Published {slug}: {len(lesson['concepts'])} concepts, assumes {len(lesson['intro'].get('assumes') or [])}, "
              f"cover {next(e['cover'] for e in index if e['slug'] == slug)}")
    (GALLERY / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
