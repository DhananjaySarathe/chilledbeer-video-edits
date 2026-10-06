"""Demo of the four v7 styles (kit/hf: sketch, annotate, scribble, collage) in one 9:16 piece, ~25 s, one beat each.

    python3 build.py --clip       # once: cut the creator clip (read-only source) + build the scribble outline (work/)
    python3 build.py              # assets + index.html (kit inlined); add --land for the 16:9 variant in landscape/
    npx hyperframes lint && npx hyperframes render -o work/raw.mp4 --fps 30 --quality delivery      # (in landscape/ for 16:9)
    node ../../../../films/how-i-edit/cues.mjs && python3 build.py --audio && python3 build.py --mux    # -> styles_demo.mp4
    python3 build.py --snap       # snapshots of the key frames -> work/snap/
    python3 ../../../qa/qa.py styles_demo.mp4 --expect-size=1080x1920        # 16:9: styles_demo_16x9.mp4, 1920x1080

Material: a screenshot and two phone screens from films/expensewaale (names already blurred there), a code snippet
of this kit's own boil rule, the agent loop as a sketch, and a 4 s clip of the creator (jobs/ew2, a whole sentence).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
KIT = HERE.parents[2]
ROOT = KIT.parent
sys.path.insert(0, str(KIT / "hf"))
import vendor  # noqa: E402

SHOTS = ROOT / "films/expensewaale/assets/shots"
SRC = ROOT / "jobs/ew2/work/source.mp4"                 # raw footage: read only
CLIP = (302.38, 4.04)                                    # "I will just give the prompt and let Claude do the thing, in high mode or medium mode."
BEATS = {"scribble": [0.0, 4.3], "sketch": [4.3, 10.6], "annotate": [10.6, 17.4], "collage": [17.4, 25.0]}   # the face first: it is the hook
TOTAL = 25.0
CLIP_AT = 0.0                                            # composition time of the clip's first frame
BED = ROOT / "kit/music/chill/chill__lakey-inspired__chill.mp3"
SR = 48000
LAND = "--land" in sys.argv                              # the 16:9 variant: same beats, src/landscape.html, built into landscape/
FILM = HERE / "landscape" if LAND else HERE
OUT = "styles_demo_16x9.mp4" if LAND else "styles_demo.mp4"
WORK = HERE / "work"
MIX = WORK / ("mix_land.wav" if LAND else "mix.wav")


def run(cmd, **kw):
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def clip():
    WORK.mkdir(exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-ss", CLIP[0], "-i", SRC, "-t", CLIP[1], "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p", "-g", "15",
         "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", WORK / "creator.mp4"])
    run([sys.executable, KIT / "hf/tools/scribble.py", WORK / "creator.mp4", WORK / "outline.json", "--work", WORK / "scribble", "--expand", "20", "--amp", "5",
         "--preview", WORK / "outline_sheet.jpg"])


def pages():
    """The clip's words (whisper, jobs/ew2) as caption pages of up to three words, in composition time."""
    wj = json.load(open(ROOT / "jobs/ew2/work/whisper.json"))
    ws = []
    for s in wj["transcription"]:
        for t in s["tokens"]:
            w, a = t["text"].strip(), t["offsets"]["from"] / 1000
            if w and not w.startswith("[") and w not in ",.?" and CLIP[0] <= a < CLIP[0] + CLIP[1] - 0.15:
                ws.append({"w": w, "t": round(CLIP_AT + a - CLIP[0], 3)})
    fix = {"i": "I", "cloud": "Claude"}                    # he says "let the Claude do the thing"; whisper hears "cloud"
    for w in ws:
        w["w"] = fix.get(w["w"], w["w"])
    words = [w for w in ws if not (w["w"] == "the" and ws[ws.index(w) + 1]["w"] == "Claude")]
    groups = [["I", "will", "just"], ["give", "the", "prompt"], ["and", "let", "Claude"], ["do", "the", "thing"], ["in", "high", "mode"], ["or", "medium", "mode."]]
    out, i = [], 0
    for g in groups:
        pg = words[i:i + len(g)]
        assert [w["w"] for w in pg] == [x.rstrip(".") for x in g], ([w["w"] for w in pg], g)
        if g[-1].endswith("."):
            pg[-1] = {**pg[-1], "w": g[-1]}
        out.append({"ws": pg}); i += len(g)
    return out


