"""Full-frame grade for a talking head in a real room (no cut-out, so no matte edges can ever show).

The room stays; the look comes from light, not masks:
  1. tone: the clip's own black point and wall level are measured, then one luma curve sets blacks deep, lifts skin and
     rolls the bright wall off so the subject is no longer darker than the background (top channels: subject brightest);
  2. a soft key light that follows the face (a wide gaussian from the head track, offset to one side for shape, slightly
     warm) and a gentle falloff on the far cheek; it also brushes the wall a little, the way a real lamp would;
  3. an elliptical vignette that pulls the frame edges down, warm highlights / neutral shadows, saturation up except skin;
  4. luma-only sharpening (phone footage is usually upscaled) and a whisper of fine grain so it reads as film, not plastic.

The head track comes from the Vision person mask at quarter resolution (kit/bin/personseg), smoothed over time, and is
written next to the output as <out>.face.json: per frame [cx, cy, head_w] in output pixels (for framing / punch-ins).

    python3 kit/look/grade.py <clip.mp4> <out.mp4> [--light=1.0] [--test=5,40,90]   (--test writes before/after JPGs)
    python3 kit/look/grade.py <clip.mp4> <out.mp4> --look=cinematic                 (one look: kit/look/looks.py LOOKS)
    python3 kit/look/grade.py <clip.mp4> <out.mp4> --looks=looks.json               ([{t, look, fade}]: looks per scene)
    python3 kit/look/grade.py <clip.mp4> sheet.jpg --sheet=12.5 [--track=...]        (one frame in every look, labelled)
    ... --room=shelf                    a room profile (looks.ROOMS): tone targets for a different background
    ... --matte=<dir>                   person mattes (kit/bin/personseg --mask on the clip's frames, f00001.png ...):
                                        portrait mode, the room defocused and set back (per look, from the room's "bg")

To grade only what an edit keeps: track the whole take once (`--track-only`), cut the picture, then grade the cut with
`--track=<take>.face.json --map=<cut>.map.json` (the map gives each cut frame's frame in the take).

Look v2 (opt-in, kit/look/v2.py; the same looks, rooms, mattes, --looks plans, --test and --sheet):
    ... --v2                            per-shot exposure / white balance from the face, sigmoid tone curve, subtractive
                                        saturation, skin secondaries, halation, grain and dither (see kit/look/README.md)
    ... --v2 --track-only               a YuNet face track (kit/look/faces.py) instead of the person-mask head track
    ... --shots=12.4,80.2               shot boundaries in seconds (each shot gets its own balance; default: one shot)
    ... --balance=<out>.balance.json    reuse the per-shot balance of an earlier grade (written next to every v2 output)
    ... --reel                          Reels/Shorts finish: lifted shadows (+0.02), half grain, gentler vignette
"""
import json
import shutil
import subprocess
import sys
import tempfile
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from look import luma, skin_weight, smoothstep  # noqa: E402
import looks as LK  # noqa: E402

# the targets, light, colour and finish of every look live in kit/look/looks.py (LOOKS); "natural" is the approved
# preset_paper_studio grade: black 0.03, skin 0.50, wall 0.87, key 0.20, falloff 0.08, vignette 0.16, sat 1.10, grain 1 %


def arg(name, default=None):
    return next((a.split("=", 1)[1] for a in sys.argv if a.startswith(f"--{name}=")), default)


def probe(src):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
                          "-of", "csv=p=0", str(src)], capture_output=True, text=True, check=True).stdout.strip().split(",")
    return int(out[0]), int(out[1]), round(eval(out[2]))


