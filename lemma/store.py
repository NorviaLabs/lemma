"""The lesson library."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def home() -> Path:
    p = Path(os.environ.get("LEMMA_HOME") or Path.home() / ".lemma")
    (p / "library").mkdir(parents=True, exist_ok=True)
    return p


def _write(path: Path, data: str, private: bool = False):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        if private:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------- library


def _paths(lesson_id: str) -> tuple[Path, Path]:
    if not ID_RE.match(lesson_id or ""):
        raise KeyError(lesson_id)
    lib = home() / "library"
    return lib / f"{lesson_id}.json", lib / f"{lesson_id}.source.txt"


def save_lesson(lesson: dict, source_text: str | None):
    jp, sp = _paths(lesson["id"])
    _write(jp, json.dumps(lesson, ensure_ascii=False, indent=1))
    if source_text is not None:
        _write(sp, source_text)


def load_lesson(lesson_id: str) -> tuple[dict, str | None]:
    jp, sp = _paths(lesson_id)
    lesson = json.loads(jp.read_text(encoding="utf-8"))
    src = sp.read_text(encoding="utf-8") if sp.exists() else None
    return lesson, src


def delete_lesson(lesson_id: str):
    for p in _paths(lesson_id):
        p.unlink(missing_ok=True)


def list_lessons() -> list[dict]:
    out = []
    for p in sorted((home() / "library").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            l = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({
            "id": l.get("id", p.stem),
            "title": l.get("title", ""),
            "source": (l.get("source") or {}).get("title", ""),
            "concepts": len(l.get("concepts") or []),
            "saved": p.stat().st_mtime,
        })
    return out
