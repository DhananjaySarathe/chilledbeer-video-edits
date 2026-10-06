"""Scopes and numbers for judging a grade like a colourist, instead of eyeballing a thumbnail.

    python3 kit/look/scopes.py <video|image> <seconds> [out.png]        -> the frame + waveform + vectorscope (skin line)
    python3 kit/look/scopes.py <video|image> <seconds> --json           -> the numbers only

Numbers (0..1 display values unless noted):
  black / white      1st / 99th percentile luma (deep blacks ~0.02-0.06, whites ~0.85-0.95, nothing pinned at 0 or 1)
  clip_lo / clip_hi  share of pixels crushed below 0.01 / blown above 0.99
  skin_luma          median luma of skin (talking heads: ~0.40-0.55)
  skin_hue           skin hue angle on the vectorscope (atan2(Cr, Cb), degrees); the skin-tone line is ~123
  skin_off           skin hue minus 123: + = toward yellow/olive, - = toward red/magenta (keep within about +-8)
  skin_sat           skin chroma (|CbCr|); natural skin ~0.05-0.11, above ~0.14 reads orange
  wall_luma          median luma of the background band above the head
  wall_cast          background chroma and hue: a "neutral" wall has chroma < 0.02; hue tells the cast
  contrast           luma std over the frame

QA for a graded clip (look v2 targets, measured on the YuNet face box; a pass/warn table per frame + a summary):

    python3 kit/look/scopes.py qa <video|image> [more ...] [--every=2] [--faces=<source clip>] [--track=face.json]
                                  [--matte=<dir>] [--json=out.json]

  skin_hue   atan2(Cr, Cb) of the face (BT.709), target 123 +- 4 deg; shot-to-shot drift <= 2 deg
  skin_c     2|CbCr| of the face (1.0 = the vectorscope's edge), target 0.20-0.32 (orange above ~0.32)
  skin_y     mean Y' of the face 0.40-0.55, skin_p90 <= 0.70
  black      0.5th-percentile Y' >= 0.01 (crushed below), <= 0.07 (milky above)
  clip       largest clipped (Y' > 0.985) blob as % of the frame: lamps only, < 1 %
  sep        face Y' minus background Y' >= 0.08 (background: matte < 0.05, else beside and above the head)
  bg_c       background median chroma <= skin chroma
"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from look import luma, skin_weight  # noqa: E402

SKIN_LINE = 123.0


def ycbcr(img):
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return y, (b - y) / 1.8556, (r - y) / 1.5748


def stats(img, face=None):
    """img: HxWx3 float 0..1 (display RGB). face = (cx, cy, head_w) from the head track: skin is then measured on the
    cheeks and forehead (a fixed region, so the number doesn't move with the grade); without it, by a skin-colour mask."""
    H, W = img.shape[:2]
    y, cb, cr = ycbcr(img)
    if face is not None:
        cx, cy, hw = face
        sk = np.zeros((H, W), bool)
        sk[int(cy - 0.42 * hw):int(cy + 0.12 * hw), int(cx - 0.32 * hw):int(cx + 0.32 * hw)] = True
        sk &= (y > 0.12) & (y < 0.95)                                       # not hair / eyes / speculars
    else:
        sk = skin_weight(img) > 0.6
    sk[: int(H * 0.08)] = False
    top = np.zeros_like(sk); top[int(H * 0.04):int(H * 0.22), :] = True
    top &= ~(skin_weight(img) > 0.3)
    top[:, int(W * 0.35):int(W * 0.65)] = False                         # the head is usually in the middle
    out = {"black": float(np.percentile(y, 1)), "white": float(np.percentile(y, 99)),
           "clip_lo": float((y < 0.01).mean()), "clip_hi": float((y > 0.99).mean()), "contrast": float(y.std())}
    if sk.sum() > 200:
        scb, scr = float(np.median(cb[sk])), float(np.median(cr[sk]))
        hue = float(np.degrees(np.arctan2(scr, scb)))
        out.update({"skin_luma": float(np.median(y[sk])), "skin_hue": hue, "skin_off": hue - SKIN_LINE, "skin_sat": float(np.hypot(scb, scr))})
    if top.sum() > 200:
        wcb, wcr = float(np.median(cb[top])), float(np.median(cr[top]))
        out.update({"wall_luma": float(np.median(y[top])), "wall_chroma": float(np.hypot(wcb, wcr)), "wall_hue": float(np.degrees(np.arctan2(wcr, wcb)))})
    return {k: round(v, 4) for k, v in out.items()}


def scope_image(img, size=360):
    """Frame | luma waveform | vectorscope (with the skin-tone line), side by side."""
    H, W = img.shape[:2]
    fh = size
    fw = int(W * fh / H)
    frame = cv2.resize((img * 255).astype(np.uint8), (fw, fh), interpolation=cv2.INTER_AREA)
    y, cb, cr = ycbcr(cv2.resize(img, (fw, fh), interpolation=cv2.INTER_AREA))
    wf = np.zeros((fh, fw), np.float32)                                    # waveform: per column, a luma histogram
    rows = np.clip(((1 - y) * (fh - 1)).astype(int), 0, fh - 1)
    np.add.at(wf, (rows, np.tile(np.arange(fw), (fh, 1))), 1)
    wf = np.clip(wf / (wf.max() * 0.08 + 1e-6), 0, 1)
    wimg = np.zeros((fh, fw, 3), np.uint8)
    wimg[..., 1] = (wf * 230).astype(np.uint8); wimg[..., 0] = (wf * 120).astype(np.uint8); wimg[..., 2] = (wf * 120).astype(np.uint8)
    for v in (0.1, 0.5, 0.9):
        cv2.line(wimg, (0, int((1 - v) * (fh - 1))), (fw, int((1 - v) * (fh - 1))), (90, 90, 90), 1)
    vs = np.zeros((fh, fh), np.float32)                                    # vectorscope: CbCr density
    sc = fh / 2 / 0.5
    px = np.clip((fh / 2 + cb * sc).astype(int), 0, fh - 1); py = np.clip((fh / 2 - cr * sc).astype(int), 0, fh - 1)
    np.add.at(vs, (py.ravel(), px.ravel()), 1)
    vs = np.clip(np.log1p(vs) / np.log1p(vs.max() + 1e-6), 0, 1)
    vimg = np.zeros((fh, fh, 3), np.uint8)
    for c in range(3):
        vimg[..., c] = (vs * [220, 220, 220][c]).astype(np.uint8)
    cv2.circle(vimg, (fh // 2, fh // 2), int(0.35 * sc), (70, 70, 70), 1)
    a = np.radians(SKIN_LINE)
    cv2.line(vimg, (fh // 2, fh // 2), (int(fh / 2 + np.cos(a) * fh / 2), int(fh / 2 - np.sin(a) * fh / 2)), (60, 140, 230), 1)
    return np.hstack([cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), wimg, vimg])


def frame(src, t):
    if src.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        return cv2.cvtColor(cv2.imread(src), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", src, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    return cv2.cvtColor(cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB).astype(np.float32) / 255


# ------------------------------------------------------------------------------------------------------------ v2 QA
TARGETS = {  # name: (lo, hi, unit, what a miss looks like)
    "skin_hue": (SKIN_LINE - 4, SKIN_LINE + 4, "deg", "off the skin line (> yellow/olive, < magenta)"),
    "skin_c": (0.20, 0.32, "", "pale / orange skin"),
    "skin_y": (0.40, 0.55, "", "dark / hot face"),
    "skin_p90": (0.0, 0.70, "", "hot spots on the face"),
    "black": (0.01, 0.07, "", "crushed / milky blacks"),
    "clip": (0.0, 1.0, "%", "large clipped areas"),
    "sep": (0.08, 1.0, "", "face not separated from the room"),
    "bg_c": (0.0, None, "", "room more colourful than the skin"),
}


def measure(img, face=None, matte=None):
    """The v2 numbers for one frame. img: HxWx3 display RGB (uint8 or float 0..1); face: faces.detect() dict (detected
    here when None); matte: person matte HxW 0..1 (optional, sharpens the background measure)."""
    import faces as FC
    f = img.astype(np.float32) / 255 if img.dtype == np.uint8 else img.astype(np.float32)
    H, W = f.shape[:2]
    face = face or FC.detect(f)
    y, cb, cr = ycbcr(f)
    out = {"black": float(np.percentile(y, 0.5))}
    hot = (y > 0.985).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(hot, connectivity=8)
    out["clip"] = float(st[1:, cv2.CC_STAT_AREA].max() / (H * W) * 100) if n > 1 else 0.0
    out["crushed"] = float((y < 0.004).mean() * 100)
    if face is None:
        return out
    px = FC.skin_pixels(f, face)
    if len(px) > 50:
        sy, scb, scr = ycbcr(px)
        mcb, mcr = float(np.median(scb)), float(np.median(scr))
        h = np.degrees(np.arctan2(scr, scb))
        out.update({"skin_hue": float(np.degrees(np.arctan2(mcr, mcb))), "skin_c": 2 * float(np.hypot(mcb, mcr)),
                    "skin_y": float(sy.mean()), "skin_p90": float(np.percentile(sy, 90)),
                    "skin_spread": float(1.4826 * np.median(np.abs(h - np.median(h))))})
    x0, y0, w, h_ = face["box"]
    cx, cy = x0 + w / 2, y0 + h_ / 2
    if matte is not None:
        bg = cv2.resize(matte.astype(np.float32), (W, H)) < 0.05
    else:
        yy, xx = np.mgrid[0:H, 0:W]
        bg = (np.abs(xx - cx) > 0.95 * w) & (yy < cy + 0.5 * h_)
    if bg.sum() > 500 and "skin_y" in out:
        out["sep"] = out["skin_y"] - float(np.median(y[bg]))
        out["bg_c"] = float(np.median(2 * np.hypot(cb[bg], cr[bg])))
        out["bg_y"] = float(np.median(y[bg]))
    return out


def verdict(m):
    """{name: 'ok' | 'WARN'} against TARGETS (bg_c is compared with the skin chroma)."""
    v = {}
    for k, (lo, hi, _, _) in TARGETS.items():
        if k not in m:
            continue
        if k == "bg_c":
            v[k] = "ok" if m[k] <= m.get("skin_c", 1) else "WARN"
        else:
            v[k] = "ok" if lo <= m[k] <= hi else "WARN"
    return v


COLS = ("skin_hue", "skin_c", "skin_y", "skin_p90", "black", "clip", "sep", "bg_c")


def table(rows, spread=True):
    """rows: [(label, measure dict)] -> a fixed-width pass/warn table (a trailing '!' marks a miss). With `spread` the
    skin-hue range over all rows is added (meaningful when the rows are one shot)."""
    head = f"{'frame':24s}" + "".join(f"{c:>10s}" for c in COLS) + "   misses"
    lines = [head, "-" * len(head)]
    for label, m in rows:
        v = verdict(m)
        cells = []
        for c in COLS:
            if c not in m:
                cells.append(f"{'-':>10s}")
                continue
            val = f"{m[c]:.1f}" if c in ("skin_hue",) else (f"{m[c]:.2f}" if c == "clip" else f"{m[c]:.3f}")
            cells.append(f"{val + ('!' if v.get(c) == 'WARN' else ' '):>10s}")
        miss = [c for c in COLS if v.get(c) == "WARN"]
        lines.append(f"{label[:24]:24s}" + "".join(cells) + "   " + (", ".join(miss) if miss else "pass"))
    hues = [m["skin_hue"] for _, m in rows if "skin_hue" in m]
    if spread and len(hues) > 1:
        lines.append(f"skin hue range over these frames: {max(hues) - min(hues):.1f} deg (head turns move single frames; the drift "
                     f"target is <= 2 deg between shot medians, median here {float(np.median(hues)):.1f})")
    return "\n".join(lines)


def qa(paths, every=2.0, track=None, matte_dir=None, faces_from=None):
    """Sample a graded clip (or images) every `every` seconds and measure each frame. Returns [(label, measure)].
    Faces: YuNet on `faces_from` (e.g. the ungraded source, so every version is measured on the same box), else on the
    frame itself, else the track."""
    import json as _json
    import faces as FC
    rows = []
    tr = _json.load(open(track)) if track else None
    for p in paths:
        if p.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            rows.append((Path(p).stem, measure(frame(p, 0))))
            continue
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate:format=duration",
                              "-of", "json", p], capture_output=True, text=True, check=True).stdout
        info = _json.loads(out)
        st = info["streams"][0]
        W, H, fps, dur = int(st["width"]), int(st["height"]), eval(st["r_frame_rate"]), float(info["format"]["duration"])
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-vf", f"fps=1/{every}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        fr = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)
        ref = fr
        if faces_from:
            ref = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", faces_from, "-vf", f"fps=1/{every}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                               capture_output=True, check=True).stdout, np.uint8).reshape(-1, H, W, 3)
        for k, im in enumerate(fr):
            t = k * every
            face = FC.detect(ref[min(k, len(ref) - 1)]) or (FC.from_track(*tr[min(len(tr) - 1, int(t * fps))]) if tr else None)
            mt = None
            if matte_dir:
                mp = Path(matte_dir) / f"f{int(t * fps) + 1:05d}.png"
                mt = cv2.imread(str(mp), cv2.IMREAD_GRAYSCALE) / 255.0 if mp.exists() else None
            rows.append((f"{Path(p).stem[:14]} {t:6.1f}s", measure(im, face, mt)))
    return rows


if __name__ == "__main__":
    if sys.argv[1] == "qa":
        def _a(n, d=None):
            return next((a.split("=", 1)[1] for a in sys.argv if a.startswith(f"--{n}=")), d)
        rows = qa([a for a in sys.argv[2:] if not a.startswith("--")], float(_a("every", 2.0)), _a("track"), _a("matte"), _a("faces"))
        print(table(rows))
        if _a("json"):
            Path(_a("json")).write_text(json.dumps([{"frame": l, **{k: round(v, 4) for k, v in m.items()}} for l, m in rows], indent=1))
        sys.exit(0)
    src, t = sys.argv[1], float(sys.argv[2])
    img = frame(src, t)
    print(json.dumps(stats(img)))
    out = next((a for a in sys.argv[3:] if not a.startswith("--")), None)
    if out:
        cv2.imwrite(out, scope_image(img))
