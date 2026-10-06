"""Side-by-side check of the look: raw | relit room | cut-out on a studio backdrop (numpy stand-in for the CSS one)."""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def studio(W=1920, H=1080):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    base = np.array([10, 19, 48], np.float32) / 255
    deep = np.array([5, 9, 26], np.float32) / 255
    r = np.sqrt(((xx - W * 0.5) / (W * 0.62)) ** 2 + ((yy - H * 0.42) / (H * 0.75)) ** 2)
    img = base + (deep - base) * np.clip(r, 0, 1)[..., None] ** 1.3
    warm = np.exp(-(((xx - W * 0.73) / (W * 0.2)) ** 2 + ((yy - H * 0.3) / (H * 0.3)) ** 2))[..., None]
    cool = np.exp(-(((xx - W * 0.2) / (W * 0.22)) ** 2 + ((yy - H * 0.55) / (H * 0.45)) ** 2))[..., None]
    return np.clip(img + warm * np.array([0.30, 0.17, 0.02]) * 0.6 + cool * np.array([0.02, 0.14, 0.15]) * 0.5, 0, 1)


def main():
    raw_dir, look_dir, out = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    stems = sys.argv[4].split(",")
    bg = studio()
    rows = []
    for s in stems:
        raw = cv2.cvtColor(cv2.imread(str(raw_dir / f"{s}.jpg")), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
        rl = cv2.cvtColor(cv2.imread(str(look_dir / "relit" / f"{s}.jpg")), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
        c = np.asarray(Image.open(look_dir / f"{s}.webp")).astype(np.float32) / 255
        comp = c[..., :3] * c[..., 3:] + bg * (1 - c[..., 3:])
        rows.append(np.hstack([cv2.resize(x, (960, 540), interpolation=cv2.INTER_AREA) for x in (raw, rl, comp)]))
    Image.fromarray((np.vstack(rows) * 255).astype(np.uint8)).save(out, quality=90)


if __name__ == "__main__":
    main()
