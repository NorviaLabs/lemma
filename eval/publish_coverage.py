"""Publish the coverage lessons, built in Lemma from several sources each, to the gallery.

Usage: python eval/publish_coverage.py <LEMMA_HOME that built them>

Reads each finished build and its saved lesson from that Lemma's library, without changing generated content: it
adds only the player's activity sequence, the gallery id and generation metadata. Every lesson is checked against
its complete sources before anything is written; the full sources are kept in ignored eval/results/gallery-coverage/
so normalize_gallery_sources.py can recreate the excerpts. Makes no provider calls.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lemma import lesson as L
from normalize_gallery_sources import quotation_excerpts
from publish_gallery import activity_sequence

GALLERY = ROOT / "lemma/examples/gallery"
RUN = ROOT / "eval/results/gallery-coverage"
LESSONS = {  # build title in Lemma: (gallery slug, field shown in the gallery)
    "Wave interference": ("wave-interference", "Physics"),
    "Schelling's model of segregation": ("schelling-segregation", "Urban studies"),
    "Information cascades": ("information-cascades", "Social learning"),
    "Ice–albedo feedback": ("ice-albedo-feedback", "Climate science"),
    "Externalities and Pigouvian taxes": ("externalities-pigou", "Economics"),
    "Loss aversion": ("loss-aversion", "Behavioural economics"),
}


def main(home: Path):
    index = json.loads((GALLERY / "index.json").read_text())
    builds = {r["title"]: r for r in (json.loads(p.read_text()) for p in (home / "requests").glob("*.json"))}
    prepared = []
    for title, (slug, field) in LESSONS.items():
        record = builds[title]
        if record.get("status") != "done":
            raise SystemExit(f"{slug}: build is {record.get('status')}; no lessons published")
        lesson = json.loads((home / f"library/{record['id']}.json").read_text())
        source = (home / f"library/{record['id']}.source.txt").read_text()
        if errors := list(L.check_lesson(lesson, source)):
            raise SystemExit(f"{slug}: generated validation failed ({errors[0]}); no lessons published")
        for concept in lesson["concepts"]:
            concept["activities"] = activity_sequence(concept)
        lesson["id"] = f"gallery-{slug}"
        provider = lesson["provider"]
        lesson["generation"] = dict(provider="claude", model=provider["model"], pipeline="lemma.generate.make_outline + build_lesson",
                                    source_chars=sum(len(s["text"]) for s in L.source_map(source).values()), omitted=len(lesson["omitted"]))
        if errors := list(L.check_lesson(lesson, source)):
            raise SystemExit(f"{slug}: sequence validation failed ({errors[0]}); no lessons published")
        excerpts = quotation_excerpts(lesson, source)
        if errors := list(L.check_lesson(lesson, excerpts)):
            raise SystemExit(f"{slug}: excerpt validation failed ({errors[0]}); no lessons published")
        prepared.append((slug, lesson, source, excerpts))
        index = [e for e in index if e["slug"] != slug]
        index.append(dict(slug=slug, field=field, cover=lesson["concepts"][0]["id"], source_file=f"sources/{slug}.txt"))
    for slug, lesson, source, excerpts in prepared:
        (RUN / slug).mkdir(parents=True, exist_ok=True)
        (RUN / slug / "source.txt").write_text(source)
        (GALLERY / f"{slug}.json").write_text(json.dumps(lesson, ensure_ascii=False, indent=1) + "\n")
        (ROOT / f"lemma/examples/sources/{slug}.txt").write_text(excerpts)
        print(f"Published {slug}: {len(lesson['concepts'])} concepts from {len(L.source_map(source))} sources, {len(lesson['omitted'])} left out")
    (GALLERY / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
