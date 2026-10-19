"""Publish completed Claude gallery builds without changing generated lesson content.

Adds only the explicit player activity sequence used by the original six gallery
lessons. Quotes are rechecked against the complete ingested source before writing.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lemma import lesson as L

RUN = ROOT / "eval/results/gallery-claude"
GALLERY = ROOT / "lemma/examples/gallery"
SLUGS = ("turner-1893", "aquinas-senses", "mendel-1866", "brown-1954", "poe-red-death", "euclid-equilateral")


def activity_sequence(concept):
    sequence = []
    for kind, narration in (("watch", concept.get("animation")), ("walk", concept.get("understand", {}).get("walkthrough"))):
        if narration and narration.get("steps"):
            sequence.append(dict(id=kind, kind=kind))
    sequence.append(dict(id="explain", kind="explain"))
    sequence.extend(dict(id=f"goal_{i}", kind="goal", i=i) for i, _ in enumerate(concept["explore"]["goals"]))
    sequence.extend((dict(id="predict", kind="predict"), dict(id="reveal", kind="reveal")))
    if concept.get("check"):
        sequence.append(dict(id="check", kind="check"))
    sequence.append(dict(id="connect", kind="connect"))
    return sequence


def main():
    index = json.loads((GALLERY / "index.json").read_text())
    prepared = []
    for slug in SLUGS:
        folder = RUN / slug
        record = json.loads((folder / "build.json").read_text())
        if record.get("status") != "done" or record.get("omitted"):
            raise SystemExit(f"{slug}: incomplete build; no lessons published")
        lesson = json.loads((folder / "lesson.json").read_text())
        source = (folder / "source.txt").read_text()
        if lesson.get("omitted") or not lesson.get("concepts"):
            raise SystemExit(f"{slug}: omitted or missing concepts; no lessons published")
        errors = list(L.check_lesson(lesson, source))
        if errors:
            raise SystemExit(f"{slug}: generated validation failed; no lessons published")
        for concept in lesson["concepts"]:
            concept["activities"] = activity_sequence(concept)
        errors = list(L.check_lesson(lesson, source))
        if errors:
            raise SystemExit(f"{slug}: sequence validation failed; no lessons published")
        metadata = json.loads((folder / "source-metadata.json").read_text())
        lesson["source"]["url"] = metadata["url"]
        lesson["generation"] = dict(provider=record["provider"], model=record["model"], pipeline="lemma.generate.make_outline + build_lesson", source_chars=len(source), omitted=0)
        prepared.append((slug, lesson))
        entry = next(e for e in index if e["slug"] == slug)
        entry["cover"] = lesson["concepts"][0]["id"]
        entry.pop("cover_values", None)
        entry.pop("source_file", None)  # checked against its full source above; the gallery ships no source text
    for slug, lesson in prepared:
        (GALLERY / f"{slug}.json").write_text(json.dumps(lesson, ensure_ascii=False, indent=1) + "\n")
        print(f"Published {slug}: {len(lesson['concepts'])} Claude-generated live-model concepts")
    (GALLERY / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
