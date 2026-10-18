"""Regenerate the six gallery additions through Lemma's unmodified build pipeline.

Run with the project's Python and a Claude key in the macOS clipboard. The key is
read into memory only. Full source texts and resumable build evidence stay under
ignored eval/results/gallery-claude/. No lessons are published by this script.
"""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lemma import generate, ingest, lesson as L
from lemma.claude import ClaudeProvider
from lemma.llm import ProviderError

RUN = ROOT / "eval/results/gallery-claude"
SLUGS = ("turner-1893", "aquinas-senses", "mendel-1866", "brown-1954", "poe-red-death", "euclid-equilateral")
AUDIENCE = "A curious adult with no background in this field"


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


class RecordingJob(generate.Job):
    def __init__(self):
        super().__init__("gallery")
        self.problems = {}

    def update(self, sid, state, detail="", quiet=False, **extra):
        if extra.get("problems") and not quiet:
            self.problems.setdefault(sid, []).append(extra["problems"])
        super().update(sid, state, detail, quiet, **extra)


def main():
    key = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True).stdout.strip()
    if not key.startswith("sk-ant-") or any(c.isspace() for c in key):
        raise SystemExit("Clipboard does not contain a recognizable Claude API key.")
    provider = ClaudeProvider(key)
    RUN.mkdir(parents=True, exist_ok=True)
    failures = []
    for slug in SLUGS:
        folder = RUN / slug
        folder.mkdir(exist_ok=True)
        record_path = folder / "build.json"
        previous = json.loads(record_path.read_text()) if record_path.exists() else {}
        if previous.get("status") == "done" and not previous.get("omitted"):
            print(f"{slug}: already built; keeping recorded result", flush=True)
            continue
        existing = json.loads((ROOT / f"lemma/examples/gallery/{slug}.json").read_text())
        job = RecordingJob()
        started = time.time()
        record = dict(slug=slug, status="running", stage="ingest", provider="claude", model=provider.model)
        save(record_path, record)
        try:
            source_path = folder / "source.txt"
            if not source_path.exists():
                print(f"{slug}: ingesting complete source", flush=True)
                # Use the same saved-web-page ingestion path as a browser upload.
                # curl works with this environment's proxy; direct DNS resolution does not.
                download = subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location", "--max-time", "90", existing["source"]["url"]], capture_output=True)
                if download.returncode:
                    raise ingest.IngestError("Could not download the source page.")
                paper = ingest.from_html(download.stdout, url=existing["source"]["url"])
                if len(paper.text) < 500:
                    raise ingest.IngestError("Source too short for a complete reading.")
                source_path.write_text(paper.text)
                save(folder / "source-metadata.json", dict(url=paper.url, title=paper.title, kind=paper.kind, chars=len(paper.text)))
            text = source_path.read_text()
            print(f"{slug}: source ready ({len(text)} characters)", flush=True)
            outline_path = folder / "outline.json"
            record["stage"] = "outline"
            save(record_path, record)
            if outline_path.exists():
                outline = json.loads(outline_path.read_text())
                problems = generate.check_outline(outline, text, require_needs=True)
                if problems:
                    raise generate.GenerationError("Cached outline failed validation.")
            else:
                print(f"{slug}: Claude outlining", flush=True)
                outline = generate.make_outline(job, provider, text, AUDIENCE)
                save(outline_path, outline)
            record["stage"] = "build"
            save(record_path, record)
            print(f"{slug}: building {len(outline['concepts'])} concepts with normal repairs/checks", flush=True)
            built = generate.build_lesson(job, provider, dict(text=text, title=existing["source"]["title"], url=existing["source"]["url"]), outline, AUDIENCE, "gallery-" + slug)
            problems = list(L.check_lesson(built, text))
            if problems:
                raise generate.GenerationError("Generated lesson failed final validation.")
            save(folder / "lesson.json", built)
            omitted = built.get("omitted", [])
            record.update(status="incomplete" if omitted else "done", stage="done", concepts=len(built["concepts"]), omitted=omitted)
            if omitted:
                failures.append(slug)
            print(f"{slug}: built {len(built['concepts'])} validated concepts; {len(built.get('omitted', []))} omitted", flush=True)
        except (ingest.IngestError, generate.GenerationError, ProviderError) as error:
            # Keep provider diagnostics with the credential redacted for resumable runs.
            record.update(status="failed", error_type=type(error).__name__, error=str(error).replace(key, "[redacted]"), omitted=(job.lesson or {}).get("omitted", []))
            failures.append(slug)
            print(f"{slug}: {record['stage']} failed ({type(error).__name__}); no lesson published", flush=True)
        finally:
            record.update(seconds=round(time.time() - started), repairs=getattr(job, "repairs", {}), problems_fixed=job.problems)
            save(record_path, record)
    if failures:
        raise SystemExit("Incomplete: " + ", ".join(failures))


if __name__ == "__main__":
    main()
