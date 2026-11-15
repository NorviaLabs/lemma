"""The shipped example and gallery lessons, read-only, and their cards."""

from __future__ import annotations

import re

from .core import EXAMPLES, GALLERY, _stamp, ensure_checked, gallery_index, load_example, load_gallery, route


def _example_key():
    return ("example", _stamp(EXAMPLES.joinpath("gallery/galton-1886.json")), _stamp(EXAMPLES.joinpath("galton-1886.txt")))


def _gallery_key(slug: str):
    entry = next((e for e in gallery_index() if e["slug"] == slug), {})
    return ("gallery", slug, _stamp(GALLERY.joinpath(f"{slug}.json")), _stamp(EXAMPLES.joinpath(entry["source_file"])) if entry.get("source_file") else None)


@route("GET", r"/api/example")
def api_example(req):
    lesson, source = load_example()
    ensure_checked(lambda: (lesson, source), _example_key())  # never show a lesson that fails its checks, even ours
    return lesson


def card_quote(quote: str | None, most: int = 32) -> str | None:
    """A verbatim run of whole sentences from a quote, short enough to set large on a gallery card. Headings under
    five words ("Article 1.") before the first sentence are skipped, and the run stops at the next one ("Objection
    1."), so the card never joins sentences that aren't side by side; a long sentence is cut with an ellipsis."""
    if not quote:
        return quote
    sentences = re.split(r"(?<=[.!?;])\s+", quote.strip())
    while len(sentences) > 1 and len(sentences[0].split()) < 5:
        sentences.pop(0)
    words = []
    for s in sentences:
        if words and (len(s.split()) < 5 or len(words) + len(s.split()) > most):
            break
        words += s.split()
    return " ".join(words[:most]).rstrip(",;:") + ("…" if len(words) > most else "")


def short_authors(authors: str | None) -> str:
    """Authors as a card credits them: a single author in full, two by surname, more as "First et al."
    Notes in brackets (translators, commentary) are dropped, and where a part names who wrote the words
    ("opinion delivered by Chief Justice Earl Warren"), that person is credited."""
    text = re.sub(r"\s*\([^)]*\)", "", authors or "").strip()
    parts = [p.strip() for p in text.split(";") if p.strip()]
    by = [p.rsplit(" by ", 1)[1] for p in parts if " by " in p]
    text = by[-1] if by else (parts[0] if parts else "")
    etal = bool(re.search(r"\bet al\.?", text))
    names = [n for n in re.split(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*", re.sub(r",?\s*\bet al\.?", "", text)) if n.strip()]
    if not names:
        return ""
    if len(names) == 1 and not etal:
        return names[0]
    def surname(name):  # the last word that isn't initials, with a particle such as "von" kept; capitals tamed
        words = name.split()
        keep = [i for i, w in enumerate(words) if not re.fullmatch(r"[A-Z]{1,3}\.?|(?:[A-Z]\.-?)+[A-Z]?\.?", w)]
        i = keep[-1] if keep else 0
        word = words[i].title() if words[i].isupper() else words[i]
        return f"{words[i - 1]} {word}" if i > 0 and words[i - 1] in ("von", "van", "de", "der", "da", "di", "le", "la") else word
    return f"{surname(names[0])} and {surname(names[1])}" if len(names) == 2 and not etal else f"{surname(names[0])} et al."


def quote_author(lesson: dict, block: dict) -> str:
    """Who wrote a quote: its own source in a combined lesson, otherwise the lesson's source."""
    source = next((s for s in lesson.get("sources") or [] if s.get("id") == block.get("source_id")), None)
    return short_authors((source or {}).get("authors") or lesson["source"].get("authors"))


def gallery_cover(lesson: dict) -> dict:
    """The concept a gallery card shows: the first with a model to draw; without models, the one with the
    shortest quote, which the card sets as a poster."""
    with_model = [c for c in lesson["concepts"] if c.get("model")]
    return with_model[0] if with_model else min(lesson["concepts"], key=lambda c: len(c["understand"].get("quote") or "x" * 9999))


@route("GET", r"/api/gallery", shared=True)
def api_gallery(req):
    items = []
    for entry in gallery_index():
        lesson, _ = load_gallery(entry["slug"])
        cover = next((c for c in lesson["concepts"] if c["id"] == entry.get("cover")), None) or gallery_cover(lesson)
        items.append({**lesson["gallery"], "title": lesson["title"], "source": lesson["source"],
                      "concepts": [c["title"] for c in lesson["concepts"]],
                      "cover": {"title": cover["title"], "idea": cover["idea"], "model": cover.get("model"),
                                "quote": card_quote(cover["understand"].get("quote")), "quote_author": quote_author(lesson, cover["understand"]),
                                "values": entry.get("cover_values", {})}})
    return items


@route("GET", r"/api/gallery/([a-z0-9-]{1,64})", shared=True)
def api_gallery_lesson(req, slug):
    lesson, source = load_gallery(slug)
    ensure_checked(lambda: (lesson, source), _gallery_key(slug))  # once per version, not per visitor
    return lesson
