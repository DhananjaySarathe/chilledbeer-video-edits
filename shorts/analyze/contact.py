"""Contact sheets: many timecoded frames in one image, so Claude can see a whole video in one look."""
from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np


def fmt_tc(t: float) -> str:
    m = int(t // 60)
    return f"{m}:{t - 60 * m:04.1f}"


def contact_sheet(frames: list[tuple[float, np.ndarray]], cols: int = 5, thumb: tuple[int, int] = (216, 384)) -> np.ndarray:
    tw, th = thumb
    rows = max(1, -(-len(frames) // cols))
    sheet = np.full((rows * th, cols * tw, 3), 24, np.uint8)
    for k, (t, frame) in enumerate(frames):
        r, c = divmod(k, cols)
        img = cv2.resize(frame, (tw, th), interpolation=cv2.INTER_AREA)
        label = fmt_tc(t)
        cv2.rectangle(img, (0, 0), (10 + 11 * len(label), 26), (0, 0, 0), -1)
        cv2.putText(img, label, (5, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        sheet[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = img
    return sheet


def save_png(img: np.ndarray, path: Path) -> None:
    cv2.imwrite(str(path), img)


def grab_frames(ffmpeg: str, path: str, duration: float, n: int, size: tuple[int, int]) -> list[tuple[float, np.ndarray]]:
    """n frames from the middle of n equal slices of a video, as BGR arrays of size (w, h)."""
    w, h = size

    def one(k: int):
        t = duration * (k + 0.5) / n
        proc = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                               "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"],
                              capture_output=True)
        buf = proc.stdout[: w * h * 3]
        return (t, np.frombuffer(buf, np.uint8).reshape(h, w, 3)) if len(buf) == w * h * 3 else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        return [r for r in pool.map(one, range(n)) if r is not None]