def head_track(src, W, H):
    """Per frame (cx, cy, head width) in full-res pixels, from Vision masks at quarter size; smoothed (median + EMA)."""
    tmp = Path(tempfile.mkdtemp(prefix="grade_"))
    try:
        fr, mk = tmp / "f", tmp / "m"
        fr.mkdir()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", f"scale={W // 4}:{H // 4}", "-q:v", "3", str(fr / "f%05d.jpg")], check=True)
        subprocess.run([str(KIT / "bin/personseg"), str(fr), str(mk), "--mask"], check=True, capture_output=True)
        raw = []
        for p in sorted(mk.glob("*.png")):
            a = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) > 127
            rows = np.where(a.sum(1) > 3)[0]
            if not len(rows):
                raw.append(None); continue
            y0 = rows[0]
            xs = np.where(a[min(a.shape[0] - 1, y0 + int(0.07 * a.shape[0]))])[0]
            if len(xs) < 4:
                raw.append(None); continue
            hw = (xs[-1] - xs[0])
            raw.append(((xs[0] + xs[-1]) / 2 * 4, (y0 + 0.75 * hw) * 4, hw * 4))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    last = next((r for r in raw if r), (W / 2, H * 0.42, W * 0.16))
    filled = []
    for r in raw:
        last = r or last
        filled.append(last)
    arr = np.array(filled, np.float64)
    k = 7
    pad = np.pad(arr, ((k, k), (0, 0)), mode="edge")
    med = np.array([np.median(pad[i:i + 2 * k + 1], 0) for i in range(len(arr))])
    out, s = [], med[0]
    for m in med:                                   # slow EMA: the light drifts with the head, it never jitters
        s = s + 0.12 * (m - s)
        out.append(s.copy())
    return np.array(out)


