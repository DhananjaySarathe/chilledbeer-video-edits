"""Jump-cut zoom: a new framing at a new thought (never A/B on every cut), held for the thought, a punch-in on key
moments, and every zoomed framing recomposed with the eyes on the upper third and a sliver of headroom.

Rules (version 7, from top editors' practice): a reframe changes the scale by at least STEP (closer reads as a
glitch) and lands at a sentence start once the framing has held HOLD_S (a mid-thought cut keeps the framing: a plain
jump cut); a framing held past HOLD_MAX_S may change at the next cut (long takes are split at clause and sentence
ends by split_for_zoom); a punch-in cuts in on its sentence and back out at the next piece.
"""
from __future__ import annotations

import numpy as np

from shorts import config
from shorts.plan.cuts import Seg
from shorts.schemas import Sentence

DEFAULT_CENTER = (540.0, 768.0)
THIRD = 1 / 3              # the eyes' line in a zoomed framing
HEADROOM = 0.03            # of the frame height, kept above the hair
EYE_K, TOP_K = 0.36, 0.29  # YuNet box: the eyes sit 0.36 box heights below its top, the hair tops out 0.29 above it
                           # (measured on jobs/ew2: eye landmarks on 40 frames, hairline on 5)
HOLD_S = 1.5               # a reframe needs the framing held this long (shorts hold a thought 1-3 s)
HOLD_MAX_S = 4.0           # a framing held longer than this changes at the next cut
STEP = 1.1                 # two framings closer than this read as a glitch, not a cut


def _faces(face_track: list, sample_fps: float, t0: float, t1: float) -> list:
    a, b = int(t0 * sample_fps), int(np.ceil(t1 * sample_fps)) + 1
    return [f for f in face_track[a:b] if f]


def face_center(face_track: list, sample_fps: float, t0: float, t1: float) -> tuple[float, float] | None:
    faces = _faces(face_track, sample_fps, t0, t1)
    if not faces:
        return None
    return float(np.median([f[0] + f[2] / 2 for f in faces])), float(np.median([f[1] + 0.45 * f[3] for f in faces]))


def face_frame(face_track: list, sample_fps: float, t0: float, t1: float) -> tuple[float, float] | None:
    """(eye line, top of the hair) of the median face box in the source, or None."""
    faces = _faces(face_track, sample_fps, t0, t1)
    if not faces:
        return None
    y, h = float(np.median([f[1] for f in faces])), float(np.median([f[3] for f in faces]))
    return y + EYE_K * h, y - TOP_K * h


def crop_for(zoom: float, center: tuple[float, float] | None,
             frame: tuple[float, float] | None = None) -> list[int] | None:
    """[w, h, x, y] of the source crop for this zoom, or None for no zoom. The face keeps its x; with `frame` (eye
    line, hair top) the eyes go on the upper third with HEADROOM above the hair, else the face centre keeps its place."""
    if zoom <= 1.0001:
        return None
    W, H = config.OUT_W, config.OUT_H
    cw, ch = int(round(W / zoom / 2)) * 2, int(round(H / zoom / 2)) * 2
    cx, cy = center or DEFAULT_CENTER
    x = min(max(cx - cx / W * cw, 0), W - cw)
    if frame:
        eye, top = frame
        s = H / ch
        y = eye - max(H * THIRD, HEADROOM * H + (eye - top) * s) / s
    else:
        y = cy - cy / H * ch
    y = min(max(y, 0), H - ch)
    return [cw, ch, int(round(x / 2)) * 2, int(round(y / 2)) * 2]


def assign_zoom(segs: list[Seg], sentences: list[Sentence], punch_ids: set[str], face_track: list,
                sample_fps: float, zoom_jump: float, zoom_punch: float) -> list[tuple[float, list[int] | None]]:
    starts = {s.first for s in sentences if s.id in punch_ids}
    firsts = sorted(s.first for s in sentences)
    frames = (1.0, zoom_jump)
    out: list[tuple[float, list[int] | None]] = []
    prev, prev_z, base, since, t = None, None, 0, 0.0, 0.0
    far = lambda a, b: max(a, b) / min(a, b) >= STEP          # noqa: E731
    for seg in segs:
        new_thought = prev is not None and any(prev.last < f <= seg.first for f in firsts)
        short = prev is not None and seg.duration < config.ZOOM_MIN_SEG_S
        if prev is None:
            z = frames[base]
        elif short:
            z = prev_z                     # a piece under ~1 s keeps the framing: a change that brief reads as a glitch
        elif any(seg.first <= i <= seg.last for i in starts):
            if prev_z == zoom_punch or prev_z <= 1.0 or far(zoom_punch, prev_z):
                z = zoom_punch             # (two punched sentences in a row share one punch)
            else:
                z = round(prev_z * STEP, 3)  # a custom zoom_jump close to zoom_punch: still a visible punch-in
        elif prev_z not in frames:         # cut back out of a punch: the other framing at a new thought, never within STEP
            order = [1 - base, base] if new_thought else [base, 1 - base]
            base = next((v for v in order if far(frames[v], prev_z)), 0)
            z = frames[base]
        elif (new_thought and t - since >= HOLD_S) or t - since >= HOLD_MAX_S:
            base = 1 - base                # a new thought, held long enough: the other framing
            z = frames[base]
        else:
            z = prev_z                     # the same thought: keep the framing (a plain jump cut)
        if prev is not None and z != prev_z:
            since = t
        out.append((z, crop_for(z, face_center(face_track, sample_fps, seg.t_in, seg.t_out),
                                face_frame(face_track, sample_fps, seg.t_in, seg.t_out))))
        prev, prev_z, t = seg, z, t + seg.duration
    return out
