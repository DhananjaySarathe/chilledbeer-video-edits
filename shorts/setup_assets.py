"""Download models and fonts into kit/, build the Vision tools and prefetch the cut checker's text model
(safe to re-run). Run: shorts setup"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

from shorts import config
from shorts.errors import ShortsError

MODEL_URLS = {
    config.WHISPER_MODEL: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin",
    config.ALIGN_MODEL: "https://huggingface.co/Xenova/wav2vec2-base-960h/resolve/main/onnx/model_quantized.onnx",
    config.ALIGN_VOCAB: "https://huggingface.co/Xenova/wav2vec2-base-960h/resolve/main/vocab.json",
    config.FACE_MODEL: "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    config.TURN_MODEL: "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/smart-turn-v3.2-cpu.onnx",
    config.VAD_MODEL: "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx",
}
# Apple Vision command-line tools (macOS, need the Xcode command line tools): name -> Swift source
TOOLS = {"personseg": config.ROOT / "shorts/gfx/personseg.swift", "ocrboxes": config.KIT / "hf/tools/ocrboxes.swift"}
# Google Fonts families and weights (static TTFs, SIL Open Font License).
FONT_FAMILIES = {"Montserrat": [800, 900], "Poppins": [600, 700, 800], "Anton": [400], "Inter": [400, 500, 600, 700, 800],
                 "Bebas Neue": [400], "DM Sans": [700], "Oswald": [500, 600, 700], "JetBrains Mono": [500, 700],
                 "Caveat": [700]}
UA = {"User-Agent": "video-shorts-setup"}


def _download(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dst)


def font_css_url(family: str, weights: list[int]) -> str:
    return f"https://fonts.googleapis.com/css2?family={family.replace(' ', '+')}:wght@{';'.join(map(str, weights))}&display=swap"


def parse_font_css(css: str) -> list[tuple[int, str]]:
    """(weight, ttf url) pairs from a Google Fonts CSS response."""
    out = []
    for block in css.split("@font-face")[1:]:
        weight = re.search(r"font-weight:\s*(\d+)", block)
        url = re.search(r"url\((https://[^)]+\.ttf)\)", block)
        if weight and url:
            out.append((int(weight.group(1)), url.group(1)))
    return out


def build_tools() -> list[str]:
    """Compile the Vision tools into kit/bin (person mattes, OCR boxes); rebuilt when the source is newer."""
    swiftc = shutil.which("swiftc")
    if not swiftc:
        raise ShortsError("E_TOOLS", "swiftc is missing, so the Apple Vision tools cannot be built.",
                          "Install the command line tools: xcode-select --install")
    built = []
    config.BIN.mkdir(parents=True, exist_ok=True)
    for name, src in TOOLS.items():
        out = config.BIN / name
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            continue
        subprocess.run([swiftc, "-O", str(src), "-o", str(out)], check=True, capture_output=True)
        built.append(name)
    return built


def prefetch_sat(model: str = "sat-3l-sm") -> None:
    """Download the cut checker's text model (wtpsplit SaT + its tokenizer) into kit/models/hf once."""
    os.environ.setdefault("HF_HOME", str(config.MODELS / "hf"))
    from wtpsplit import SaT
    SaT(model, ort_providers=["CPUExecutionProvider"])


def setup(fonts_only: bool = False) -> dict:
    fetched, present = [], []
    if not fonts_only:
        for dst, url in MODEL_URLS.items():
            if dst.exists() and dst.stat().st_size > 0:
                present.append(dst.name)
                continue
            _download(url, dst)
            fetched.append(dst.name)
    for family, weights in FONT_FAMILIES.items():
        with urllib.request.urlopen(urllib.request.Request(font_css_url(family, weights), headers=UA), timeout=30) as r:
            pairs = parse_font_css(r.read().decode())
        if not pairs:
            raise ShortsError("E_FONTS", f"Google Fonts returned no TTF files for {family}.",
                              "Check the network, or download the TTFs by hand into kit/fonts.")
        for weight, url in pairs:
            dst = config.FONTS / f"{family.replace(' ', '')}-{weight}.ttf"
            if dst.exists():
                present.append(dst.name)
                continue
            _download(url, dst)
            fetched.append(dst.name)
    built = [] if fonts_only else build_tools()
    if not fonts_only:
        prefetch_sat()
    return {"fetched": fetched, "already_present": present, "tools_built": built}


def add_command(sub) -> None:
    p = sub.add_parser("setup", help="Download models and fonts, build the Vision tools (safe to re-run).")
    p.add_argument("--fonts-only", action="store_true")
    p.set_defaults(func=lambda a: setup(fonts_only=a.fonts_only))