def levels(src):
    """The clip's black point (0.5th pct luma) and its wall level (median of the top band), over sampled frames."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vf", "fps=0.5,scale=480:270", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 270, 480, 3).astype(np.float32) / 255
    y = luma(fr)
    sk = skin_weight(fr) > 0.6
    return float(np.percentile(y, 0.5)), float(np.median(y[:, 5:60])), float(np.median(y[sk])) if sk.any() else 0.4


def tone(y, lo, wall, skin, tg):
    """Monotone luma curve through (lo, black), (skin, skin), (wall, wall) targets with a soft toe and a shoulder."""
    xs = np.array([0.0, lo, skin, wall, 1.0])
    ys = np.array([0.0, tg["black"], tg["skin"], tg["wall"], min(0.93, tg["wall"] + (1 - wall) * 0.8)])
    xs, ys = np.maximum.accumulate(xs + np.arange(5) * 1e-4), np.maximum.accumulate(ys)
    # smooth monotone interpolation (PCHIP-like via cv2-free numpy): piecewise cubic Hermite with Fritsch-Carlson slopes
    h = np.diff(xs); d = np.diff(ys) / h
    m = np.zeros(5); m[0], m[-1] = d[0], d[-1]
    for i in range(1, 4):
        m[i] = 0 if d[i - 1] * d[i] <= 0 else 3 * (h[i - 1] + h[i]) / ((2 * h[i] + h[i - 1]) / d[i - 1] + (h[i] + 2 * h[i - 1]) / d[i])
    yi = np.clip(y, 0, 1)
    i = np.clip(np.searchsorted(xs, yi) - 1, 0, 3)
    t = (yi - xs[i]) / h[i]
    t2, t3 = t * t, t * t * t
    return (2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * m[i] + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h[i] * m[i + 1]


_G = {}
LS = 4                                      # the light and vignette are smooth: computed at 1/4 size, then upsampled


def _lut(x, a, b):
    """smoothstep(a, b, x) as a 1024-entry table lookup on x in 0..1 (x is clipped)."""
    key = ("ss", a, b)
    if key not in _G:
        _G[key] = smoothstep(a, b, np.linspace(0, 1, 1024, dtype=np.float32)).astype(np.float32)
    return _G[key][np.clip((x * 1023 + 0.5).astype(np.int32), 0, 1023)]


def _look_frame(img, cx, cy, hw, W, H, lo, wall, skin, light, seed, name, room=None, matte=None):
    """One frame through one look: tone targets -> face key / falloff / vignette -> colour (LUT) -> halation ->
    portrait background (with a person matte) -> sharpen, grain. `room` picks a room profile (looks.ROOMS)."""
    key_ = (name, room)
    if ("look",) + key_ not in _G:
        _G[("look",) + key_] = LK.look_for(name, room)
    L = _G[("look",) + key_]
    lt, fin = L["light"], L["finish"]
    name = key_
    if ("grid", name) not in _G:
        h4, w4 = H // LS, W // LS
        yy, xx = (np.mgrid[0:h4, 0:w4].astype(np.float32) + 0.5) * LS
        r = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H * 0.46) / (H * 0.70)) ** 2)
        _G[("grid", name)] = (yy, xx, (1 - lt["vignette"] * smoothstep(0.45, 1.25, r)).astype(np.float32))
        lut = tone(np.linspace(0, 1, 4096), lo, wall, skin, lt)
        _G[("tone", name)] = (lut / np.maximum(np.linspace(0, 1, 4096), 1e-4)).astype(np.float32)   # gain per luma level
        if L["colour"].get("mode") != "paper":
            _G[("lut", name)] = LK.bake(name[0], colour=L["colour"], tag=room or "")
    if "grain" not in _G:
        rng = np.random.default_rng(7)                                                         # 6 unit grain plates, cycled
        _G["grain"] = [cv2.GaussianBlur(rng.standard_normal((H, W)).astype(np.float32), (0, 0), 0.7) for _ in range(6)]
    yy, xx, vig = _G[("grid", name)]
    y = luma(img)
    out = img * _G[("tone", name)][np.clip((y * 4095 + 0.5).astype(np.int32), 0, 4095)][..., None]
    # light: a wide soft key on the camera-left cheek, a little falloff on the far side; both centred on the head track
    key = np.exp(-(((xx - (cx - 0.30 * hw)) / (1.05 * hw)) ** 2 + ((yy - (cy - 0.05 * hw)) / (1.25 * hw)) ** 2))
    far = np.exp(-(((xx - (cx + 0.55 * hw)) / (0.55 * hw)) ** 2 + ((yy - cy) / (1.0 * hw)) ** 2))
    # the light lands mostly on skin (a soft colour weight, no edges); the wall only catches a little spill
    small = cv2.resize(out, (W // LS, H // LS), interpolation=cv2.INTER_AREA)
    sk = cv2.GaussianBlur(skin_weight(small), (0, 0), 5 / LS)
    ks = lt.get("key_skin", 0.55)                                         # how much the key prefers skin (strong keys: less, or it looks patchy)
    key = key * ((1 - ks) + ks * sk)
    if matte is not None:                                                 # with a matte the key lands on the person, not on tan book spines
        key = key * (0.3 + 0.7 * cv2.GaussianBlur(cv2.resize(matte, (W // LS, H // LS), interpolation=cv2.INTER_AREA), (0, 0), 3))
    gain = cv2.resize(((1 + light * (lt["key"] * key - lt["fall"] * far)) * vig).astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR)
    tint = cv2.resize((light * lt.get("key_warm", 0.012) * key).astype(np.float32), (W, H), interpolation=cv2.INTER_LINEAR)
    out = out * gain[..., None] + tint[..., None] * np.array([1.0, 0.5, -0.4], np.float32)
    # colour: natural computes its paper-studio colour directly (exact); every other look goes through its baked LUT
    if L["colour"].get("mode") == "paper":
        out = LK.colour_op(np.clip(out, 0, 1), L["colour"]).astype(np.float32)
    else:
        out = LK.apply_lut(out, _G[("lut", name)])
    out = LK.halation(out, fin.get("halation", 0.0))
    bg = L.get("bg")
    if matte is not None and bg:                                          # portrait: the room behind is defocused, calmer, a little darker
        h2, w2 = H // 2, W // 2
        o2 = cv2.resize(out, (w2, h2), interpolation=cv2.INTER_AREA)
        m2 = cv2.resize(matte, (w2, h2), interpolation=cv2.INTER_AREA)
        b2 = 1 - m2
        sg = bg["blur"] * H / 1080 / 2
        # 1) defocus: a normalised (masked) blur, so the person never bleeds into the room; composited with a slightly
        #    eroded matte, so the unblurred rim of room that the matte always includes around hair is defocused too
        bl = cv2.GaussianBlur(o2 * b2[..., None], (0, 0), sg) / (cv2.GaussianBlur(b2, (0, 0), sg)[..., None] + 1e-3)
        me = cv2.GaussianBlur(cv2.erode(m2, np.ones((3, 3), np.uint8)), (0, 0), 1.0)
        me = cv2.resize(me, (W, H), interpolation=cv2.INTER_LINEAR)[..., None]
        out = out * me + cv2.resize(bl, (W, H), interpolation=cv2.INTER_LINEAR) * (1 - me)
        # 2) separation as light, not as a cut-out: the room falls off smoothly away from the person (a wide blur of the
        #    matte), so darkening never draws a line around hair or fingers
        soft = cv2.resize(cv2.GaussianBlur(m2, (0, 0), 24 * H / 1080 / 2), (W, H), interpolation=cv2.INTER_LINEAR)
        soft = np.clip(soft * 1.25, 0, 1)[..., None]
        yb = luma(out)[..., None]
        sat = bg["sat"] + (1 - bg["sat"]) * soft
        out = (yb + (out - yb) * sat) * (bg["gain"] + (1 - bg["gain"]) * soft)
    # luma-only unsharp mask (on the person only when the room is defocused), then fine grain
    yo = luma(out)
    det = yo - cv2.GaussianBlur(yo, (0, 0), 1.3)
    if matte is not None and bg:
        det = det * (0.3 + 0.7 * matte)
    out = out + (fin.get("sharpen", 0.45) * det)[..., None]
    if fin.get("grain"):
        out = out + (_G["grain"][seed % 6] * fin["grain"] * (1 - _lut(yo, 0.6, 1.0)))[..., None]
    return np.clip(out, 0, 1)


def load_matte(path, W, H):
    """A person matte (kit/bin/personseg --mask PNG, any size) as float32 HxW 0..1: the soft edge is tightened a little
    and feathered by ~1.5 px so hair and fingers blend instead of showing a line. Missing file -> None."""
    m = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if m is None:
        return None
    m = cv2.resize(m, (W, H), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255
    m = np.clip((m - 0.08) / 0.84, 0, 1)
    return cv2.GaussianBlur(m, (0, 0), 1.5 * H / 1080)


_V2P = {}


def _v2_frame(buf, track, W, H, seed, look, room, matte, opts):
    """One frame through look v2 (kit/look/v2.py) with this frame's shot balance (opts["bal"][look])."""
    import faces as FC
    import v2 as V2
    img = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
    face = FC.from_track(*[float(v) for v in track])

    def one(name, u8):
        key = (name, room, opts.get("reel", False))
        if key not in _V2P:
            _V2P[key] = V2.params(name, room, opts.get("reel", False))
        return V2.grade(img, opts["bal"][name], _V2P[key], face, matte, seed, out_u8=u8)
    if isinstance(look, str):
        return one(look, True).tobytes()
    a, b, m = look
    out = one(a, False) * np.float32(1 - m) + one(b, False) * np.float32(m)
    return V2.quantise(out, seed, _V2P[(b, room, opts.get("reel", False))]["dither"]).tobytes()


