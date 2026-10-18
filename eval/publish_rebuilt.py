"""Replace the gallery with the lessons rebuilt on 2026-10-19, without changing generated lesson content.

Each lesson is checked against its complete source, then against the quotation excerpts the gallery ships.
Galton is left as it is: it is the built-in example the tests are written against. Nothing is written unless
every lesson passes. Links, ids and gallery entries carry over from the lessons they replace.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lemma import lesson as L
from lemma.server import gallery_cover
from normalize_gallery_sources import quotation_excerpts

RUN = ROOT / "eval/results/rebuilt-2026-10-19/papers"
EXAMPLES = ROOT / "lemma/examples"
GALLERY = EXAMPLES / "gallery"
PAPERS = {"attention-2017": "01", "ioannidis-2005": "21", "wuhan-2020": "25", "opinion-dynamics-2002": "45",
          "gettier-1963": "50", "turner-1893": "turner_1893",
          "aquinas-senses": "aquinas_senses", "mendel-1866": "mendel_1866", "brown-1954": "brown_1954",
          "poe-red-death": "poe_red_death", "euclid-equilateral": "euclid_equilateral",
          "wave-interference": "wave_interference", "schelling-segregation": "schelling_segregation",
          "information-cascades": "information_cascades", "ice-albedo-feedback": "ice_albedo_feedback",
          "externalities-pigou": "externalities_pigou", "loss-aversion": "loss_aversion"}


def main():
    index = json.loads((GALLERY / "index.json").read_text())
    prepared = []
    for entry in index:
        slug = entry["slug"]
        if slug not in PAPERS:
            continue
        folder = RUN / PAPERS[slug]
        lesson = json.loads((folder / "lesson.json").read_text())
        source = (folder / "source.txt").read_text()
        if lesson.get("omitted") or not lesson.get("concepts"):
            raise SystemExit(f"{slug}: omitted or missing concepts; nothing published")
        if errors := list(L.check_lesson(lesson, source)):
            raise SystemExit(f"{slug}: fails against its full source ({errors[0]}); nothing published")
        old = json.loads((GALLERY / f"{slug}.json").read_text())
        lesson["id"] = old["id"]
        lesson["source"]["url"] = lesson["source"].get("url") or old["source"].get("url", "")
        links = {s["id"]: s.get("url") for s in old.get("sources") or []}
        for s in lesson.get("sources") or []:
            s["url"] = s.get("url") or links.get(s["id"], "")
        lesson["generation"] = dict(provider="claude", model="claude-opus-5-5", pipeline="lemma.generate.make_outline + build_lesson",
                                    source_chars=len(source), omitted=0)
        shipped = quotation_excerpts(lesson, source)
        if errors := list(L.check_lesson(lesson, shipped)):
            raise SystemExit(f"{slug}: fails against the source it ships with ({errors[0]}); nothing published")
        entry["cover"] = gallery_cover(lesson)["id"]
        entry.pop("cover_values", None)
        prepared.append((slug, lesson, shipped, entry["source_file"]))
    for slug, lesson, shipped, source_file in prepared:
        (GALLERY / f"{slug}.json").write_text(json.dumps(lesson, ensure_ascii=False, indent=1) + "\n")
        (EXAMPLES / source_file).write_text(shipped, encoding="utf-8")
        print(f"Published {slug}: {len(lesson['concepts'])} concepts, cover {next(e['cover'] for e in index if e['slug'] == slug)}")
    (GALLERY / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
