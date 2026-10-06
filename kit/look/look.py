"""The footage look: grade the speaker and lift them off the room.

Measured against 11 top channels (kit/refs/REFERENCE.md): their subject is the brightest thing in frame (centre minus
edge +5..+46 luma), blacks sit at 7-23, whites at 220-245, highlights are warm (R-B about +25) and skin stays on the
skin line (hue 107-142 deg, chroma 21-26). Phone footage in a white room is the opposite: the wall is brightest (-24..-44),
blacks are milky (20-30), whites clip near 218 and highlights are neutral.

For each frame:
  1. the Vision person mask is smoothed over time (flicker) and tightened;
  2. a clean plate of the empty room (median of uncovered pixels over the clip) adds back what Vision misses
     (fast, motion-blurred hands) and is removed from the edge pixels (no white halo on dark backdrops);
  3. the person is graded: per-clip black/white points, a gentle S-curve on luma only, warm highlights / slightly cool
     shadows, saturation up except on skin;
  4. written as an RGBA WebP cut-out (the composition puts it on a designed backdrop), and optionally as a "relit" JPEG
     where the real room is kept but pulled down ~1.3 stops with a warm practical glow.

    python3 kit/look/look.py <frames_dir> <mask_dir> <out_dir> [--relit] [--only=f00800,f00801] [--workers=8]
"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

# grade targets (0..1 sRGB): the person's black point, and where their skin sits (references: skin luma 0.31-0.49)
BLACK, SKIN = 0.035, 0.45
S_CURVE = 0.22            # 0 = linear; strength of the luma S-curve
WARM_HI, COOL_SH = 0.022, 0.014
SAT, SKIN_SAT = 1.16, 1.03


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def luma(img):
    return img[..., 0] * 0.2126 + img[..., 1] * 0.7152 + img[..., 2] * 0.0722


def load_rgb(p):
    return cv2.cvtColor(cv2.imread(str(p), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB).astype(np.float32) / 255


def load_mask(p):
    return cv2.imread(str(p), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255


def skin_weight(img):
    r, g, b = img[..., 0] * 255, img[..., 1] * 255, img[..., 2] * 255
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    return np.exp(-(((cb - 108) / 14) ** 2 + ((cr - 152) / 12) ** 2))


def clip_levels(frames_dir, mask_dir, names, n=24):
    """The person's black point and median skin luma across the clip (robust, over sampled frames)."""
    lo, sk = [], []
    for name in names[:: max(1, len(names) // n)]:
        img, m = load_rgb(frames_dir / name), load_mask(mask_dir / (Path(name).stem + ".png"))
        y = luma(img)
        yp = y[m > 0.9]
        ys = y[(m > 0.9) & (skin_weight(img) > 0.5)]
        if yp.size > 1000:
            lo.append(np.quantile(yp, 0.005))
        if ys.size > 500:
            sk.append(np.median(ys))
    return float(np.median(lo)), float(np.median(sk))


def refine_mask(masks):
    """Temporal smoothing over (prev, cur, next), then a tighter, lightly feathered edge."""
    m = 0.25 * masks[0] + 0.5 * masks[1] + 0.25 * masks[2]
    m = smoothstep(0.22, 0.95, m)
    m = cv2.erode(m, np.ones((3, 3), np.uint8))           # choke ~1 px: Vision's edge sits a little outside the hair
    # drop small islands (bits of furniture Vision sometimes grabs): keep components of at least 0.4 % of the frame
    n, lab, st, _ = cv2.connectedComponentsWithStats((m > 0.5).astype(np.uint8), connectivity=8)
    if n > 2:
        small = [k for k in range(1, n) if st[k, cv2.CC_STAT_AREA] < 0.004 * m.size]
        if small:
            drop = cv2.dilate(np.isin(lab, small).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
            m = np.where(drop, 0, m)
    return cv2.GaussianBlur(m, (0, 0), 0.9)


def clean_plate(frames_dir, mask_dir, names, n=36):
    """The empty room: per-pixel median over sampled frames of every pixel the person is clearly not covering.
    Returns (plate, known) at full size; `known` is False where the person covered the pixel in every sample."""
    stack = []
    for name in names[:: max(1, len(names) // n)]:
        img = cv2.imread(str(frames_dir / name), cv2.IMREAD_COLOR).astype(np.float32)
        m = cv2.dilate(cv2.imread(str(mask_dir / (Path(name).stem + ".png")), cv2.IMREAD_GRAYSCALE), np.ones((41, 41), np.uint8))
        img[m > 8] = np.nan
        stack.append(img)
    st = np.stack(stack)
    count = np.sum(~np.isnan(st[..., 0]), axis=0)
    with np.errstate(all="ignore"):
        import warnings
        warnings.simplefilter("ignore", RuntimeWarning)
        plate = np.nanmedian(st, axis=0)
    known = count >= max(6, len(stack) // 3)                 # seen empty often enough to trust
    plate = np.nan_to_num(plate, nan=0.0)
    return cv2.cvtColor(plate.astype(np.float32), cv2.COLOR_BGR2RGB) / 255, known


def room_diff(img, a, plate, known):
    """How far each pixel is from the empty room (0..255), after matching the phone's exposure drift; wall shadows
    (the room darkened evenly, same colour ratios) count as room."""
    bg = (a < 0.02) & known
    g = np.median(img[bg], axis=0) / np.maximum(np.median(plate[bg], axis=0), 1e-3) if bg.sum() > 5000 else 1.0
    p = plate * g
    d = np.abs(img - p).max(-1) * 255
    r = img / np.maximum(p, 1e-3)
    shadow = (r.max(-1) < 0.98) & (r.min(-1) > 0.3) & (r.max(-1) - r.min(-1) < 0.1)
    return np.where(shadow | ~known, 0, d), shadow


def solidify_blur(a, d, raw, img):
    """A fast hand swinging past the body is motion-blurred and Vision makes it half transparent. Inside Vision's own
    uncertain zone, skin-toned pixels that are clearly not the empty room become solid (the blur stays in the pixels);
    skin only, so furniture next to the arm never comes back."""
    zone = cv2.dilate((raw > 0.04).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool) & (raw < 0.97)
    r, g, b = img[..., 0] * 255, img[..., 1] * 255, img[..., 2] * 255
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    skinish = np.exp(-(((cb - 110) / 18) ** 2 + ((cr - 148) / 16) ** 2)) * smoothstep(5, 12, np.hypot(cb - 128, cr - 128))
    k = smoothstep(22, 60, d) * zone * smoothstep(0.25, 0.6, skinish)
    k = cv2.morphologyEx(k.astype(np.float32), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return np.maximum(a, cv2.GaussianBlur(k, (0, 0), 1.0))


def fill_holes(img, a, plate, known):
    """What Vision misses: a fast, motion-blurred hand leaves a hole in the mask. A gap enclosed by the person (the
    frame's bottom edge counts as the person, the body continues below it) is filled unless it is visibly the empty
    room: a trusted plate pixel that still matches the room. Shadows are the room darkened evenly, so they match too."""
    H, W = a.shape
    out = np.zeros((H + 1, W + 2), np.uint8)
    out[1:, 1:-1] = a < 0.5
    out[0, :] = 1; out[:, 0] = 1; out[:, -1] = 1                            # open border: top, left, right
    n, lab = cv2.connectedComponents(out, connectivity=4)
    outside = lab[0, 0]
    holes = (lab[1:, 1:-1] != outside) & (lab[1:, 1:-1] > 0)
    if not holes.any():
        return a
    d, shadow = room_diff(img, a, plate, known)
    room = known & ((d < 26) | shadow)
    fill = (holes & ~room).astype(np.float32)
    fill = cv2.morphologyEx(fill, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    return np.maximum(a, cv2.GaussianBlur(fill, (0, 0), 1.5))


def wall_plate(img, a):
    """The room colour behind the person: a normalised blur of the visible background, at 1/8 size."""
    s = cv2.resize(img, (240, 135), interpolation=cv2.INTER_AREA)
    w = cv2.resize((1 - a) ** 2, (240, 135), interpolation=cv2.INTER_AREA)
    num = cv2.GaussianBlur(s * w[..., None], (0, 0), 9)
    den = cv2.GaussianBlur(w, (0, 0), 9)[..., None] + 1e-4
    return cv2.resize(num / den, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)


def decontaminate(img, a, plate):
    """Remove the wall that is mixed into semi-transparent edge pixels: F = (I - (1 - a) B) / a."""
    aa = np.maximum(a, 0.22)[..., None]
    f = np.clip((img - (1 - a)[..., None] * plate) / aa, 0, 1)
    w = smoothstep(0.02, 0.3, a)[..., None] * (1 - smoothstep(0.96, 0.995, a))[..., None]
    return img * (1 - w) + f * w


def grade(img, lo, sk):
    y = luma(img)
    # levels on luma: the clip's black point to BLACK and its skin to SKIN, with a soft toe below the black point
    yl = BLACK + (y - lo) * (SKIN - BLACK) / max(sk - lo, 1e-3)
    toe = BLACK * np.clip(y / max(lo, 1e-3), 0, 1) ** 1.6
    yl = np.where(y < lo, toe, yl)
    # gentle S-curve (fixed at 0, 0.5, 1) and a soft shoulder so whites roll off instead of clipping
    ys = yl - S_CURVE * np.sin(2 * np.pi * yl) / (2 * np.pi)
    ys = np.where(ys > 0.85, 0.85 + (1 - np.exp(-(ys - 0.85) / 0.15)) * 0.15, ys)
    out = img * (np.clip(ys, 0, 1) / np.maximum(y, 1e-4))[..., None]
    # split tone: warm highlights, a touch of teal in the shadows
    h = smoothstep(0.55, 1.0, ys)[..., None]
    s = (1 - smoothstep(0.0, 0.3, ys))[..., None]
    out = out + h * np.array([WARM_HI, WARM_HI * 0.35, -WARM_HI], np.float32) + s * np.array([-COOL_SH * 0.8, COOL_SH * 0.2, COOL_SH], np.float32)
    # saturation: more colour everywhere except skin, which is already on the skin line
    skin = skin_weight(out)[..., None]
    k = SAT + (SKIN_SAT - SAT) * skin
    yy = luma(out)[..., None]
    out = yy + (out - yy) * k
    return np.clip(out, 0, 1)


def face_light(g, a, strength=1.0):
    """Studio lighting on the cut-out, placed from the person mask: a soft warm key on one side of the face, a gentle
    falloff on the other side (negative fill, for shape), and a cool rim along the head and shoulders that lifts a dark
    shirt off a dark backdrop. Off by default; `--light=0.6` etc. sets the strength."""
    if strength <= 0:
        return g
    H, W = a.shape
    rows = np.where((a > 0.5).sum(1) > 8)[0]
    if not len(rows):
        return g
    y0 = rows[0]
    probe = min(H - 1, y0 + int(0.12 * H))
    xs = np.where(a[probe] > 0.5)[0]
    if len(xs) < 10:
        return g
    cx, hw = (xs[0] + xs[-1]) / 2, max(60.0, (xs[-1] - xs[0]) * 1.0)
    cy = y0 + 0.75 * hw
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    key = np.exp(-(((xx - (cx - 0.38 * hw)) / (0.62 * hw)) ** 2 + ((yy - (cy - 0.1 * hw)) / (0.85 * hw)) ** 2))
    face = np.exp(-(((xx - cx) / (1.1 * hw)) ** 2 + ((yy - cy) / (1.2 * hw)) ** 2))
    fill = smoothstep(cx - 0.15 * hw, cx + 0.75 * hw, xx) * face
    gain = 1 + strength * (0.20 * key - 0.11 * fill)
    out = g * gain[..., None] + (strength * 0.018 * key)[..., None] * np.array([1.0, 0.45, -0.6], np.float32)
    inner = cv2.erode(a, np.ones((13, 13), np.uint8))
    band = cv2.GaussianBlur(np.clip(a - inner, 0, 1), (0, 0), 3.5) * a
    upper = 1 - smoothstep(cy + 0.4 * hw, cy + 2.2 * hw, yy)                # head and shoulders, not the whole body
    side = 0.55 + 0.45 * smoothstep(cx - 0.6 * hw, cx + 0.8 * hw, xx)        # stronger on the side away from the key
    rim = band * upper * side * strength
    out = out + rim[..., None] * np.array([0.16, 0.22, 0.30], np.float32)
    return np.clip(g + (out - g) * a[..., None], 0, 1)


def relight(img, graded, a, plate_bright):
    """Keep the real room but pull it down ~1.3 stops, with a warm practical glow high on one side and a vignette."""
    H, W = a.shape
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    room = grade(img, *plate_bright) * 0.40
    glow = np.exp(-(((xx - W * 0.78) / (W * 0.30)) ** 2 + ((yy - H * 0.28) / (H * 0.42)) ** 2))[..., None]
    room = room * (1 + 0.55 * glow) + glow * np.array([0.10, 0.055, 0.0], np.float32)
    vig = 1 - 0.35 * smoothstep(0.35, 1.25, np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2))
    room *= vig[..., None]
    return np.clip(graded * a[..., None] + room * (1 - a[..., None]), 0, 1)


_PLATE = {}


def work(job):
    frames_dir, mask_dir, out_dir, names, i, lo, hi, relit, light = job
    name = names[i]
    stem = Path(name).stem
    if "p" not in _PLATE:
        z = np.load(out_dir / "plate.npz")
        _PLATE["p"], _PLATE["k"] = z["plate"], z["known"]
    plate, known = _PLATE["p"], _PLATE["k"]
    ms = [load_mask(mask_dir / (Path(names[j]).stem + ".png")) for j in (max(0, i - 1), i, min(len(names) - 1, i + 1))]
    img = load_rgb(frames_dir / name)
    a = refine_mask(ms)
    a = solidify_blur(a, room_diff(img, a, plate, known)[0], ms[1], img)
    a = fill_holes(img, a, plate, known)
    b = np.where(known[..., None], plate, wall_plate(img, a))
    f = decontaminate(img, a, b)
    g = face_light(grade(f, lo, hi), a, light)
    rgba = np.dstack([g, a])
    from PIL import Image                     # only the cut-out writer needs PIL (grade.py / scopes.py run without it)
    Image.fromarray((rgba * 255 + 0.5).astype(np.uint8), "RGBA").save(out_dir / f"{stem}.webp", "WEBP", quality=90, alpha_quality=92, method=4)
    if relit:
        (out_dir / "relit").mkdir(exist_ok=True)
        rl = relight(img, g, a, (lo, hi))
        cv2.imwrite(str(out_dir / "relit" / f"{stem}.jpg"), cv2.cvtColor((rl * 255 + 0.5).astype(np.uint8), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 93])
    return stem


def main():
    frames_dir, mask_dir, out_dir = (Path(x) for x in sys.argv[1:4])
    relit = "--relit" in sys.argv
    only = next((set(a.split("=")[1].split(",")) for a in sys.argv if a.startswith("--only=")), None)
    workers = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--workers=")), 8))
    light = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--light=")), 0))
    out_dir.mkdir(parents=True, exist_ok=True)
    names = sorted(p.name for p in frames_dir.glob("*.jpg"))
    lo, hi = clip_levels(frames_dir, mask_dir, names)
    plate, known = clean_plate(frames_dir, mask_dir, names)
    np.savez(out_dir / "plate.npz", plate=plate.astype(np.float32), known=known)
    (out_dir / "levels.json").write_text(json.dumps({"black_in": round(lo, 4), "skin_in": round(hi, 4), "black_out": BLACK, "skin_out": SKIN}))
    idx = [i for i, n in enumerate(names) if only is None or Path(n).stem in only]
    with Pool(workers) as pool:
        for k, _ in enumerate(pool.imap_unordered(work, [(frames_dir, mask_dir, out_dir, names, i, lo, hi, relit, light) for i in idx], chunksize=4)):
            if k and k % 300 == 0:
                print(f"  {k}/{len(idx)}", flush=True)
    print(f"{frames_dir.name}: {len(idx)} frames, black {lo:.3f} -> {BLACK}, skin {hi:.3f} -> {SKIN}")


if __name__ == "__main__":
    main()
