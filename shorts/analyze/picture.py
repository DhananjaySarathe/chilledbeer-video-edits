"""What the camera shows, sampled twice a second: sharpness, brightness, face position, shot changes."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

import cv2
import numpy as np

from shorts import config
from shorts.errors import ShortsError

cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)   # OpenCV 5 warns about DNN targets it ignores

SW, SH = 360, 640                  # sample size, 1/3 of 1080x1920
SCALE = config.OUT_W / SW          # sample pixels -> output pixels


@dataclass
class Sample:
    t: float
    blur: float
    brightness: float
    face: tuple[float, float, float, float] | None
    scene: float


def sample_frames(ffmpeg: str, src: str, fps: float = 2.0):
    # Software decoding: ffmpeg's threaded HEVC decoder ran 3x faster here than VideoToolbox with copy-back.
    cmd = [ffmpeg, "-v", "error", "-i", src, "-an", "-vf", f"fps={fps},scale={SW}:{SH}:flags=bilinear",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    size, k = SW * SH * 3, 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield k / fps, np.frombuffer(buf, np.uint8).reshape(SH, SW, 3)
            k += 1
    finally:
        proc.stdout.close()
        err = proc.stderr.read().decode(errors="replace")
        proc.wait()
    if k == 0:
        raise ShortsError("E_DECODE", f"Could not decode video frames: {err.strip()[-300:]}",
                          "Check that the file plays; try re-exporting it as H.264 mp4.")


class FaceFinder:
    def __init__(self):
        self.det = cv2.FaceDetectorYN.create(str(config.FACE_MODEL), "", (SW, SH), 0.7, 0.3, 20)

    def largest(self, frame: np.ndarray) -> tuple[float, float, float, float] | None:
        _, faces = self.det.detect(frame)
        if faces is None or len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])[:4]
        return float(x) * SCALE, float(y) * SCALE, float(w) * SCALE, float(h) * SCALE


def blur_score(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def scene_score(prev_small: np.ndarray, small: np.ndarray) -> float:
    return float(np.mean(np.abs(small.astype(np.int16) - prev_small.astype(np.int16)))) / 255.0


def ranges(times: list[float], flags: list[bool], step: float, min_s: float) -> list[dict]:
    out, start = [], None
    for t, flag in zip(times + [None], flags + [False]):
        if flag and start is None:
            start = t
        if not flag and start is not None:
            end = t if t is not None else times[-1] + step
            if end - start >= min_s - 1e-9:
                out.append({"start": round(start, 2), "end": round(end, 2)})
            start = None
    return out


def picture_pass(ffmpeg: str, src: str, duration: float, n_thumbs: int = 20, fps: float = 2.0):
    finder = FaceFinder()
    samples: list[Sample] = []
    thumbs: dict[int, tuple[float, np.ndarray]] = {}
    want = [duration * (k + 0.5) / n_thumbs for k in range(n_thumbs)]
    prev = None
    for t, frame in sample_frames(ffmpeg, src, fps):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (64, 114), interpolation=cv2.INTER_AREA)
        samples.append(Sample(t=round(t, 3), blur=blur_score(gray), brightness=float(gray.mean()),
                              face=finder.largest(frame), scene=0.0 if prev is None else scene_score(prev, small)))
        prev = small
        for k, wt in enumerate(want):
            if k not in thumbs and abs(t - wt) <= 0.5 / fps + 1e-6:
                thumbs[k] = (t, frame.copy())
    return samples, [thumbs[k] for k in sorted(thumbs)]


def summarize(samples: list[Sample], fps: float = 2.0) -> dict:
    times, step = [s.t for s in samples], 1.0 / fps
    faces = [s.face for s in samples if s.face]
    med = [float(np.median([f[k] for f in faces])) for k in range(4)] if faces else None
    blur_med = float(np.median([s.blur for s in samples])) if samples else 0.0
    return {
        "fps": fps,
        "face_presence": round(len(faces) / max(len(samples), 1), 3),
        "face_box": {"x": med[0], "y": med[1], "w": med[2], "h": med[3]} if med else None,
        "face_track": [[round(v, 1) for v in s.face] if s.face else None for s in samples],
        "blurry": ranges(times, [s.blur < 0.35 * blur_med for s in samples], step, 1.0),
        "dark": ranges(times, [s.brightness < 40 for s in samples], step, 1.0),
        "no_face": ranges(times, [s.face is None for s in samples], step, 1.0),
        "scene_changes": [s.t for s in samples if s.scene > 0.25],
    }