def build():
    FILM.mkdir(exist_ok=True)
    (FILM / "hyperframes.json").write_text('{ "paths": { "assets": "assets" } }\n')
    vendor.copy_assets(FILM)
    a = FILM / "assets"
    for src, name in ((SHOTS / "ultra-home.jpg", "shot.jpg"), (SHOTS / "low-mobile.jpg", "low.jpg"), (SHOTS / "ultra-mobile.jpg", "ultra.jpg"), (WORK / "creator.mp4", "creator.mp4")):
        shutil.copy2(src, a / name)
    S = json.load(open(WORK / "outline.json"))
    D = {"total": TOTAL, "beats": BEATS, "order": {k: i + 1 for i, k in enumerate(BEATS)}, "clip": {"at": CLIP_AT, "dur": CLIP[1], "pages": pages()}}
    html = (HERE / ("src/landscape.html" if LAND else "src/template.html")).read_text()
    html = vendor.inline(html, stickman=False).replace("/*DATA*/", "const D = " + json.dumps(D) + ";\n      const S = " + json.dumps(S, separators=(",", ":")) + ";")
    (FILM / "index.html").write_text(html.replace("__TOTAL__", str(TOTAL)))
    print("index.html:", TOTAL, "s;", len(S["steps"]), "outline steps")


def dec(p, ss=0.0, t=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", str(ss)] + (["-t", str(t)] if t else []) + ["-i", str(p), "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32).reshape(-1, 2).copy()


def audio():
    """A chill bed (ducked ~12 dB under his sentence), his voice, the sound cues; -14 LUFS, TP -1.5."""
    n = int(TOTAL * SR); t = np.arange(n) / SR
    voice = dec(WORK / "creator.mp4")
    fade = int(0.03 * SR); voice[:fade] *= np.linspace(0, 1, fade)[:, None]; voice[-fade:] *= np.linspace(1, 0, fade)[:, None]
    vo = np.zeros((n, 2), np.float32); i = int(CLIP_AT * SR); vo[i:i + len(voice)] = voice[: n - i]
    bed = dec(BED, 36.0, TOTAL + 0.5)[:n]; bed = np.pad(bed, ((0, n - len(bed)), (0, 0)))
    rms = lambda x: np.sqrt(np.mean(np.square(x)) + 1e-12)
    vdb = 20 * np.log10(rms(voice[np.abs(voice[:, 0]) > 1e-3]))
    duck = np.clip(np.minimum((t - (CLIP_AT - 0.35)) / 0.3, ((CLIP_AT + CLIP[1] + 0.3) - t) / 0.4), 0, 1)
    g = vdb - 20 * np.log10(rms(bed)) + (-7 - 6 * duck)                 # bed 7 dB under the voice level, 13 dB while he talks
    env = np.clip(t / 0.4, 0, 1) * np.clip((TOTAL - 0.05 - t) / 1.2, 0, 1)
    mix = vo + bed * (10 ** (g / 20) * env)[:, None]
    for c in json.load(open(FILM / "cues.json")):
        x = dec(ROOT / "kit/sfx" / f"{c['name']}.wav")
        x = x / (np.abs(x).max() + 1e-9) * 10 ** ((-3 + c["gain_db"]) / 20)
        i = int(c["at"] * SR); j = min(n, i + len(x))
        if 0 <= i < n:
            mix[i:j] += x[: j - i]
    pre = WORK / "mix_pre.wav"
    run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", SR, "-ac", "2", "-i", "-", "-c:a", "pcm_f32le", pre], input=mix.astype(np.float32).tobytes())
    m = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(pre), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
    m = json.loads(m[m.rindex("{"):m.rindex("}") + 1])
    af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
          f"offset={m['target_offset']}:linear=true,aresample=192000,alimiter=limit=0.79:level=false,aresample=48000")
    run(["ffmpeg", "-v", "error", "-y", "-i", pre, "-af", af, "-c:a", "pcm_s24le", MIX])
    print(MIX.name)


def mux():
    raw = FILM / "work/raw.mp4" if LAND else WORK / "raw.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", raw, "-i", MIX, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-aac_pns", "0",
         "-b:a", "320k", "-ar", "48000", "-shortest", "-movflags", "+faststart", HERE / OUT])
    print("->", OUT)


def snap():
    at = [0.0, 0.6, 1.5, 3.2, 5.0, 6.6, 8.2, 9.6, 11.4, 12.8, 14.4, 16.4, 18.1, 19.2, 21.5, 24.9]
    run(["npx", "hyperframes", "snapshot", "--at", ",".join(f"{x:.2f}" for x in at), "--no-end", "--describe", "false", "--timeout", "30000",
         "-o", WORK / ("snap_land" if LAND else "snap")], cwd=FILM)


if __name__ == "__main__":
    {"--clip": clip, "--audio": audio, "--mux": mux, "--snap": snap}.get(next((a for a in sys.argv[1:] if a.startswith("--") and a != "--land"), ""), build)()
