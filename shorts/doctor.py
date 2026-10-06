"""`shorts doctor`: is everything the pipeline needs installed?"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from shorts import config
from shorts import fonts as fontmod

FILTERS = ("subtitles", "loudnorm", "zscale", "ebur128", "blackdetect", "freezedetect")


def doctor() -> dict:
    checks: list[dict] = []

    def add(name: str, ok, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    for tool, formula in (("ffmpeg", "ffmpeg"), ("ffprobe", "ffmpeg"), ("whisper-cli", "whisper-cpp")):
        path = shutil.which(tool)
        add(tool, path, path or f"brew install {formula}")
    if shutil.which("ffmpeg"):
        filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        for f in FILTERS:
            add(f"ffmpeg filter {f}", re.search(rf"\s{f}\s", filters))
        encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        add("ffmpeg encoder h264_videotoolbox", "h264_videotoolbox" in encoders)
    hf = shutil.which("hyperframes")
    hf_v = subprocess.run([hf, "--version"], capture_output=True, text=True).stdout.strip() if hf else ""
    add(f"hyperframes {config.HYPERFRAMES_VERSION}", hf_v == config.HYPERFRAMES_VERSION,
        hf_v or f"npm install -g hyperframes@{config.HYPERFRAMES_VERSION}")
    for p in (config.WHISPER_MODEL, config.ALIGN_MODEL, config.ALIGN_VOCAB, config.FACE_MODEL, config.TURN_MODEL, config.VAD_MODEL):
        add(f"model {p.name}", p.is_file(), f"{p.stat().st_size / 1e6:.1f} MB" if p.is_file() else "run: shorts setup")
    for name in ("personseg", "ocrboxes"):
        add(f"tool {name}", (config.BIN / name).is_file(), "" if (config.BIN / name).is_file() else "run: shorts setup")
    chrome = Path("/Applications/Google Chrome.app")
    add("Google Chrome", chrome.exists(), "renders graphics and HyperFrames" if chrome.exists() else "install Google Chrome")
    audio = [p for p in (config.KIT / "music").rglob("*.mp3")] + [p for p in (config.KIT / "sfx").rglob("*.wav")]
    add("music + sfx library", len(audio) >= 60, f"{len(audio)} files" if len(audio) >= 60 else
        f"{len(audio)} files: run python3 kit/assets_src/fetch.py")
    found = fontmod.available()
    add("fonts", len(found) >= 4, ", ".join(found) or "run: shorts setup")
    add("TYPESAFE_API_KEY (optional)", True, "present: Jev picks zoom-ins and drafts graphics" if config.jev_enabled()
        else "not set: fine, Claude picks zoom-ins and graphics (README: Jev is optional)")
    versions = {}                                   # compare two machines: same versions -> same output
    if shutil.which("ffmpeg"):
        versions["ffmpeg"] = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.split()[2]
    if shutil.which("brew"):
        w = subprocess.run(["brew", "list", "--versions", "whisper.cpp"], capture_output=True, text=True).stdout.split()
        versions["whisper.cpp"] = w[-1] if w else ""
    if hf_v:
        versions["hyperframes"] = hf_v
    return {"passed": all(c["ok"] for c in checks), "checks": checks, "versions": versions}


def add_command(sub) -> None:
    p = sub.add_parser("doctor", help="Check tools, models, fonts and the optional Jev key.")
    p.set_defaults(func=lambda a: doctor())
