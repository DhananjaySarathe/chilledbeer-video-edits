"""Speaker footage for graphics: frames cut from the edited base video, optionally with the background removed."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from shorts import config
from shorts.errors import ShortsError
from shorts.proc import run

PERSONSEG_SRC = Path(__file__).with_name("personseg.swift")
PERSONSEG_BIN = config.KIT / "bin" / "personseg"


def extract_frames(ffmpeg: str, video: str, start: float, duration: float, out_dir: Path,
                   fps: int = 30, width: int = 720) -> list[Path]:
    """JPEG frames of video[start, start+duration) at fps, scaled to width (height keeps 9:16)."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    run([ffmpeg, "-v", "error", "-y", "-ss", f"{start:.4f}", "-i", video, "-t", f"{duration:.4f}",
         "-vf", f"fps={fps},scale={width}:-2:flags=lanczos", "-q:v", "2", str(out_dir / "f%04d.jpg")],
        code="E_FRAMES", what="Extracting speaker frames")
    return sorted(out_dir.glob("f*.jpg"))


def ensure_personseg() -> Path:
    """Compile the macOS Vision cutout tool on first use (needs the Xcode command line tools)."""
    if PERSONSEG_BIN.exists() and PERSONSEG_BIN.stat().st_mtime >= PERSONSEG_SRC.stat().st_mtime:
        return PERSONSEG_BIN
    swiftc = shutil.which("swiftc")
    if not swiftc:
        raise ShortsError("E_CUTOUT", "swiftc is missing, so the person cutout tool cannot be built.",
                          "Install the command line tools: xcode-select --install")
    PERSONSEG_BIN.parent.mkdir(parents=True, exist_ok=True)
    run([swiftc, "-O", str(PERSONSEG_SRC), "-o", str(PERSONSEG_BIN)], code="E_CUTOUT", what="Building the cutout tool")
    return PERSONSEG_BIN


def cutout(frames_dir: Path, out_dir: Path) -> list[Path]:
    """PNG frames with the background transparent (macOS Vision person segmentation)."""
    tool = ensure_personseg()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    proc = subprocess.run([str(tool), str(frames_dir), str(out_dir)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise ShortsError("E_CUTOUT", f"Person cutout failed: {proc.stderr.strip()[-300:]}",
                          "Check the frames exist; the scene can use the uncut speaker instead.")
    return sorted(out_dir.glob("f*.png"))
