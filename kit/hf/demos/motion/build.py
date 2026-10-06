"""Camera v2 demo: a 45 s edit of the raw jobs/ew2 take (English, 1920x1080, 30 fps) that shows every camera move
in context, the same edit with the old camera (before/after), and a 9:16 panel version.

    uv run python kit/hf/demos/motion/build.py             # cut, faces, plans, blur bake, three pages (--keep-cut: reuse the cut)
    cd kit/hf/demos/motion        && npx hyperframes render -o renders/after.mp4  --fps 30 --quality delivery --quiet
    cd kit/hf/demos/motion/before && npx hyperframes render -o ../renders/before.mp4 --fps 30 --quality delivery --quiet
    cd kit/hf/demos/motion/reel   && npx hyperframes render -o ../renders/reel.mp4   --fps 30 --quality delivery --quiet
    uv run python kit/hf/demos/motion/build.py --mux       # demo_motion.mp4, demo_before_after.mp4, demo_reel.mp4

Reads jobs/ew2 (source.mp4, analysis.json, the DeepFilterNet voice) and never writes there. Media stays local.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "kit/hf"))
sys.path.insert(0, str(ROOT / "kit/motion"))
import camera  # noqa: E402
import vendor  # noqa: E402

vendor.MODULES = [m for m in vendor.MODULES if (vendor.HERE / m).exists()]   # other tracks' modules may not exist yet

JOB = ROOT / "jobs/ew2"
SRC, VOICE = JOB / "work/source.mp4", JOB / "work/voice_raw_DeepFilterNet3.wav"
FPS, SR = 30, 48000
WORK, ASSETS = HERE / "work", HERE / "assets"
MAX_GAP, LEAD, TAIL, TAIL_END = 0.30, 0.05, 0.09, 0.16     # a pause over 0.30 s keeps ~0.14 s (~0.21 s after a sentence)
# (first word, last word, section tag): whole sentences only (503-508, "so, it was in max effort," is left out)
KEEP = [(376, 502, "max"), (509, 538, "max"), (593, 604, "ultra")]
# punctuation by thought (whisper ran this take on as one sentence), so the director sees where thoughts start
FIX = {385: "well.", 386: "And", 396: "good.", 397: "But", 426: "effort.", 427: "Sorry,", 435: "different.", 436: "When",
       451: "skills.", 452: "It", 470: "right?", 471: "It", 502: "them.", 509: "But", 513: "expensive.", 514: "And",
       538: "right?", 593: "But", 604: "code."}
# what the director is told (word ids are the take's own indices)
TAGS = {"ease": [399], "joke": [427], "story": [[471, 502]], "punchline": [512], "section": [593]}
RULES = {"punch": {"gap": 7}}                     # demo only: every move inside 40 s (long-form default is 16 s)
LABELS = {"reframe": "Reframe at a new thought", "punch": "Emphasis punch (hard cut)", "ease": "Eased punch + 180° blur",
          "snap": "Snap zoom + blur + landing shake", "push": "Slow push (story)", "zoomx": "Zoom transition (section)"}
SHORT = {"reframe": ("Reframe", "a new thought"), "punch": ("Emphasis *punch", "hard cut, held to the end of the line"),
         "ease": ("Eased *punch", "power3.out, 180° motion blur"), "snap": ("Snap *zoom", "expo out, 270° blur, landing shake"),
         "push": ("Slow *push", "a story beat, sine in-out"), "zoomx": ("Zoom *transition", "a section change, 330° blur")}


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


# ------------------------------------------------------------------ the cut
def cut() -> dict:
    A = json.load(open(JOB / "analysis.json"))
    words = A["words"]
    pieces, out_words, t_out = [], [], 0.0
    runs = []
    for first, last, tag in KEEP:
        ws, curr = words[first:last + 1], []
        for w in ws:
            if curr and w["start"] - curr[-1]["end"] > MAX_GAP:
                runs.append((curr, tag)); curr = []
            curr.append(w)
        runs.append((curr, tag))
    spans = []
    for r, tag in runs:
        end = FIX.get(r[-1]["i"], r[-1]["text"]).endswith((".", "?", "!"))
        spans.append([round((r[0]["start"] - LEAD) * FPS), round((r[-1]["end"] + (TAIL_END if end else TAIL)) * FPS), r, tag])
    for x, y in zip(spans, spans[1:]):                         # never overlap the next piece
        x[1] = min(x[1], y[0])
    for fa, fb, r, tag in spans:
        out_a = round(t_out, 4)
        for w in r:
            out_words.append({"i": w["i"], "text": FIX.get(w["i"], w["text"]), "t": round(out_a + w["start"] - fa / FPS, 3),
                              "e": round(out_a + w["end"] - fa / FPS, 3)})
        t_out += (fb - fa) / FPS
        pieces.append({"src_f": [fa, fb], "out_a": out_a, "out_b": round(t_out, 4), "tag": tag, "w": [r[0]["i"], r[-1]["i"]]})
    edl = {"fps": FPS, "total": round(t_out, 4), "pieces": pieces, "words": out_words}
    WORK.mkdir(exist_ok=True)
    ASSETS.mkdir(exist_ok=True)
    first, last = pieces[0]["src_f"][0], pieces[-1]["src_f"][1]
    ss = (first - 2.5) / FPS                                  # frame first-2 is the decoder's frame 0
    sel = "+".join(f"between(n\\,{p['src_f'][0] - first + 2}\\,{p['src_f'][1] - 1 - first + 2})" for p in pieces)
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ss:.6f}", "-t", f"{(last - first + 4) / FPS:.6f}", "-i", SRC, "-an",
         "-vf", f"select='{sel}',setpts=N/{FPS}/TB", "-r", FPS, "-c:v", "libx264", "-crf", "14", "-preset", "medium", "-g", "15",
         "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
         "-movflags", "+faststart", ASSETS / "aroll.mp4"])
    n = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames",
                            "-of", "csv=p=0", ASSETS / "aroll.mp4"], capture_output=True, text=True, check=True).stdout.strip())
    want = sum(p["src_f"][1] - p["src_f"][0] for p in pieces)
    if n != want:
        raise SystemExit(f"cut picture has {n} frames, the edit has {want}")
    voice(edl)
    json.dump(edl, open(WORK / "edl.json", "w"))
    print(f"cut: {len(pieces)} pieces, {edl['total']:.2f} s, {n} frames")
    return edl


def voice(edl: dict) -> None:
    """The voice (the DeepFilterNet-cleaned take) cut like the picture, 25 ms raised-cosine fades at every splice
    (8 ms left a click at one splice: qa.py --cuts)."""
    raw = run(["ffmpeg", "-v", "error", "-i", VOICE, "-ac", "1", "-ar", SR, "-f", "f32le", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.float32)
    parts, fade = [], int(0.025 * SR)
    r = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, fade))).astype(np.float32)
    for p in edl["pieces"]:
        x = v[int(p["src_f"][0] / FPS * SR):int(p["src_f"][1] / FPS * SR)].copy()
        x[:fade] *= r; x[-fade:] *= r[::-1]
        parts.append(x)
    run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", SR, "-ac", 1, "-i", "-", "-c:a", "pcm_f32le", WORK / "vo.wav"],
        input=np.concatenate(parts).tobytes())
    json.dump([p["out_a"] for p in edl["pieces"][1:]], open(WORK / "cuts.json", "w"))


# ------------------------------------------------------------------ the face per piece (YuNet, like films/*/face_track.py)
def faces(edl: dict) -> None:
    det = cv2.FaceDetectorYN.create(str(ROOT / "kit/models/face_detection_yunet_2023mar.onnx"), "", (960, 540), 0.6)
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(ASSETS / "aroll.mp4"), "-vf", "scale=960:540", "-f", "rawvideo",
                            "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    raw, last = [], None
    while True:
        buf = dec.stdout.read(960 * 540 * 3)
        if len(buf) < 960 * 540 * 3:
            break
        _, f = det.detect(np.frombuffer(buf, np.uint8).reshape(540, 960, 3))
        if f is not None and len(f):
            f = max(f, key=lambda r: r[2] * r[3])
            x, y, w, h = (float(q) * 2 for q in f[:4])
            last = (x + w / 2, y + h / 2, w / 1.078)
        raw.append(last)
    dec.wait()
    first = next(r for r in raw if r)
    raw = [r or first for r in raw]
    for p in edl["pieces"]:
        fs = raw[round(p["out_a"] * FPS):max(round(p["out_a"] * FPS) + 1, round(p["out_b"] * FPS))]
        p["face"] = [round(float(np.median([f[q] for f in fs])), 1) for q in range(3)]
    json.dump([[round(v, 1) for v in r] for r in raw], open(WORK / "aroll.face.json", "w"))
    json.dump(edl, open(WORK / "edl.json", "w"))
    print("faces:", [p["face"] for p in edl["pieces"][:3]], "...")


# ------------------------------------------------------------------ pages
def project(d: Path) -> None:
    d.mkdir(exist_ok=True)
    vendor.copy_assets(d)
    if d != HERE:                                           # the variants share the cut picture
        (d / "assets").mkdir(exist_ok=True)
        for f in ASSETS.glob("*.mp4"):
            dst = d / "assets" / f.name
            if not dst.exists() or dst.stat().st_mtime < f.stat().st_mtime:
                shutil.copy2(f, dst)


def page(d: Path, tpl: str, D: dict) -> None:
    html = vendor.inline((HERE / "src" / tpl).read_text()).replace("/*DATA*/", "const D = " + json.dumps(D) + ";")
    (d / "index.html").write_text(html.replace("__TOTAL__", f"{D['total']:.4f}"))


def labels(P: dict) -> list:
    """What the demo's label pill says, when (the director's own decisions)."""
    out = [[m["t0"], m["t1"], LABELS[m["kind"]], *SHORT[m["kind"]]] for m in P["moves"]]
    for s in P["shots"][1:]:
        if s["why"].startswith("reframe") and not any(m["t0"] - 0.05 <= s["t0"] < m["t1"] for m in P["moves"]):
            out.append([s["t0"], s["t0"] + 1.4, f"{LABELS['reframe']} ({s['s']:.2f}x)", SHORT["reframe"][0],
                        f"{SHORT['reframe'][1]}, {s['s']:.2f}x"])
    return sorted(out)


def build(edl: dict) -> None:
    pieces = [{k: p[k] for k in ("out_a", "out_b", "tag", "face")} for p in edl["pieces"]]
    track = json.load(open(WORK / "aroll.face.json"))         # per output frame: the camera frames each span on its own face
    base = {"pieces": pieces, "words": edl["words"], "fps": FPS, "tags": TAGS, "rules": RULES, "faces": track}
    # 16:9, camera v2 (director + baked blur)
    P = camera.plan(dict(base, view=[1920, 1080], framing={"max": "W", "ultra": "W"}, format="long"))
    blur = camera.bake(ASSETS / "aroll.mp4", P, ASSETS / "aroll_motion")
    print("\n".join(P["log"]))
    print("blur 16:9:", blur["stats"], [(w["f0"], w["f1"]) for w in blur["windows"]])
    project(HERE)
    D = {"total": edl["total"], "pieces": pieces, "words": edl["words"], "camera": camera.for_page(P, blur), "labels": labels(P)}
    page(HERE, "template.html", D)
    json.dump(P["cues"], open(WORK / "cues_after.json", "w"))
    # 16:9, the old camera (v1: a new framing on every cut, 1.0 / 1.08, a 2.5% push on long pieces)
    project(HERE / "before")
    page(HERE / "before", "template.html", dict(D, camera=None, labels=[[0, edl["total"], "Before: camera v1 (alternates 1.0 / 1.08 on every cut)"]]))
    # 9:16 panel (reel rules), the hook full screen for the first sentence
    hook_end = next(p["out_b"] for p in edl["pieces"] if p["w"][1] >= 385)
    R = camera.plan(dict(base, mode="panel", top=880, width=1080, height=1920, format="reel", hook=[0, hook_end], rules={}))
    rblur = camera.bake(ASSETS / "aroll.mp4", R, ASSETS / "aroll_motion_reel")
    print("\n".join(R["log"]))
    print("blur 9:16:", rblur["stats"], [(w["f0"], w["f1"], w["view"]) for w in rblur["windows"]])
    project(HERE / "reel")
    page(HERE / "reel", "reel.html", dict(D, camera=camera.for_page(R, rblur), labels=labels(R)))
    json.dump(R["cues"], open(WORK / "cues_reel.json", "w"))


# ------------------------------------------------------------------ audio and mux
def dec(p, ch=2):
    raw = run(["ffmpeg", "-v", "error", "-i", p, "-ac", ch, "-ar", SR, "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, ch).copy()


def mix(cues_file: Path, total: float, out: Path) -> None:
    """Voice + the camera's sound cues (swishes on snaps and zoom transitions), mastered to -14 LUFS / -1.5 dBTP."""
    n = int(total * SR)
    vo = dec(WORK / "vo.wav", 1)[:n, 0]
    mixed = np.repeat(np.pad(vo, (0, n - len(vo)))[:, None], 2, axis=1)
    names = {"swish": "whoosh/whoosh__air-woosh__mixkit-1489"}
    for c in json.load(open(cues_file)):
        x = dec(ROOT / "kit/sfx" / f"{names.get(c['name'], c['name'])}.wav")
        x = x / (np.abs(x).max() + 1e-9) * 10 ** ((-3 + c["db"]) / 20)
        i = int(c["t"] * SR); j = min(n, i + len(x))
        mixed[i:j] += x[:j - i]
    pre = WORK / "mix_pre.wav"
    run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", SR, "-ac", 2, "-i", "-", "-c:a", "pcm_f32le", pre], input=mixed.astype(np.float32).tobytes())
    m = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(pre), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    m = json.loads(m[m.rindex("{"):m.rindex("}") + 1])
    af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
          f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample=192000,alimiter=limit=0.79:level=false,aresample=48000")
    run(["ffmpeg", "-v", "error", "-y", "-i", pre, "-af", af, "-c:a", "pcm_s24le", out])
    pre.unlink()