def grade_frame(job):
    """job = (rgb bytes, (cx, cy, head_w), W, H, lo, wall, skin, light, frame index, look[, room, matte path, v2 opts])
    where look is a name or (name_a, name_b, mix) during a crossfade between looks (a 'lights dim' moment). With v2 opts
    ({"bal": {look: balance}, "reel": bool}) the frame goes through look v2 instead."""
    buf, (cx, cy, hw), W, H, lo, wall, skin, light, seed = job[:9]
    look = job[9] if len(job) > 9 else "natural"
    room = job[10] if len(job) > 10 else None
    mpath = job[11] if len(job) > 11 else None
    matte = load_matte(mpath, W, H) if mpath else None
    if len(job) > 12 and job[12]:
        return _v2_frame(buf, (cx, cy, hw), W, H, seed, look, room, matte, job[12])
    cx, cy, hw = float(cx), float(cy), float(hw)
    img = np.frombuffer(buf, np.uint8).reshape(H, W, 3).astype(np.float32) * np.float32(1 / 255)
    if isinstance(look, str):
        out = _look_frame(img, cx, cy, hw, W, H, lo, wall, skin, light, seed, look, room, matte)
    else:
        a, b, m = look
        out = (_look_frame(img, cx, cy, hw, W, H, lo, wall, skin, light, seed, a, room, matte) * (1 - m)
               + _look_frame(img, cx, cy, hw, W, H, lo, wall, skin, light, seed, b, room, matte) * m)
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8).tobytes()


def look_at(t, plan):
    """The look at time t from a list of switches [{t, look, fade}] (fade 0 = a hard switch, e.g. on a cut)."""
    cur, prev, start, fade = plan[0]["look"], None, plan[0]["t"], 0.0
    for p in plan:
        if t >= p["t"]:
            prev, cur, start, fade = cur, p["look"], p["t"], p.get("fade", 0.0)
    if prev and prev != cur and fade > 0 and t < start + fade:
        m = (t - start) / fade
        return (prev, cur, m * m * (3 - 2 * m))
    return cur


