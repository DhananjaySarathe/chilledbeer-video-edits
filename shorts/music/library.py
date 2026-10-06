"""The background-music library (kit/music): track list, measured structure (beat grid, drops, quiet intro) and a
usage log so consecutive videos do not reuse the same track."""
from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

from shorts import config

MUSIC = config.KIT / "music"
LIBRARY = MUSIC / "library.json"
STRUCTURE = MUSIC / "structure.json"          # cache of structure(), keyed by file + size
LEGACY_USAGE = MUSIC / "usage.json"           # where the log lived before output/ (read if the new one is missing)
MOODS = ("chill", "upbeat", "tech", "hype", "emotional", "suspense", "funny", "cinematic")
SR = 22050
RATE = 20                                     # envelope frames per second


def tracks() -> list[dict]:
    """Every library track that is present on disk (audio is fetched separately, see kit/assets_src/fetch.py)."""
    if not LIBRARY.exists():
        return []
    return [t for t in json.loads(LIBRARY.read_text()) if (config.ROOT / "kit" / t["file"]).exists()]


def path(t: dict) -> Path:
    return config.KIT / t["file"]


def _load(p: Path) -> np.ndarray:
    raw = subprocess.run([config.tool("ffmpeg"), "-v", "error", "-i", str(p), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def _envelopes(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Full-band dB, low-band (kick/bass) dB and spectral flux, all at RATE frames per second."""
    hop, win = SR // RATE, 2048
    fr = np.lib.stride_tricks.sliding_window_view(np.pad(x, (0, win)), win)[::hop]
    sp = np.abs(np.fft.rfft(fr * np.hanning(win), axis=1))
    f = np.fft.rfftfreq(win, 1 / SR)
    full = 20 * np.log10(np.sqrt(np.mean(fr ** 2, axis=1)) + 1e-9)
    low = 20 * np.log10(sp[:, (f > 35) & (f < 150)].mean(1) + 1e-9)
    flux = np.maximum(0, np.diff(np.log1p(sp), axis=0, prepend=np.log1p(sp[:1]))).sum(1)
    return full, low, flux


def _smooth(v: np.ndarray, seconds: float) -> np.ndarray:
    n = max(1, int(seconds * RATE))
    return np.convolve(np.pad(v, n, mode="edge"), np.ones(2 * n + 1) / (2 * n + 1), mode="valid")


def _tempo(flux: np.ndarray) -> tuple[float, float]:
    """(bpm, phase seconds of the first beat): autocorrelation of the onset curve scored across beat multiples
    (so half/double-time peaks do not win), with a mild prior around 115 BPM."""
    o = np.maximum(flux - _smooth(flux, 0.4), 0)
    seg = o[: 120 * RATE] - o[: 120 * RATE].mean()
    ac = np.correlate(seg, seg, "full")[len(seg) - 1:]
    ac = ac / (ac[0] + 1e-12)
    fine = 8                                            # evaluate lags at 1/8-frame steps (linear interpolation)
    def at(l):
        i = int(l)
        return ac[i] + (ac[i + 1] - ac[i]) * (l - i) if i + 1 < len(ac) else 0.0
    best, score = 0.0, -1e18
    for bpm10 in range(800, 1661, 2):
        lag = RATE * 60 / (bpm10 / 10)
        sc = sum(at(k * lag) / k for k in range(1, 5)) + 0.5 * at(lag / 2)
        sc *= np.exp(-0.5 * (np.log2(bpm10 / 1150) / 0.9) ** 2)
        if sc > score:
            best, score = bpm10 / 10, sc
    period = 60 / best
    lagf = period * RATE
    phases = [sum(o[int(round(p + k * lagf))] for k in range(int((len(o) - p) / lagf))) for p in np.arange(0, lagf, 1)]
    return round(best, 1), round(float(np.argmax(phases)) / RATE, 3)


def _drops(full: np.ndarray, low: np.ndarray, flux: np.ndarray, dur: float) -> list[dict]:
    """Moments the track lands hard: a sustained jump in energy (and usually the bass), away from the ends."""
    e = _smooth(full, 0.5)
    lo = _smooth(low, 0.5)
    w = 4 * RATE
    out = []
    for i in range(w, len(e) - w):
        t = i / RATE
        if t < 5 or t > dur - 8:
            continue
        rise = e[i:i + w].mean() - e[i - w:i].mean()
        bass = lo[i:i + w].mean() - lo[i - w:i].mean()
        if rise >= 4.5 or (rise >= 3 and bass >= 8):
            out.append((i, rise + 0.3 * max(bass, 0)))
    # one drop per 8 s: the strongest, then snapped to the nearest onset
    picked = []
    for i, s in sorted(out, key=lambda x: -x[1]):
        if all(abs(i - j) > 8 * RATE for j, _ in picked):
            picked.append((i, s))
    res = []
    for i, s in sorted(picked):
        a, b = max(0, i - int(0.5 * RATE)), min(len(flux), i + int(0.5 * RATE))
        k = a + int(np.argmax(flux[a:b]))
        res.append({"t": round(k / RATE, 2), "strength": round(float(s), 1)})
    return res[:6]


def structure(t: dict) -> dict:
    """Measured structure of a track, cached in kit/music/structure.json."""
    p = path(t)
    cache = json.loads(STRUCTURE.read_text()) if STRUCTURE.exists() else {}
    key = f"{t['file']}:{p.stat().st_size}"
    if key in cache:
        return cache[key]
    x = _load(p)
    dur = len(x) / SR
    full, low, flux = _envelopes(x)
    body = float(np.median(full))
    loud = _smooth(full, 1.0) > body - 4
    intro = float(np.argmax(loud) / RATE) if loud.any() else 0.0
    bpm, phase = _tempo(flux)
    sec = _smooth(full, 1.0)[:: RATE]
    s = {"duration": round(dur, 2), "bpm": bpm, "beat0": phase, "quiet_intro": round(intro, 2),
         "drops": _drops(full, low, flux, dur), "body_db": round(body, 1),
         "steadiness_db": round(float(np.std(sec[int(intro): max(int(intro) + 1, int(dur) - 6)])), 2),
         "energy_1s": [round(float(v), 1) for v in sec]}
    cache[key] = s
    STRUCTURE.write_text(json.dumps(cache))
    return s


def usage_path() -> Path:
    """Which track each job used: output/music_usage.json (kept history, not temp: it keeps tracks from repeating)."""
    return config.OUTPUT / "music_usage.json"


@lru_cache(maxsize=1)
def usage() -> list[dict]:
    p = usage_path() if usage_path().exists() else LEGACY_USAGE
    return json.loads(p.read_text()) if p.exists() else []


def record_use(job: str, file: str) -> None:
    log = [u for u in usage() if u["job"] != job] + [{"job": job, "file": file}]
    usage_path().parent.mkdir(parents=True, exist_ok=True)
    usage_path().write_text(json.dumps(log[-50:], indent=1))
    usage.cache_clear()
