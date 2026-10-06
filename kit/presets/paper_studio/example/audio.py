"""The mix: cleaned voice + one calm bed under the talk (LAKEY INSPIRED - Chill, ducked under speech, ~13 dB below the
voice) + a beat-synced track for the launch film (MokkaMusic - Drive, 85 BPM: its downbeat lands on the first launch
shot) + the composition's sound cues, mastered to -14 LUFS / -1.5 dBTP.
    python3 build.py --cues && python3 audio.py -> mix.wav (in the film's temp work folder, kit/paths.py)"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "kit/paths.py").exists())
sys.path.insert(0, str(ROOT))
from kit.paths import Film  # noqa: E402

F = Film(__file__)
KIT = ROOT / "kit"
M = KIT / "music"
SR = 48000
ED = json.load(open(HERE / "edl.json"))
TOTAL, L0 = ED["total"], ED["launch"][0]
# (file, reel start, reel end, track time at reel start, fade in, fade out, level in gaps vs voice, level under speech vs voice)
DRIVE_BEAT, DRIVE_PHASE = 0.706, 0.385     # measured: Drive's beat period and first-beat offset (s)
SECTIONS = [
    (M / "chill/chill__lakey-inspired__chill.mp3", 0.0, L0 + 0.15, 0.0, 0.4, 1.6, -4, -13),
    (M / "upbeat/upbeat__mokkamusic__drive.mp3", L0 - 0.02, TOTAL, DRIVE_PHASE + 16 * DRIVE_BEAT - 0.02, 0.02, 1.8, 0, -13),
]


def decode(p, start=None, dur=None, ch=2):
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", f"{max(0, start):.4f}"] if start is not None else []) + (["-t", f"{dur:.4f}"] if dur else [])
    raw = subprocess.run(cmd + ["-i", str(p), "-ac", str(ch), "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, ch).copy()


def db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-9)


def main():
    n = int(TOTAL * SR)
    vo = decode(F.work / "vo.wav", ch=1)[:n, 0]
    vo = np.pad(vo, (0, n - len(vo)))
    vo_db = db(vo[np.abs(vo) > 1e-3])
    rate = 100
    tt = np.arange(int(TOTAL * rate) + 1) / rate
    sp = np.zeros(len(tt))
    for w in ED["words"]:
        sp[int((w["t"] - 0.12) * rate):int((w["e"] + 0.2) * rate)] = 1
    k = np.hanning(31); k /= k.sum()
    sp = np.clip(np.convolve(sp, k, mode="same") * 1.6, 0, 1)
    music = np.zeros((n, 2), np.float32)
    for f, a, b, start, fi, fo, g_gap, g_sp in SECTIONS:
        dur = b - a
        x = decode(f, start, dur + 0.5)[: int(dur * SR)]
        x = np.pad(x, ((0, int(dur * SR) - len(x)), (0, 0)))
        body = db(x[int(min(2, dur / 3) * SR):])
        t = a + np.arange(len(x)) / SR
        g = vo_db + (g_gap + (g_sp - g_gap) * np.interp(t, tt, sp)) - body
        env = np.clip((t - a) / max(fi, 1e-3), 0, 1) * np.clip((b - t) / max(fo, 1e-3), 0, 1)
        i = int(a * SR)
        music[i:i + len(x)] += x * (10 ** (g / 20) * env)[:, None]
    t = np.arange(n) / SR
    music *= np.clip((TOTAL - 0.05 - t) / 1.2, 0, 1)[:, None]
    sfx = np.zeros((n, 2), np.float32)
    cache, seen = {}, set()
    for c in json.load(open(F.work / "cues.json")):
        key = (c["name"], round(c["at"], 2))
        if key in seen:
            continue
        seen.add(key)
        if c["name"] not in cache:
            x = decode(KIT / "sfx" / f"{c['name']}.wav")
            cache[c["name"]] = x / (np.abs(x).max() + 1e-9) * 10 ** (-3 / 20)
        x = cache[c["name"]] * 10 ** (c["gain_db"] / 20)
        i = int(c["at"] * SR)
        j = min(n, i + len(x))
        if 0 <= i < n:
            sfx[i:j] += x[: j - i]
    mix = vo[:, None] + music + sfx
    pre = F.work / "mix_pre.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-", "-c:a", "pcm_s24le", str(pre)], input=mix.astype(np.float32).tobytes(), check=True)
    m = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(pre), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
    m = json.loads(m[m.rindex("{"):m.rindex("}") + 1])
    af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample=192000,alimiter=limit=0.79:level=false,aresample=48000")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(pre), "-af", af, "-c:a", "pcm_s24le", str(F.work / "mix.wav")], check=True)
    pre.unlink()
    print(f"voice {vo_db:.1f} dBFS, {len(seen)} sfx -> mix.wav")


if __name__ == "__main__":
    main()
