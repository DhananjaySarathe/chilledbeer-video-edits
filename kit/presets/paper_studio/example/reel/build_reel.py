"""Build the reel: index.html from src/template.html, the launch excerpt from the long video, the mix, the mux.
Generated files go to the reel's temp folders and output/final/<film>/ (kit/paths.py; python3 build_reel.py --paths).

    python3 reel_edl.py && python3 ../../../kit/look/grade.py $W/aroll.mp4 $W/aroll_graded.mp4 \
        --track=<take temp>/source.face.json --map=$W/aroll.map.json
    python3 build_reel.py && python3 build_reel.py --cues && python3 build_reel.py --audio
    npx hyperframes render $HF -o $R/raw.mp4 --fps 30 --quality delivery && python3 build_reel.py --mux
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
LONG = HERE.parent
ROOT = next(p for p in HERE.parents if (p / "kit/paths.py").exists())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kit/hf"))
import vendor  # noqa: E402
from kit.paths import Film  # noqa: E402

F, LONG_F = Film(__file__), Film(LONG)
KIT = ROOT / "kit"
EDL = json.load(open(HERE / "edl.json"))
MAIN = json.load(open(LONG / "edl.json"))
SR = 48000
DRIVE = KIT / "music/upbeat/upbeat__mokkamusic__drive.mp3"
DRIVE_BEAT, DRIVE_PHASE = 0.706, 0.385


def run(cmd):
    subprocess.run(cmd, check=True)


def launch_from():
    """The long video's launch film from its 3rd shot (Cut) for 4 shots: the reel shows that excerpt."""
    L0, L1 = MAIN["launch"]
    return L0 + 2 * (L1 - L0) / 7


def build():
    F.stage()
    vendor.copy_assets(F.hf)
    shutil.copy(F.work / "aroll_graded.mp4", F.assets / "aroll.mp4")
    a, b = EDL["launch"]
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{launch_from():.3f}", "-i", str(LONG_F.renders / "raw.mp4"), "-t", f"{b - a + 0.1:.3f}", "-an",
         "-vf", "scale=1080:608:flags=lanczos", "-c:v", "libx264", "-crf", "14", "-g", "10", "-pix_fmt", "yuv420p", str(F.assets / "launch.mp4")])
    html = (HERE / "src/template.html").read_text()
    html = html.replace("/*DATA*/", "const D = " + json.dumps(EDL) + ";").replace("__TOTAL__", f"{EDL['total']}")
    html = html.replace("<!--AROLL-->", f'<video id="aroll" class="clip" src="assets/aroll.mp4" muted playsinline data-start="0" '
                                         f'data-duration="{EDL["total"]:.3f}" data-media-start="0" data-track-index="2"></video>')
    (F.hf / "index.html").write_text(html)
    print(f"{F.hf / 'index.html'} built")


def decode(p, start=0.0, dur=None, ch=2):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.4f}"] + (["-t", f"{dur:.4f}"] if dur else []) + ["-i", str(p), "-ac", str(ch), "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32).reshape(-1, ch).copy()


def db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-9)


def audio():
    """Voice + Drive (beat-locked so the launch excerpt's cuts stay on its beats) ~12 dB under speech, up in the launch,
    + sound cues; mastered to -14 LUFS / -1.5 dBTP."""
    T = EDL["total"]
    n = int(T * SR)
    vo = decode(F.work / "vo.wav", ch=1)[:n, 0]
    vo = np.pad(vo, (0, n - len(vo)))
    vo_db = db(vo[np.abs(vo) > 1e-3])
    # track time at the excerpt start must equal the long video's track time there
    la = EDL["launch"][0]
    track_at_la = DRIVE_PHASE + 16 * DRIVE_BEAT + (launch_from() - MAIN["launch"][0])
    start = track_at_la - la
    while start < 4.0:
        start += 16 * DRIVE_BEAT                                  # whole bars later, still on the grid
    x = decode(DRIVE, start, T + 0.5)[:n]
    x = np.pad(x, ((0, n - len(x)), (0, 0)))
    body = db(x)
    rate = 100
    tt = np.arange(int(T * rate) + 1) / rate
    sp = np.zeros(len(tt))
    for w in EDL["words"]:
        sp[int((w["t"] - 0.12) * rate):int((w["e"] + 0.2) * rate)] = 1
    k = np.hanning(31); k /= k.sum()
    sp = np.clip(np.convolve(sp, k, mode="same") * 1.6, 0, 1)
    t = np.arange(n) / SR
    g = vo_db + (-4 + (-12 + 4) * np.interp(t, tt, sp)) - body
    inl = ((t >= la - 0.05) & (t < EDL["launch"][1] + 0.1)).astype(np.float32)
    inl = np.convolve(inl, np.ones(2400) / 2400, mode="same")
    g = g + inl * 4                                                # the launch excerpt plays the music up front
    env = np.clip(t / 0.05, 0, 1) * np.clip((T - 0.05 - t) / 1.2, 0, 1)
    music = x * (10 ** (g / 20) * env)[:, None]
    sfx = np.zeros((n, 2), np.float32)
    for c in json.load(open(F.work / "cues.json")):
        y = decode(KIT / "sfx" / f"{c['name']}.wav")
        y = y / (np.abs(y).max() + 1e-9) * 10 ** ((c["gain_db"] - 3) / 20)
        i = int(c["at"] * SR); j = min(n, i + len(y))
        if 0 <= i < n:
            sfx[i:j] += y[: j - i]
    mix = vo[:, None] + music + sfx
    pre = F.work / "mix_pre.wav"
    run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-", "-c:a", "pcm_s24le", str(pre)]) if False else \
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-", "-c:a", "pcm_s24le", str(pre)], input=mix.astype(np.float32).tobytes(), check=True)
    m = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(pre), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
    m = json.loads(m[m.rindex("{"):m.rindex("}") + 1])
    af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample=192000,alimiter=limit=0.79:level=false,aresample=48000")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(pre), "-af", af, "-c:a", "pcm_s24le", str(F.work / "mix.wav")])
    pre.unlink()
    print(f"mix.wav (Drive from {start:.3f} s)")


def mux():
    out = F.final / "reel_how_i_edit.mp4"          # next to the long video in output/final/<film>/
    run(["ffmpeg", "-v", "error", "-y", "-i", str(F.renders / "raw.mp4"), "-i", str(F.work / "mix.wav"), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-c:a", "aac", "-aac_pns", "0", "-b:a", "320k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)])
    print(f"-> {out}")


def cues():
    run(["node", str(LONG / "cues.mjs"), str(F.hf / "index.html"), str(F.work / "cues.json")])


if __name__ == "__main__":
    if "--paths" in sys.argv:
        print(f"W={F.work}\nHF={F.hf}\nR={F.renders}\nFINAL={F.final}")
    else:
        {"--mux": mux, "--audio": audio, "--cues": cues}.get(next((a for a in sys.argv[1:] if a.startswith("--")), ""), build)()
