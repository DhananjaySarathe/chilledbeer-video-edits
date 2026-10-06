"""A job is one take's workspace, split by how long each file is worth keeping:

    output/jobs/<name>/    probe/analysis/brief/style/decisions/resolutions/edit/visuals/check JSON + source.mp4 (keep)
    output/temp/jobs/<name>/   audio, whisper output, graphics frames, captions, preview, contact sheets, logs (delete any time)
    output/final/<name>/   final.mp4 + final_contact.png (the deliverable)

A take made before this layout (jobs/<name>/ with everything inside, work/ included) keeps working where it is.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from shorts import config
from shorts.errors import ShortsError

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
STEP_FILES = [
    ("probe", "probe.json"), ("analyze", "analysis.json"), ("brief", "brief.json"), ("style", "style.json"),
    ("decide", "decisions.json"), ("plan", "edit.json"), ("preview", "preview.mp4"), ("render", "final.mp4"),
    ("check", "check.json"),
]


class Job:
    def __init__(self, name: str, root: Path | None = None):
        if not NAME_RE.match(name):
            raise ShortsError("E_JOB_NAME", f"Invalid job name {name!r}.",
                              "Use lowercase letters, digits, '-' and '_' (max 64 characters).")
        self.name = name
        legacy = config.LEGACY_JOBS / name
        self.legacy = root is None and legacy.is_dir() and not (config.JOBS / name).is_dir()
        if self.legacy:
            self.dir, self.work, self.final_dir = legacy, legacy / "work", legacy
        else:
            self.dir = (root if root is not None else config.JOBS) / name
            self.work = config.TEMP / "jobs" / name
            self.final_dir = config.FINAL / name
        self.source = self.work / "source.mp4" if self.legacy else self.dir / "source.mp4"
        self.final = self.final_dir / "final.mp4"
        self.preview = self.work / "preview.mp4"

    @classmethod
    def create(cls, name: str, root: Path | None = None) -> "Job":
        job = cls(name, root)
        job.dir.mkdir(parents=True, exist_ok=True)
        job.work.mkdir(parents=True, exist_ok=True)
        return job

    @classmethod
    def open(cls, name: str, root: Path | None = None) -> "Job":
        job = cls(name, root)
        if not job.dir.is_dir():
            raise ShortsError("E_NO_JOB", f"Job {name!r} does not exist.",
                              "Start one with: shorts probe <video> --job NAME")
        job.work.mkdir(parents=True, exist_ok=True)     # output/temp may have been deleted since
        return job

    def path(self, rel: str) -> Path:
        return self.dir / rel

    def has(self, rel: str) -> bool:
        return (self.dir / rel).exists()

    def read(self, rel: str) -> dict:
        p = self.dir / rel
        if not p.exists():
            raise ShortsError("E_MISSING_FILE", f"{rel} not found in job {self.name}.",
                              f"Run the earlier steps first (see: shorts status {self.name}).")
        return json.loads(p.read_text())

    def write(self, rel: str, data) -> Path:
        return write_json(self.dir / rel, data)

    def read_work(self, rel: str) -> dict:
        return json.loads((self.work / rel).read_text())

    def write_work(self, rel: str, data) -> Path:
        return write_json(self.work / rel, data)

    @contextmanager
    def timed(self, step: str):
        t0 = time.perf_counter()
        yield
        timings = self.read("timings.json") if self.has("timings.json") else {}
        timings[step] = round(time.perf_counter() - t0, 3)
        self.write("timings.json", timings)

    def status(self) -> dict:
        where = {"preview.mp4": self.preview, "final.mp4": self.final}
        done = {step: (where[f] if f in where else self.dir / f).exists() for step, f in STEP_FILES}
        return {"job": self.name, "dir": str(self.dir), "temp": str(self.work), "final": str(self.final_dir),
                "done": done, "next": next((s for s, ok in done.items() if not ok), None)}


def write_json(p: Path, data) -> Path:
    """Write JSON atomically (a crash never leaves half a file)."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=p.suffix)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)
    return p


def add_command(sub) -> None:
    p = sub.add_parser("status", help="Show which steps are done for a job.")
    p.add_argument("job")
    p.set_defaults(func=lambda a: Job.open(a.job).status())