def v2_balances(src, plan, track, mp, room, reel, fps, n_frames):
    """Look v2's per-shot balance: [(t0, t1, {look: balance})] for the shots in --shots (default one shot), each from
    up to 12 frames sampled across the shot (YuNet face on the frame, else the track; the person matte when given)."""
    import faces as FC
    import v2 as V2
    dur = n_frames / fps
    cuts = [0.0] + sorted(float(t) for t in arg("shots").split(",")) + [dur] if arg("shots") else [0.0, dur]
    names = sorted({p["look"] for p in plan} | set(arg("sheet-looks", ",".join(LK.LOOKS)).split(",") if arg("sheet") else []))
    W, H, _ = probe(src)
    shots = []
    for t0, t1 in zip(cuts[:-1], cuts[1:]):
        n = int(np.clip((t1 - t0) / 3, 4, 12))
        frames = []
        for k in range(n):
            t = t0 + (k + 0.5) * (t1 - t0) / n
            i = min(int(t * fps), n_frames - 1)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                 capture_output=True, check=True).stdout
            if len(raw) < W * H * 3:
                continue
            im = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
            face = FC.detect(im) or FC.from_track(*track[min(i, len(track) - 1)])
            m = load_matte(mp(i), W, H) if mp(i) else None
            frames.append((im.astype(np.float32) / 255, face, m))
        bal = {nm: V2.analyse(frames, V2.params(nm, room, reel)) for nm in names}
        shots.append((t0, t1, bal))
        b0 = bal["natural" if "natural" in bal else names[0]]
        print(f"v2 shot {t0:.1f}-{t1:.1f}s ({'natural' if 'natural' in bal else names[0]}): ev {b0['ev']:+.2f}, wb {b0['wb']}, skin rot {b0['skin_rot']:+.1f} deg, flare {b0['flare']:.5f}"
              f" (skin {b0['src'].get('skin_hue', 0):.1f} deg / {b0['src'].get('skin_c', 0):.3f} -> {b0['out'].get('skin_hue', 0):.1f} / {b0['out'].get('skin_c', 0):.3f})")
    return shots