def mux() -> None:
    edl = json.load(open(WORK / "edl.json"))
    R = HERE / "renders"
    mix(WORK / "cues_after.json", edl["total"], WORK / "mix_after.wav")
    mix(WORK / "cues_reel.json", edl["total"], WORK / "mix_reel.wav")
    aac = ["-c:a", "aac", "-aac_pns", "0", "-b:a", "256k", "-ar", SR, "-shortest", "-movflags", "+faststart"]
    run(["ffmpeg", "-v", "error", "-y", "-i", R / "after.mp4", "-i", WORK / "mix_after.wav", "-map", "0:v", "-map", "1:a", "-c:v", "copy", *aac, HERE / "demo_motion.mp4"])
    run(["ffmpeg", "-v", "error", "-y", "-i", R / "reel.mp4", "-i", WORK / "mix_reel.wav", "-map", "0:v", "-map", "1:a", "-c:v", "copy", *aac, HERE / "demo_reel.mp4"])
    # before | after, stacked (each 1920x540 high, letterboxed in 16:9: before on top)
    font = ROOT / "kit/fonts/Inter-700.ttf"
    lab = lambda s: f"drawtext=fontfile='{font}':text='{s}':x=28:y=h-th-28:fontsize=34:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=12"
    run(["ffmpeg", "-v", "error", "-y", "-i", R / "before.mp4", "-i", R / "after.mp4", "-i", WORK / "mix_after.wav", "-filter_complex",
         f"[0:v]scale=960:540:flags=lanczos,{lab('BEFORE  camera v1')}[a];[1:v]scale=960:540:flags=lanczos,{lab('AFTER  camera v2')}[b];"
         "[a][b]hstack=inputs=2,pad=1920:1080:0:270:color=0x1b1815[v]", "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-crf", "16",
         "-preset", "medium", "-pix_fmt", "yuv420p", *aac, HERE / "demo_before_after.mp4"])
    print("-> demo_motion.mp4, demo_before_after.mp4, demo_reel.mp4")


if __name__ == "__main__":
    if "--mux" in sys.argv:
        mux()
    elif "--voice" in sys.argv:
        voice(json.load(open(WORK / "edl.json")))
    else:
        e = cut() if "--keep-cut" not in sys.argv or not (WORK / "edl.json").exists() else json.load(open(WORK / "edl.json"))
        if "face" not in e["pieces"][0]:
            faces(e)
        build(e)
