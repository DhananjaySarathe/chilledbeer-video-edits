"""Faces for the grade and the scopes: OpenCV's YuNet detector (kit/models/face_detection_yunet_2023mar.onnx).

A face is a dict {box: (x, y, w, h), lm: [(x, y) right eye, left eye, nose tip, right mouth corner, left mouth corner],
score} in full-frame pixels. `skin_region` turns it into the pixels a colourist would read skin from: the upper cheeks
and the strip of forehead above the brows (no eyes, no beard, no hair, no specular highlights).

A face track is the same [cx, cy, head_w] per frame that grade.py has always used (films/expensewaale/face_track.py's
YuNet convention: the box centre and box width / 1.078), so old and new tracks are interchangeable.

    python3 kit/look/faces.py <clip> <out.face.json>        # a YuNet track for a whole clip (half-size detection, smoothed)
"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

MODEL = Path(__file__).resolve().parents[1] / "models/face_detection_yunet_2023mar.onnx"
WK = 1.078                      # YuNet box width / head width (films/expensewaale/face_track.py, measured)
BOX_H = 1.29                    # YuNet box height / box width (measured on 8 eval frames, both rooms: 1.22-1.38)

_DET = {}


def detect(img: np.ndarray, scale: float = 0.5) -> dict | None:
    """The largest face in an RGB frame (uint8 or float 0..1), or None."""
    H, W = img.shape[:2]
    w, h = int(W * scale), int(H * scale)
    if (w, h) not in _DET:
        _DET[(w, h)] = cv2.FaceDetectorYN.create(str(MODEL), "", (w, h), 0.6)
    u8 = img if img.dtype == np.uint8 else (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
    small = cv2.resize(cv2.cvtColor(u8, cv2.COLOR_RGB2BGR), (w, h), interpolation=cv2.INTER_AREA)
    _, f = _DET[(w, h)].detect(small)
    if f is None or not len(f):
        return None
    f = max(f, key=lambda r: r[2] * r[3]) / scale
    return {"box": tuple(float(v) for v in f[:4]), "lm": [(float(f[4 + 2 * i]), float(f[5 + 2 * i])) for i in range(5)],
            "score": float(f[-1] * scale)}


def from_track(cx: float, cy: float, hw: float) -> dict:
    """A face (box + landmarks placed by average proportions) from a track entry [cx, cy, head_w]."""
    w = hw * WK
    h = w * BOX_H
    x, y = cx - w / 2, cy - h / 2
    lm = [(x + 0.30 * w, y + 0.40 * h), (x + 0.70 * w, y + 0.40 * h), (x + 0.50 * w, y + 0.60 * h),
          (x + 0.34 * w, y + 0.78 * h), (x + 0.66 * w, y + 0.78 * h)]
    return {"box": (x, y, w, h), "lm": lm, "score": 0.0}


def to_track(face: dict) -> list:
    x, y, w, h = face["box"]
    return [x + w / 2, y + h / 2, w / WK]


def skin_region(shape, face: dict) -> np.ndarray:
    """Boolean HxW: upper cheeks (under the eyes, beside the nose, above the beard) and the forehead strip above the
    brows. Uses the landmarks, so it follows a turned head."""
    H, W = shape[:2]
    x, y, w, h = face["box"]
    (rex, rey), (lex, ley), (nx, ny), (rmx, rmy), (lmx, lmy) = face["lm"]
    eye_d = max(8.0, np.hypot(lex - rex, ley - rey))
    m = np.zeros((H, W), np.uint8)
    for ex, ey, out in ((rex, rey, -1), (lex, ley, 1)):
        # an upper-cheek ellipse: below the eye, a little outward, ending above the moustache/beard line
        cy = ey + 0.42 * (ny - ey) + 0.10 * eye_d
        cx = ex + out * 0.08 * eye_d
        cv2.ellipse(m, (int(cx), int(cy)), (max(2, int(0.22 * eye_d)), max(2, int(0.16 * eye_d))), 0, 0, 360, 1, -1)
    # forehead strip: between the eyes, ~0.55-0.8 eye distances above them (fringes are dropped by the luma filter)
    fy = (rey + ley) / 2 - 0.62 * eye_d
    cv2.ellipse(m, (int((rex + lex) / 2), int(fy)), (max(2, int(0.35 * eye_d)), max(2, int(0.10 * eye_d))), 0, 0, 360, 1, -1)
    return m.astype(bool)


def skin_pixels(img: np.ndarray, face: dict) -> np.ndarray:
    """Skin pixels of the face as an (N, 3) float array (display RGB 0..1): the skin region minus hair/beard (dark and
    low chroma), eyebrows and the top 2 % (speculars)."""
    reg = skin_region(img.shape, face)
    px = img[reg].astype(np.float32)
    if img.dtype == np.uint8:
        px = px / 255
    if len(px) < 50:
        return px
    y = px @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    cb, cr = (px[:, 2] - y) / 1.8556, (px[:, 0] - y) / 1.5748
    med = np.median(y)
    keep = (y > 0.55 * med) & (y < np.percentile(y, 98)) & (np.hypot(cb, cr) > 0.02) & (cr > 0)   # hair/beard: dark, grey
    return px[keep] if keep.sum() > 30 else px


def track_clip(src: str, step: int = 1, scale: float = 0.5) -> list:
    """YuNet on every `step`-th frame of a clip at `scale`, gaps filled, median + slow EMA smoothed: [[cx, cy, hw], ...]."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", src],
                         capture_output=True, text=True, check=True).stdout.strip().split(",")
    W, H = int(out[0]), int(out[1])
    w, h = int(W * scale) // 2 * 2, int(H * scale) // 2 * 2
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    raw, i = [], 0
    while True:
        buf = dec.stdout.read(w * h * 3)
        if len(buf) < w * h * 3:
            break
        if i % step == 0:
            f = detect(np.frombuffer(buf, np.uint8).reshape(h, w, 3), 1.0)
            raw.append([v / scale for v in to_track(f)] if f else None)
        else:
            raw.append(None)
        i += 1
    dec.wait()
    first = next((r for r in raw if r), [W / 2, H * 0.4, W * 0.12])
    last, filled = first, []
    for r in raw:
        last = r or last
        filled.append(last)
    arr = np.array(filled, np.float64)
    k = 5
    pad = np.pad(arr, ((k, k), (0, 0)), mode="edge")
    med = np.array([np.median(pad[j:j + 2 * k + 1], 0) for j in range(len(arr))])
    res, s = [], med[0]
    for m in med:
        s = s + 0.18 * (m - s)
        res.append([round(float(v), 1) for v in s])
    return res


if __name__ == "__main__":
    tr = track_clip(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(tr))
    print(f"{sys.argv[2]}: {len(tr)} frames")
