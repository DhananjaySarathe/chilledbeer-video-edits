"""Sound effects synthesised from scratch (numpy): no downloads, no licences, identical every run.

    uv run python -m shorts.gfx.sfx      # writes kit/sfx/*.wav (48 kHz stereo, peak -3 dBFS)
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from shorts import config

SR = 48000
SFX_DIR = config.KIT / "sfx"
NAMES = ("whoosh", "swipe", "pop", "click", "tick", "typing", "ding", "stamp", "thud", "riser", "rewind", "scratch",
         "boom")


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(SR * seconds)) / SR


def _noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n)


def _band_sweep(x: np.ndarray, f0: float, f1: float, width: float, frame: int = 1024) -> np.ndarray:
    """Band-pass x with a centre frequency gliding from f0 to f1 (short-time FFT, overlap-add)."""
    hop = frame // 4
    win = np.hanning(frame)
    pad = np.concatenate([np.zeros(frame), x, np.zeros(frame)])
    out = np.zeros_like(pad)
    freqs = np.fft.rfftfreq(frame, 1 / SR)
    starts = range(0, len(pad) - frame, hop)
    total = max(1, len(starts) - 1)
    for k, s in enumerate(starts):
        fc = f0 * (f1 / f0) ** (k / total)
        gain = np.exp(-0.5 * ((np.log(freqs + 1) - np.log(fc)) / width) ** 2)
        out[s:s + frame] += np.fft.irfft(np.fft.rfft(pad[s:s + frame] * win) * gain, frame) * win
    return out[frame:frame + len(x)]


def _env(n: int, attack: float, release: float) -> np.ndarray:
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1) ** 1.5
    r = np.exp(-np.clip(t - attack, 0, None) / max(release, 1e-4))
    return a * r


def _blip(f0: float, f1: float, seconds: float, decay: float) -> np.ndarray:
    t = _t(seconds)
    freq = f0 * (f1 / f0) ** (t / seconds)
    return np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t / decay)


def _stereo(x: np.ndarray, pan_from: float = 0.0, pan_to: float = 0.0) -> np.ndarray:
    p = np.linspace(pan_from, pan_to, len(x))            # -1 left .. 1 right, constant power
    ang = (p + 1) * np.pi / 4
    return np.stack([x * np.cos(ang), x * np.sin(ang)], axis=1)


def synth(name: str) -> np.ndarray:
    if name == "whoosh":
        n = len(_t(0.5))
        x = _band_sweep(_noise(n, 1), 260, 2600, 0.55) * _env(n, 0.18, 0.12)
        return _stereo(x, -0.6, 0.6)
    if name == "swipe":
        n = len(_t(0.28))
        x = _band_sweep(_noise(n, 2), 900, 5200, 0.45) * _env(n, 0.07, 0.07)
        return _stereo(x, 0.5, -0.5)
    if name == "pop":
        x = _blip(1100, 260, 0.14, 0.035) + 0.3 * _band_sweep(_noise(len(_t(0.14)), 3), 2500, 1500, 0.5) * _env(len(_t(0.14)), 0.002, 0.012)
        return _stereo(x)
    if name == "click":
        n = len(_t(0.05))
        x = 0.7 * _blip(2400, 1800, 0.05, 0.006) + 0.5 * _band_sweep(_noise(n, 4), 4000, 3000, 0.4) * _env(n, 0.0005, 0.004)
        return _stereo(x)
    if name == "tick":
        return _stereo(_blip(3200, 3000, 0.03, 0.004))
    if name == "typing":
        out = np.zeros(len(_t(0.8)))
        r = np.random.default_rng(5)
        pos = 0.02
        while pos < 0.72:
            key = 0.6 * _blip(1800 + r.uniform(-300, 300), 1500, 0.03, 0.005)
            key += 0.4 * _band_sweep(_noise(len(key), int(pos * 1000)), 3500, 2500, 0.5) * _env(len(key), 0.0005, 0.006)
            s = int(pos * SR)
            out[s:s + len(key)] += key * r.uniform(0.6, 1.0)
            pos += r.uniform(0.06, 0.11)
        return _stereo(out)
    if name == "ding":
        t = _t(1.1)
        x = (np.sin(2 * np.pi * 1318.5 * t) + 0.55 * np.sin(2 * np.pi * 1975.5 * t) + 0.25 * np.sin(2 * np.pi * 2637 * t))
        return _stereo(x * np.exp(-t / 0.32) * np.clip(t / 0.004, 0, 1))
    if name == "stamp":
        x = 1.0 * _blip(120, 48, 0.3, 0.07)
        n = len(x)
        x += 0.45 * _band_sweep(_noise(n, 6), 1800, 700, 0.6) * _env(n, 0.001, 0.03)
        return _stereo(x)
    if name == "thud":
        x = _blip(80, 40, 0.35, 0.09)
        n = len(x)
        x += 0.2 * _band_sweep(_noise(n, 7), 400, 200, 0.5) * _env(n, 0.002, 0.05)
        return _stereo(x)
    if name == "riser":
        t = _t(1.0)
        n = len(t)
        x = 0.6 * _band_sweep(_noise(n, 8), 300, 4000, 0.5) + 0.4 * _blip(220, 1320, 1.0, 10.0)
        return _stereo(x * (t / t[-1]) ** 2.2 * np.clip((1.0 - t) / 0.03, 0, 1), -0.3, 0.3)
    if name == "rewind":                      # a tape shuttling backwards: a warbling chirp that climbs, plus hiss
        t = _t(0.75)
        n = len(t)
        freq = 380 * (2600 / 380) ** (t / t[-1])
        tone = np.sin(2 * np.pi * np.cumsum(freq) / SR) * (0.65 + 0.35 * np.sin(2 * np.pi * 31 * t))
        hiss = _band_sweep(_noise(n, 9), 900, 5000, 0.5)
        x = (0.55 * tone + 0.45 * hiss) * np.clip(t / 0.05, 0, 1) * np.clip((t[-1] - t) / 0.18, 0, 1)
        return _stereo(x, 0.4, -0.4)
    if name == "scratch":                     # a record scratch: the needle yanked back and forth twice
        t = _t(0.36)
        n = len(t)
        wob = np.abs(np.sin(2 * np.pi * 2.8 * t))              # two strokes
        x = _band_sweep(_noise(n, 10), 700, 2600, 0.35) * wob + 0.35 * np.sin(2 * np.pi * np.cumsum(200 + 900 * wob) / SR) * wob
        return _stereo(x * np.clip((t[-1] - t) / 0.04, 0, 1))
    if name == "boom":                        # a deep cinematic hit for a reveal
        x = _blip(95, 32, 1.0, 0.28)
        n = len(x)
        x += 0.35 * _band_sweep(_noise(n, 11), 600, 120, 0.6) * _env(n, 0.002, 0.08)
        return _stereo(x)
    raise KeyError(name)


def write_wav(x: np.ndarray, path: Path) -> None:
    x = x / (np.abs(x).max() + 1e-9) * 10 ** (-3 / 20)
    pcm = (x * 32767).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def ensure_sfx() -> dict[str, Path]:
    out = {}
    for name in NAMES:
        p = SFX_DIR / f"{name}.wav"
        if not p.exists():
            write_wav(synth(name), p)
        out[name] = p
    return out


if __name__ == "__main__":
    for name, p in ensure_sfx().items():
        print(name, p.stat().st_size // 1024, "KB")
