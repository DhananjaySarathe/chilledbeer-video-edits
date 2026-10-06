"""Measure music tracks for the library: tempo, loudness, energy curve, drop, quiet intro, and vocals (whisper).

    python3 analyze_music.py <files...>  -> JSON lines on stdout
"""
import json, re, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

SR = 22050
MODEL = Path(__file__).resolve().parents[1] / "models/ggml-large-v3-turbo-q5_0.bin"


def load(p):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.float32)


def tempo(x):
    hop, win = 512, 2048
    fr = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    sp = np.log1p(np.abs(np.fft.rfft(fr * np.hanning(win), axis=1)))
    flux = np.maximum(0, np.diff(sp, axis=0)).sum(1)
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")
    flux = np.maximum(flux, 0)
    fps = SR / hop
    seg = flux[: int(90 * fps)] - flux[: int(90 * fps)].mean()
    ac = np.correlate(seg, seg, "full")[len(seg) - 1:]
    lags = np.arange(1, len(ac))
    bpm = 60 * fps / lags
    m = (bpm >= 70) & (bpm <= 180)
    score = ac[1:][m] * (1 + 0.15 * ((bpm[m] >= 85) & (bpm[m] <= 140)))     # mild preference for the usual range
    return round(float(bpm[m][np.argmax(score)]), 1)


def vocals(p, dur):
    words = []
    for frac in (0.35, 0.65):
        with tempfile.NamedTemporaryFile(suffix=".wav") as t:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur * frac:.1f}", "-t", "20", "-i", str(p), "-ac", "1", "-ar", "16000", t.name], check=True)
            out = subprocess.run(["whisper-cli", "-m", str(MODEL), "-f", t.name, "-l", "en", "-nt", "-np", "-t", "4"], capture_output=True, text=True).stdout
        txt = re.sub(r"\[[^\]]*\]|\([^)]*\)|♪|music", " ", out, flags=re.I)
        words.append(len(re.findall(r"[A-Za-z']{2,}", txt)))
    return words


def analyze(p):
    x = load(p)
    dur = len(x) / SR
    sec = SR
    rms = np.array([np.sqrt(np.mean(x[i:i + sec] ** 2)) + 1e-9 for i in range(0, len(x) - sec, sec)])
    db = 20 * np.log10(rms)
    sm = np.convolve(db, np.ones(3) / 3, mode="same")
    body = np.median(db)
    # drop: biggest rise over 2 s into a loud section
    rise = sm[2:] - sm[:-2]
    k = int(np.argmax(rise)) + 2 if len(rise) else 0
    intro = next((i for i, v in enumerate(db) if v > body - 4), 0)
    vw = vocals(p, dur)
    return {"file": str(p), "duration": round(dur, 1), "bpm": tempo(x), "rms_db": round(float(body), 1),
            "dynamic_db": round(float(np.percentile(db, 95) - np.percentile(db, 10)), 1),
            "drop_s": k if rise.size and rise.max() > 5 else None, "drop_rise_db": round(float(rise.max()), 1) if rise.size else 0,
            "quiet_intro_s": intro, "vocal_words": vw, "vocals": sum(vw) >= 12,
            "energy_2s": [round(float(v), 1) for v in db[::2]]}


if __name__ == "__main__":
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as ex:
        for r in ex.map(analyze, sys.argv[1:]):
            print(json.dumps(r), flush=True)
