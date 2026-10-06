"""Generate small test media with ffmpeg and macOS `say` (nothing is committed)."""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

FF = "ffmpeg"


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def make_clip(path: Path, *, w: int = 1080, h: int = 1920, seconds: float = 2.0, fps: int = 30,
              audio: str = "stereo48", hdr: bool = False, vfr: bool = False, rotate: int | None = None) -> Path:
    cmd = [FF, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate={fps}:duration={seconds}"]
    if audio != "none":
        sr = 48000 if audio == "stereo48" else 44100
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={sr}:duration={seconds}"]
    if vfr:
        cmd += ["-vf", f"setpts='(N+0.4*mod(N\\,3))/({fps}*TB)'", "-fps_mode", "vfr"]
    if hdr:
        cmd += ["-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-x265-params", "log-level=error:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc",
                "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio != "none":
        cmd += ["-c:a", "aac", "-ac", "2" if audio == "stereo48" else "1"]
    target = path.with_name(path.stem + "_raw.mp4") if rotate else path
    _run(cmd + [str(target)])
    if rotate:
        _run([FF, "-y", "-v", "error", "-display_rotation", str(rotate), "-i", str(target), "-c", "copy", str(path)])
        target.unlink()
    return path


TRUTH_WORDS = ("So uh today I'm going to show you something really cool um this app can edit your videos "
               "basically by itself and uh honestly it looks amazing").split()
TRUTH_GAPS = [0.0, 0.25, 0.30, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.35, 0.30, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
              0.20, 0.0, 0.0, 0.0, 0.30, 0.25, 0.0, 0.0]


def _say_word(folder: Path, i: int, word: str, sr: int) -> np.ndarray:
    aiff, wav = folder / f"w{i}.aiff", folder / f"w{i}.wav"
    _run(["say", "-v", "Samantha", "-r", "190", "-o", str(aiff), word])
    _run([FF, "-v", "error", "-y", "-i", str(aiff), "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(wav)])
    with wave.open(str(wav)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768


def make_truth_speech(folder: Path) -> tuple[Path, list[dict]]:
    """Speak each word separately with `say` and join them, so every word's true start and end are known."""
    sr, t = 16000, 0.3
    with ThreadPoolExecutor(max_workers=8) as pool:       # `say` takes ~1 s per call; run them side by side
        clips = list(pool.map(lambda iw: _say_word(folder, iw[0], iw[1], sr), enumerate(TRUTH_WORDS)))
    parts, truth = [np.zeros(int(0.3 * sr), np.float32)], []
    for i, (word, a) in enumerate(zip(TRUTH_WORDS, clips)):
        idx = np.where(np.abs(a) > 0.02)[0]
        a = a[max(idx[0] - 40, 0): idx[-1] + 40]
        if TRUTH_GAPS[i] > 0:
            parts.append(np.zeros(int(TRUTH_GAPS[i] * sr), np.float32))
            t += TRUTH_GAPS[i]
        truth.append({"word": word, "start": round(t, 3), "end": round(t + len(a) / sr, 3)})
        parts.append(a)
        t += len(a) / sr
    parts.append(np.zeros(int(0.4 * sr), np.float32))
    y = np.concatenate(parts)
    y = (y / np.abs(y).max() * 0.8 * 32767).astype(np.int16)
    out = folder / "truth16k.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(y.tobytes())
    (folder / "truth.json").write_text(json.dumps(truth))
    return out, truth


def pair_with_truth(texts: list[str], truth: list[dict]) -> list[tuple[int, int]]:
    """(word index, truth index) for the words Whisper transcribed correctly, matched in order."""
    bare = lambda s: re.sub(r"[^a-z']", "", s.lower())
    sm = difflib.SequenceMatcher(a=[bare(t) for t in texts], b=[bare(t["word"]) for t in truth], autojunk=False)
    return [(m.a + k, m.b + k) for m in sm.get_matching_blocks() for k in range(m.size)]


def make_speech_clip(path: Path, text: str, voice: str = "Samantha") -> Path:
    """A 1080x1920 test-pattern video whose audio is `say` speaking `text` (48 kHz stereo)."""
    aiff = path.with_suffix(".aiff")
    _run(["say", "-v", voice, "-o", str(aiff), text])
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(aiff)],
                               capture_output=True, text=True, check=True).stdout)
    _run([FF, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=1080x1920:rate=30:duration={dur + 0.6:.2f}",
          "-i", str(aiff), "-filter_complex", "[1:a]adelay=300|300,apad=pad_dur=0.3,aresample=48000[a]",
          "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-ac", "2", "-shortest", str(path)])
    aiff.unlink()
    return path
