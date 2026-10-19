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


def write_private(path: Path, data: str):
    """Writes a file only this user can read."""
    _write(path, data, private=True)


# ---------------------------------------------------------------- library


def library(owner: str | None = None) -> Path:
    """Each account's library (see auth.py). Tools that work outside any account, such as eval/run.py, use `None`."""
    if owner is None:
        return home() / "library"
    if not ID_RE.match(owner):
        raise KeyError(owner)
    lib = home() / "users" / owner / "library"
    lib.mkdir(parents=True, exist_ok=True)
    return lib


def _paths(lesson_id: str, owner: str | None = None) -> tuple[Path, Path]:
    if not ID_RE.match(lesson_id or ""):
        raise KeyError(lesson_id)
    lib = library(owner)
    return lib / f"{lesson_id}.json", lib / f"{lesson_id}.source.txt"


def save_lesson(lesson: dict, source_text: str | None, owner: str | None = None):
    jp, sp = _paths(lesson["id"], owner)
    _write(jp, json.dumps(lesson, ensure_ascii=False, indent=1))
    if source_text is not None:
        _write(sp, source_text)


def load_lesson(lesson_id: str, owner: str | None = None) -> tuple[dict, str | None]:
    jp, sp = _paths(lesson_id, owner)
    lesson = json.loads(jp.read_text(encoding="utf-8"))
    src = sp.read_text(encoding="utf-8") if sp.exists() else None
    return lesson, src


def delete_lesson(lesson_id: str, owner: str | None = None):
    for p in _paths(lesson_id, owner):
        p.unlink(missing_ok=True)


def _category_name(lesson: dict) -> str:
    """The subject a built lesson was sorted into (see categorize.py), or "" for one saved before categories."""
    category = lesson.get("category")
    primary = category.get("primary") if isinstance(category, dict) else None
    name = primary.get("name") if isinstance(primary, dict) else None
    return name if isinstance(name, str) else ""


def list_lessons(owner: str | None = None) -> list[dict]:
    out = []
    for p in sorted(library(owner).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            l = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({
            "id": l.get("id", p.stem),
            "title": l.get("title", ""),
            "source": (l.get("source") or {}).get("title", ""),
            "concepts": len(l.get("concepts") or []),
            "category": _category_name(l),
            "saved": p.stat().st_mtime,
        })
    return out


def adopt_unowned(owner: str):
    """Moves lessons and build requests saved before this computer had accounts into its owner's account, once.

    Anything already in the account with the same name wins, so signing in again never overwrites."""
    for name in ("library", "requests"):
        old = home() / name
        if not old.is_dir():
            continue
        new = library(owner) if name == "library" else requests(owner)
        for path in old.iterdir():
            if path.is_file() and not (new / path.name).exists():
                path.replace(new / path.name)
        try:
            old.rmdir()
        except OSError:
            pass  # something stayed behind; it is left where it was


def requests(owner: str | None = None) -> Path:
    path = library(owner).parent / "requests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def request_path(rid: str, owner: str | None = None) -> Path:
    if not ID_RE.fullmatch(rid or ""):
        raise KeyError(rid)
    return requests(owner) / f"{rid}.json"


def save_request(record: dict, owner: str | None = None):
    write_private(request_path(record["id"], owner), json.dumps(record, ensure_ascii=False))


def load_request(rid: str, owner: str | None = None) -> dict:
    return json.loads(request_path(rid, owner).read_text(encoding="utf-8"))


def list_requests(owner: str | None = None) -> list[dict]:
    records = []
    for path in requests(owner).glob("*.json"):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(records, key=lambda r: r.get("created", 0), reverse=True)
