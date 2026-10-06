"""Run external tools (ffmpeg, whisper-cli) and turn failures into ShortsError."""
from __future__ import annotations

import subprocess
from pathlib import Path

from shorts.errors import ShortsError


def run(cmd: list[str], *, code: str, what: str, cwd: Path | None = None,
        log: Path | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(" ".join(cmd) + "\n\n" + proc.stderr)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise ShortsError(code, f"{what} failed (exit {proc.returncode}): {tail}",
                          f"Full log: {log}" if log else "Re-run the command to see the full error.")
    return proc
