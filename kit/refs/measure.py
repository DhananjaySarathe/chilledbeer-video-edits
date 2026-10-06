"""Measure a video's look with the same metrics used on the reference channels (storyboard analyzer):
black/mid/white points, saturation, colourfulness, centre-vs-edge brightness, shadow/highlight warmth, skin tone.

    python3 kit/refs/measure.py video.mp4 [step_seconds]
"""
import subprocess
import sys

import numpy as np

W, H = 320, 180


def frames(path, step):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps=1/{step},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(np.float32)


def stats(f):
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    Y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    mx, mn = f.max(-1), f.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0).mean()
    a, c = r - g, 0.5 * (r + g) - b
    colorful = np.sqrt(a.var() + c.var()) + 0.3 * np.hypot(a.mean(), c.mean())
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    sk = (cb > 77) & (cb < 127) & (cr > 137) & (cr < 173) & (Y > 40) & (Y < 235)
    yy, xx = np.mgrid[0:H, 0:W]
    rr = ((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2
    q25, q75 = np.quantile(Y, [0.25, 0.75])
    sh, hi = Y < q25, Y > q75
    return dict(p1=np.quantile(Y, .01), p50=np.quantile(Y, .5), p99=np.quantile(Y, .99), sat=sat, colorful=colorful,
                cme=Y[rr < 0.16].mean() - Y[rr > 0.8].mean(), skin=sk.mean(),
                shadowRB=(r[sh] - b[sh]).mean(), highRB=(r[hi] - b[hi]).mean(),
                skinHue=np.degrees(np.arctan2(cr[sk] - 128, cb[sk] - 128)).mean() if sk.any() else np.nan,
                skinC=np.hypot(cr[sk] - 128, cb[sk] - 128).mean() if sk.any() else np.nan, skinL=Y[sk].mean() if sk.any() else np.nan)


def main():
    path, step = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 5
    S = [stats(f) for f in frames(path, step)]
    face = [s for s in S if s["skin"] > 0.08 and s["skinC"] > 12]
    med = lambda L, k: np.nanmedian([s[k] for s in L]) if L else float("nan")
    print(f"{path.split('/')[-1]}: {len(S)} frames, face share {len(face) / len(S):.2f}")
    print("  all : " + " ".join(f"{k} {med(S, k):.1f}" for k in ["p1", "p50", "p99", "sat", "colorful", "cme"]))
    print("  face: " + " ".join(f"{k} {med(face, k):.1f}" for k in ["shadowRB", "highRB", "skinHue", "skinC", "skinL", "cme", "p1", "p99"]))


if __name__ == "__main__":
    main()
