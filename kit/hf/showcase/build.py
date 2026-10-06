"""The kit/hf showcase: one 16:9 film that uses every component (the speaker engine, lower third, chapter tags, side
words, the living diagram, an annotated screen demo, a code diff, a terminal, a compare, a chat, a stickman moment and
the end card). It's the kit's regression test, its preview source and a worked example for new films.

    node make_screen.mjs          # once: the sample screen recording (assets/screen.mp4)
    python3 build.py              # assets + index.html (kit inlined)
    node ../../../films/how-i-edit/cues.mjs     # the components' sound cues -> cues.json
    npx hyperframes lint && npx hyperframes render -o work/raw.mp4 --fps 30 --quality delivery
    python3 build.py --mux        # cues + a quiet bed -> showcase.mp4
    python3 build.py --previews   # snapshots -> kit/hf/previews/<component>.jpg
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parents[1]
ROOT = KIT.parent
sys.path.insert(0, str(KIT / "hf"))
import vendor  # noqa: E402

LONG = ROOT / "films/how-i-edit"
TOTAL = 73.0
# nominal section starts (seconds); snapped to the nearest cut so framing changes land on cuts
SECTIONS = [("intro", 0.0, "W"), ("hook", 6.0, "SR"), ("diagram", 11.5, "PIP"), ("screen", 23.5, "PIP"), ("code", 37.5, "PIP"),
            ("term", 46.5, "PIP"), ("compare", 54.0, "OFF"), ("recap", 57.5, "PIP"), ("chat", 61.0, "SR"), ("stick", 66.0, "OFF"), ("end", 69.5, "OFF")]


def run(cmd):
    subprocess.run(cmd, check=True)


def data():
    """The long video's cut pieces (with face tracks) for the first TOTAL seconds, split at the section starts so every
    section begins exactly on time; each piece is tagged with its section (the camera framing per section)."""
    edl = json.load(open(LONG / "edl.json"))
    cuts = sorted(t for _, t, _ in SECTIONS if t > 0)
    out = []
    for p in edl["pieces"]:
        if p["out_a"] >= TOTAL:
            break
        a, b = p["out_a"], min(p["out_b"], TOTAL)
        for c in [c for c in cuts if a < c < b] + [b]:
            out.append({"out_a": a, "out_b": c, "face": p["face"]})
            a = c
    for p in out:
        p["tag"] = [n for n, t, _ in SECTIONS if t <= p["out_a"] + 1e-6][-1]
    bounds = {n: [t, SECTIONS[i + 1][1] if i + 1 < len(SECTIONS) else TOTAL] for i, (n, t, _) in enumerate(SECTIONS)}
    return {"total": TOTAL, "pieces": out, "win": bounds, "framing": {n: f for n, _, f in SECTIONS}}


def build():
    vendor.copy_assets(HERE)
    a = HERE / "assets"
    if not (a / "aroll.mp4").exists():
        run(["ffmpeg", "-v", "error", "-y", "-i", str(LONG / "assets/aroll.mp4"), "-t", f"{TOTAL + 0.5}", "-an", "-c:v", "libx264", "-crf", "18", "-g", "15",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(a / "aroll.mp4")])
    (a / "broll").mkdir(exist_ok=True)
    D = data()
    html = (HERE / "src/template.html").read_text()
    html = vendor.inline(html).replace("/*DATA*/", "const D = " + json.dumps(D) + ";").replace("__TOTAL__", str(TOTAL))
    (HERE / "index.html").write_text(html)
    print("index.html:", {k: [round(x, 2) for x in v] for k, v in D["win"].items()})


def previews():
    """One snapshot per component, saved as kit/hf/previews/<id>.png (the registry points at these)."""
    D = data()
    w = D["win"]
    at = {"lowerThird": w["intro"][0] + 2.2, "camera_side": w["hook"][0] + 3.0, "diagram": w["diagram"][0] + 3.6, "diagram_focus": w["diagram"][0] + 4.6,
          "screen": w["screen"][0] + 2.6, "screen_cursor": w["screen"][0] + 4.9, "code": w["code"][0] + 4.6, "code_diff": w["code"][0] + 6.7,
          "terminal": w["term"][0] + 6.6, "compare": w["compare"][0] + 2.9, "diagram_recap": w["recap"][0] + 2.6, "chat": w["chat"][0] + 4.2,
          "stickman": w["stick"][0] + 2.4, "endCard": w["end"][0] + 2.2}
    out = HERE / "work/prev"
    run(["npx", "hyperframes", "snapshot", "--at", ",".join(f"{t:.2f}" for t in at.values()), "--no-end", "--describe", "false", "--timeout", "20000", "-o", str(out)])
    dest = KIT / "hf/previews"
    dest.mkdir(exist_ok=True)
    shots = sorted(out.glob("frame-*.png"))
    for (name, _), f in zip(at.items(), shots):
        run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-vf", "scale=960:-1", str(dest / f"{name}.jpg")])
    print(f"{len(shots)} previews -> {dest}")


def mux():
    """The components' sound cues (cues.json, from cues.mjs) + a quiet bed, to -14 LUFS, onto the render."""
    import numpy as np
    SR, n = 48000, int(TOTAL * 48000)
    dec = lambda p, ss=0.0, t=None: np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-ss", str(ss)] + (["-t", str(t)] if t else []) + ["-i", str(p), "-ac", "2", "-ar", str(SR),
                                                  "-f", "f32le", "-"], capture_output=True, check=True).stdout, np.float32).reshape(-1, 2)
    mix = np.zeros((n, 2), np.float32)
    bed = dec(KIT / "music/chill/chill__lakey-inspired__chill.mp3", 40.0, TOTAL)[:n]
    tt = np.arange(len(bed)) / SR
    mix[:len(bed)] += bed * (0.16 * np.clip(tt / 1.0, 0, 1) * np.clip((TOTAL - tt) / 2.0, 0, 1))[:, None]
    for c in json.load(open(HERE / "cues.json")):
        x = dec(KIT / "sfx" / f"{c['name']}.wav")
        x = x / (np.abs(x).max() + 1e-9) * 10 ** ((c["gain_db"] + 9) / 20)
        i = int(c["at"] * SR); j = min(n, i + len(x))
        if 0 <= i < n:
            mix[i:j] += x[: j - i]
    mix *= 0.5 / (np.abs(mix).max() + 1e-9)                                  # headroom before loudness
    pre, wav = HERE / "work/mix_pre.wav", HERE / "work/mix.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-", "-c:a", "pcm_f32le", str(pre)], input=mix.tobytes(), check=True)
    m = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(pre), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
    m = json.loads(m[m.rindex("{"):m.rindex("}") + 1])
    af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
          f"offset={m['target_offset']}:linear=true,aresample=192000,alimiter=limit=0.79:level=false,aresample=48000")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(pre), "-af", af, "-c:a", "pcm_s24le", str(wav)])
    run(["ffmpeg", "-v", "error", "-y", "-i", str(HERE / "work/raw.mp4"), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-c:a", "aac", "-aac_pns", "0", "-b:a", "256k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(HERE / "showcase.mp4")])
    print("-> showcase.mp4")


if __name__ == "__main__":
    previews() if "--previews" in sys.argv else mux() if "--mux" in sys.argv else build()
