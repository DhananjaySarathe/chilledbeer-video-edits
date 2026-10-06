"""Scribble outline around the speaker (the rotoscope look), built offline for kit/hf/scribble.js.

For every 12 fps step of a clip: person matte (kit/bin/personseg) -> temporal + spatial smoothing -> largest blob ->
expand 10-16 px -> cv2.findContours -> drop the runs along the frame border (the outline stays open where the body
leaves the frame) -> resample + smooth -> a seeded jitter per step (the line boils on twos) -> JSON, one path per step
and pass, in the source video's pixels.

    python3 kit/hf/tools/scribble.py clip.mp4 outline.json [--start=0] [--dur=4] [--fps=12] [--expand=14] [--seed=7]
            [--passes=2] [--amp=5] [--open=0] [--scale=0.5] [--work=DIR] [--preview=sheet.jpg]

  --expand  how far the line sits outside the person (source px; 10-16 reads as a drawn outline, not a matte edge)
  --amp     jitter amplitude (source px) of the boil; the second pass gets 1.5x and its own seed
  --open    remove protrusions thinner than this (source px): fingers and hair wisps; 0 keeps the hands
  --temporal union (default: the outline covers where the person is during the whole step, so fast head turns never
            put the line on the face) or mean (tighter, can cut in on fast moves)
  --scale   matte resolution (0.5 of 1920x1080 is plenty; personseg is fast)
  --preview a contact sheet of every 4th step with the outline drawn on the frame: LOOK AT IT (hair/hand blobs)

Output: {"kind": "hf-scribble", "fps": 12, "width": W, "height": H, "start", "dur", "passes", "closed",
         "steps": [[pass0_runs, pass1_runs], ...], "boxes": [[x, y, w, h], ...]}   (runs: flat int [x0, y0, x1, y1, ...])
Step k covers clip time [k/fps, (k+1)/fps) and is matted from the frame in the middle of that interval.
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PERSONSEG = ROOT / "kit/bin/personseg"


def probe(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", str(video)],
                         capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    return j["streams"][0]["width"], j["streams"][0]["height"], float(j["format"]["duration"])


def extract(video, work, start, dur, fps, scale):
    key = f"{video.stem}_{start:.3f}_{dur:.3f}_{fps}_{scale}"                # one folder per request: reruns overwrite, nothing is deleted
    fdir, mdir = work / f"frames_{key}", work / f"mattes_{key}"
    for d in (fdir, mdir):
        d.mkdir(parents=True, exist_ok=True)
    ss = start + 0.5 / fps                                       # the middle of each step
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ss:.4f}", "-i", str(video), "-t", f"{dur:.4f}", "-vf", f"fps={fps},scale=iw*{scale}:ih*{scale}",
                    "-q:v", "2", str(fdir / "f%05d.jpg")], check=True)
    subprocess.run([str(PERSONSEG), str(fdir), str(mdir), "--mask"], check=True, capture_output=True)
    files = sorted(mdir.glob("*.png"))
    if not files:
        raise SystemExit("personseg produced no mattes")
    return np.stack([cv2.imread(str(f), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255 for f in files]), sorted(fdir.glob("*.jpg"))


def clean(M, k, expand, open_px, sigma, temporal="union"):
    """Matte k over time (union of the neighbouring steps, so the line never cuts into a moving head during the step;
    or "mean": 1-2-1) and space, the largest blob, holes filled, expanded by `expand` px."""
    n = len(M)
    a, b = M[max(0, k - 1)], M[min(n - 1, k + 1)]
    m = np.maximum(np.maximum(a, b) * 0.9, M[k]) if temporal == "union" else 0.25 * a + 0.5 * M[k] + 0.25 * b
    m = cv2.GaussianBlur(m, (0, 0), sigma)
    b = (m > 0.5).astype(np.uint8)
    if open_px > 0:
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(open_px) | 1, int(open_px) | 1))
        b = cv2.morphologyEx(b, cv2.MORPH_OPEN, ker)
    cnt, lab, st, _ = cv2.connectedComponentsWithStats(b, 8)
    if cnt <= 1:
        return None
    b = (lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    inv = 1 - b                                                   # fill holes: background reachable from the border
    ff = inv.copy(); h, w = b.shape
    cv2.floodFill(ff, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 2)
    b[ff == 1] = 1
    dist = cv2.distanceTransform(1 - b, cv2.DIST_L2, 5)          # a round expansion
    e = (dist <= expand).astype(np.uint8)
    e = cv2.GaussianBlur(e.astype(np.float32), (0, 0), max(1.0, expand * 0.35))   # soften corners left by hands/hair
    return (e > 0.5).astype(np.uint8)


def runs(mask, edge):
    """The outline as point runs: the contour minus the stretches along the frame border."""
    cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return [], False
    c = max(cs, key=cv2.contourArea)[:, 0, :].astype(np.float64)
    h, w = mask.shape
    on = (c[:, 0] <= edge) | (c[:, 0] >= w - 1 - edge) | (c[:, 1] <= edge) | (c[:, 1] >= h - 1 - edge)
    if not on.any():
        return [c], True
    k0 = int(np.argmax(on))                                       # start on a border point so runs don't wrap
    c, on = np.roll(c, -k0, 0), np.roll(on, -k0)
    out, cur = [], []
    for p, b in zip(c, on):
        if b:
            if len(cur) > 1:
                out.append(np.array(cur))
            cur = []
        else:
            cur.append(p)
    if len(cur) > 1:
        out.append(np.array(cur))
    total = sum(len(r) for r in out) or 1
    return [r for r in out if len(r) > 0.12 * total], False


def resample(p, step, closed):
    q = np.vstack([p, p[:1]]) if closed else p
    seg = np.hypot(*np.diff(q, axis=0).T)
    s = np.concatenate([[0], np.cumsum(seg)])
    L = s[-1]
    n = max(4, int(L / step))
    t = np.linspace(0, L, n, endpoint=not closed)
    return np.stack([np.interp(t, s, q[:, 0]), np.interp(t, s, q[:, 1])], 1), L


def smooth1d(p, sigma, closed):
    r = int(3 * sigma) + 1
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2); k /= k.sum()
    pad = np.vstack([p[-r:], p, p[:r]]) if closed else np.vstack([np.repeat(p[:1], r, 0), p, np.repeat(p[-1:], r, 0)])
    return np.stack([np.convolve(pad[:, i], k, mode="valid") for i in range(2)], 1)


def jitter(p, rng, amp, closed):
    """Offset along the normals by low-frequency noise (a few sines over the arc length) plus a little grain."""
    d = np.gradient(p, axis=0)
    nrm = np.stack([-d[:, 1], d[:, 0]], 1); nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-9
    s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(p, axis=0).T))])
    off = np.zeros(len(p))
    for _ in range(3):
        wl = rng.uniform(160, 420)
        off += rng.uniform(0.4, 1.0) * np.sin(2 * np.pi * s / wl + rng.uniform(0, 2 * np.pi))
    off = off / 1.8 * amp + smooth1d(np.stack([rng.normal(0, amp * 0.5, len(p)), np.zeros(len(p))], 1), 1.5, closed)[:, 0]
    return p + nrm * off[:, None]


def overshoot(p, frac, rng):
    """Hand-drawn ends: run a little past the start/end along the tangent."""
    a, b = p[1] - p[0], p[-1] - p[-2]
    a /= np.linalg.norm(a) + 1e-9; b /= np.linalg.norm(b) + 1e-9
    e0, e1 = rng.uniform(0.5, 1) * frac, rng.uniform(0.5, 1) * frac
    return np.vstack([p[:1] - a * e0, p, p[-1:] + b * e1])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("video"); ap.add_argument("out")
    ap.add_argument("--start", type=float, default=0.0); ap.add_argument("--dur", type=float, default=None)
    ap.add_argument("--fps", type=int, default=12); ap.add_argument("--expand", type=float, default=14)
    ap.add_argument("--seed", type=int, default=7); ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--amp", type=float, default=5.0); ap.add_argument("--open", type=float, default=0)
    ap.add_argument("--scale", type=float, default=0.5); ap.add_argument("--spacing", type=float, default=18)
    ap.add_argument("--work", default=None); ap.add_argument("--preview", default=None)
    ap.add_argument("--temporal", choices=["union", "mean"], default="union")
    a = ap.parse_args()
    video = Path(a.video).resolve()
    W, H, D = probe(video)
    dur = a.dur if a.dur is not None else D - a.start
    work = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="scribble_"))
    work.mkdir(parents=True, exist_ok=True)
    M, frames = extract(video, work, a.start, dur, a.fps, a.scale)
    inv = 1 / a.scale                                             # matte px -> source px
    steps, boxes, closed_any = [], [], False
    for k in range(len(M)):
        mask = clean(M, k, a.expand * a.scale, a.open * a.scale, sigma=max(1.0, 3 * a.scale * 2), temporal=a.temporal)
        rs, closed = ([], False) if mask is None else runs(mask, edge=2)
        closed_any |= closed
        passes = []
        for ps in range(a.passes):
            rng = np.random.default_rng(a.seed * 100003 + k * 7919 + ps * 104729)
            out = []
            for r in rs:
                p, L = resample(r * inv, a.spacing * 0.5, closed)
                p = smooth1d(p, 4.0, closed)
                p = jitter(p, rng, a.amp * (1.5 if ps else 1.0), closed) + (rng.normal(0, 1.5, 2) if ps else 0)
                if not closed:
                    p = overshoot(p, 26 if ps else 14, rng)
                p, _ = resample(p, a.spacing, closed)
                out.append([int(round(v)) for v in p.reshape(-1)])
            passes.append(out)
        steps.append(passes)
        allp = np.array([v for r in passes[0] for v in r]).reshape(-1, 2) if passes and passes[0] else np.zeros((1, 2))
        x0, y0 = allp.min(0); x1, y1 = allp.max(0)
        boxes.append([int(x0), int(y0), int(x1 - x0), int(y1 - y0)])
    data = {"kind": "hf-scribble", "version": 1, "src": str(video.name), "start": a.start, "dur": round(dur, 4), "fps": a.fps, "width": W, "height": H,
            "expand": a.expand, "seed": a.seed, "amp": a.amp, "passes": a.passes, "closed": closed_any, "steps": steps, "boxes": boxes}
    Path(a.out).write_text(json.dumps(data, separators=(",", ":")))
    print(f"{a.out}: {len(steps)} steps at {a.fps} fps, {a.passes} passes, {W}x{H}, {Path(a.out).stat().st_size // 1024} KB")
    if a.preview:
        tiles = []
        for k in range(0, len(steps), 4):
            im = cv2.resize(cv2.imread(str(frames[k])), (W // 4, H // 4))
            for ps, col in ((1, (120, 190, 255)), (0, (43, 86, 226))):
                for r in steps[k][ps] if ps < len(steps[k]) else []:
                    pts = (np.array(r).reshape(-1, 2) / 4).astype(np.int32)
                    cv2.polylines(im, [pts], data["closed"], col, 2, cv2.LINE_AA)
            cv2.putText(im, f"{k}", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            tiles.append(im)
        while len(tiles) % 4:
            tiles.append(np.zeros_like(tiles[0]))
        rows = [np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
        cv2.imwrite(a.preview, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])
        print("preview:", a.preview)


if __name__ == "__main__":
    main()