def _worker_init():
    """One OpenCV thread per worker: 8 processes x OpenCV's own thread pool oversubscribed the cores (2.5x the CPU time
    went to the kernel)."""
    cv2.setNumThreads(1)


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    light = float(arg("light", 1.0))
    room = arg("room")
    if room and room not in LK.ROOMS:
        raise SystemExit(f"unknown room {room!r} (one of {sorted(LK.ROOMS)})")
    mdir = arg("matte")
    mp = (lambda i: str(Path(mdir) / f"f{i + 1:05d}.png")) if mdir else (lambda i: None)
    plan = [{"t": 0.0, "look": arg("look", "natural")}]
    if arg("looks"):
        plan = sorted(json.load(open(arg("looks"))), key=lambda p: p["t"])
    for p in plan:
        if p["look"] not in LK.LOOKS:
            raise SystemExit(f"unknown look {p['look']!r} (one of {sorted(LK.LOOKS)})")
    W, H, fps = probe(src)
    use_v2, reel = "--v2" in sys.argv, "--reel" in sys.argv
    if use_v2:
        lo = wall = skin = 0.0                                               # v2 measures per shot (v2_balances)
    else:
        lo, wall, skin = [float(v) for v in arg("levels").split(",")] if arg("levels") else levels(src)   # --levels: match an earlier grade
        print(f"levels: black {lo:.3f}, wall {wall:.3f}, skin {skin:.3f}")
    if arg("track"):
        track = np.array(json.load(open(arg("track"))))
        if arg("map"):
            track = track[np.clip(np.array(json.load(open(arg("map")))), 0, len(track) - 1)]
    else:
        if use_v2:                                                           # v2 wants the face, not the hairline
            import faces as FC
            track = np.array(FC.track_clip(str(src)))
        else:
            track = head_track(src, W, H)
        json.dump([[round(float(v), 1) for v in r] for r in track], open(str(out) + ".face.json", "w"))
        if "--track-only" in sys.argv:
            print(f"track: {len(track)} frames -> {out}.face.json")
            return
    v2o = lambda i: None                                                     # noqa: E731  (per frame: v2 options or None)
    if use_v2:
        if arg("balance"):
            shots = [(s["t0"], s["t1"], s["bal"]) for s in json.load(open(arg("balance")))]
        else:
            shots = v2_balances(src, plan, track, mp, room, reel, fps, len(track))
            Path(str(out) + ".balance.json").write_text(json.dumps([{"t0": a, "t1": b, "bal": c} for a, b, c in shots], indent=1))
        def v2o(i):  # noqa: E306
            t = i / fps
            bal = next((c for a, b, c in shots if a <= t < b), shots[-1][2])
            return {"bal": bal, "reel": reel}
    test = arg("test")
    if test:
        for t in (float(x) for x in test.split(",")):
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(src), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                 capture_output=True, check=True).stdout
            g = np.frombuffer(grade_frame((raw, track[min(len(track) - 1, int(t * fps))], W, H, lo, wall, skin, light, 1, look_at(t, plan), room, mp(int(t * fps)), v2o(int(t * fps)))), np.uint8).reshape(H, W, 3)
            o = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
            cv2.imwrite(f"{out.with_suffix('')}_test_{t:g}.jpg", cv2.cvtColor(np.hstack([o, g]), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
        print("test frames written")
        return
    if arg("sheet"):                                                         # one frame in every look, labelled
        t = float(arg("sheet"))
        names = arg("sheet-looks", ",".join(n for n in LK.LOOKS)).split(",")
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(src), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        tiles = [("source", np.frombuffer(raw, np.uint8).reshape(H, W, 3))]
        import scopes
        rows_ = []
        for n in ["source"] + names:
            im = tiles[0][1] if n == "source" else np.frombuffer(grade_frame((raw, track[min(len(track) - 1, int(t * fps))], W, H, lo, wall, skin, light, 1, n, room, mp(int(t * fps)), v2o(int(t * fps)))), np.uint8).reshape(H, W, 3)
            if n != "source":
                tiles.append((n, im))
            st = scopes.stats(im.astype(np.float32) / 255, face=track[min(len(track) - 1, int(t * fps))])
            rows_.append(f"{n:10s} " + "  ".join(f"{k}={st.get(k, float('nan')):.3f}" for k in ("black", "white", "skin_luma", "skin_off", "skin_sat", "wall_luma", "wall_chroma", "wall_hue", "contrast")))
        print("\n".join(rows_))
        tw = 640
        th = int(H * tw / W)
        cols = 3 if len(tiles) > 4 else 2
        rows = -(-len(tiles) // cols)
        sheet = np.full((rows * th, cols * tw, 3), 24, np.uint8)
        for k, (n, im) in enumerate(tiles):
            r, c = divmod(k, cols)
            small = cv2.resize(im, (tw, th), interpolation=cv2.INTER_AREA).copy()
            cv2.rectangle(small, (0, 0), (14 + 15 * len(n), 34), (20, 18, 16), -1)
            cv2.putText(small, n, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (243, 238, 230), 2, cv2.LINE_AA)
            sheet[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = small
        cv2.imwrite(str(out), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
        print(f"{out}: {len(tiles)} looks at {t}s")
        return
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(src), "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                            "-c:v", "libx264", "-crf", "13", "-preset", "slow", "-tune", "film", "-g", str(fps), "-pix_fmt", "yuv420p",
                            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)

    # frames go to the pool through a bounded window (an unbounded imap would decode the whole clip into memory and
    # swap): decoding, grading and encoding overlap, and frames are written in order
    from collections import deque
    pending, n, i = deque(), 0, 0
    with Pool(8, initializer=_worker_init) as pool:
        while True:
            buf = dec.stdout.read(W * H * 3)
            if len(buf) < W * H * 3:
                break
            pending.append(pool.apply_async(grade_frame, ((buf, track[min(i, len(track) - 1)], W, H, lo, wall, skin, light, i,
                                                          look_at(i / fps, plan), room, mp(i), v2o(i)),)))
            i += 1
            while pending and (len(pending) >= 24 or pending[0].ready()):
                enc.stdin.write(pending.popleft().get())
                n += 1
        while pending:
            enc.stdin.write(pending.popleft().get())
            n += 1
    enc.stdin.close()
    if enc.wait():
        raise SystemExit("encode failed")
    print(f"{out.name}: {n} frames graded")


if __name__ == "__main__":
    main()
