"""Audio facts: a 16 kHz mono copy for speech models, a loudness envelope, adaptive levels, overall loudness."""
from __future__ import annotations

import re
import subprocess
import wave
from pathlib import Path

import numpy as np

from shorts.proc import run

HOP_S = 0.01


def extract_wav(ffmpeg: str, src: str, dst: Path, sr: int = 16000) -> Path:
    run([ffmpeg, "-v", "error", "-y", "-i", src, "-vn", "-map", "0:a:0", "-ac", "1", "-ar", str(sr),
         "-c:a", "pcm_s16le", str(dst)], code="E_AUDIO", what="Extracting audio")
    return dst


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError(f"{path}: expected 16-bit mono wav")
        data = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
        return data, w.getframerate()


def energy_db(samples: np.ndarray, sr: int, hop_s: float = HOP_S) -> np.ndarray:
    hop = int(round(sr * hop_s))
    n = len(samples) // hop
    if n == 0:
        return np.zeros(0, np.float32)
    frames = samples[: n * hop].reshape(n, hop)
    return (20 * np.log10(np.sqrt(np.mean(frames * frames, axis=1) + 1e-12))).astype(np.float32)


def levels(db: np.ndarray) -> tuple[float, float, float, float]:
    """(speech_db, floor_db, quiet_db, dip_db) adapted to this recording's noise floor and speech level."""
    if len(db) == 0:
        return -20.0, -60.0, -45.0, -35.0
    speech = float(np.percentile(db, 90))
    floor = float(np.percentile(db, 10))
    span = max(speech - floor, 6.0)
    return speech, floor, floor + 0.35 * span, floor + 0.55 * span


_NUM = r"(-?\d+(?:\.\d+)?|-inf)"


def parse_ebur128(stderr: str) -> dict:
    text = stderr[stderr.rfind("Summary:"):] if "Summary:" in stderr else stderr

    def grab(pattern: str) -> float | None:
        m = re.search(pattern, text)
        return None if not m or m.group(1) == "-inf" else float(m.group(1))

    return {"integrated": grab(rf"I:\s+{_NUM} LUFS"), "lra": grab(rf"LRA:\s+{_NUM} LU"),
            "true_peak": grab(rf"Peak:\s+{_NUM} dBFS")}


def measure_loudness(ffmpeg: str, src: str) -> dict:
    proc = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", src, "-vn", "-af", "ebur128=peak=true",
                           "-f", "null", "-"], capture_output=True, text=True)
    return parse_ebur128(proc.stderr)
