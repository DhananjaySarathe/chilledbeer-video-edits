"""Refuse broken edit files before anything is rendered."""
from __future__ import annotations

import math

from shorts import config, fonts
from shorts.errors import ShortsError
from shorts.plan.captions import block_height
from shorts.schemas import EditFile


def _caption_problems(edit: EditFile) -> list[str]:
    cap, W, H = edit.captions, edit.output.width, edit.output.height
    try:
        font = fonts.font_path(cap.font)
    except ShortsError as e:
        return [e.message]
    out: list[str] = []
    bh = block_height(cap.font_size, cap.outline_px)
    if cap.center_y - bh / 2 < config.SAFE_TOP * H - 0.5 or cap.center_y + bh / 2 > (1 - config.SAFE_BOTTOM) * H + 0.5:
        out.append(f"captions at y={cap.center_y} leave the vertical safe zone")
    if (cap.center_x - cap.max_width / 2 < config.SAFE_LEFT * W - 0.5
            or cap.center_x + cap.max_width / 2 > (1 - config.SAFE_RIGHT) * W + 0.5):
        out.append(f"caption width {cap.max_width} at x={cap.center_x} leaves the horizontal safe zone")
    prev_end = 0.0
    for k, p in enumerate(cap.pages):
        if not p.words:
            out.append(f"caption page {k} has no words")
        if p.end <= p.start:
            out.append(f"caption page {k} ends before it starts")
        if p.start < prev_end - 1e-3:
            out.append(f"caption page {k} overlaps the previous page")
        if p.end > edit.duration + 1e-3:
            out.append(f"caption page {k} runs past the end of the video")
        width = fonts.text_width(font, " ".join(w.text for w in p.words), cap.font_size, cap.spacing) * p.scale
        if width > cap.max_width + 1:
            out.append(f"caption page {k} is {width:.0f}px wide (max {cap.max_width:.0f}px)")
        prev_end = p.end
    return out


def validate_edit(edit: EditFile) -> list[str]:
    fps, W, H = edit.output.fps, edit.output.width, edit.output.height
    segs = edit.segments
    if not segs:
        return ["no segments: nothing would be rendered"]
    problems: list[str] = []
    min_frames = max(1, math.ceil(config.MIN_SEGMENT_S * fps) - 1)
    prev_out = 0
    for k, s in enumerate(segs):
        if s.out_frame <= s.in_frame:
            problems.append(f"segment {k} is empty ({s.in_frame}-{s.out_frame})")
        elif len(segs) > 1 and s.out_frame - s.in_frame < min_frames:
            problems.append(f"segment {k} is shorter than {min_frames} frames")
        if s.in_frame < 0 or s.out_frame > edit.source_frames:
            problems.append(f"segment {k} ({s.in_frame}-{s.out_frame}) is outside the source (0-{edit.source_frames})")
        if k >= edit.cold_open and s.in_frame < prev_out:    # the teaser may repeat later footage
            problems.append(f"segment {k} overlaps the previous one")
        if k >= edit.cold_open:
            prev_out = max(prev_out, s.out_frame)
        if s.crop is not None:
            cw, ch, x, y = s.crop
            if cw <= 0 or ch <= 0 or cw % 2 or ch % 2 or x < 0 or y < 0 or x + cw > W or y + ch > H:
                problems.append(f"segment {k} crop {s.crop} does not fit the {W}x{H} frame")
    total = sum(s.out_frame - s.in_frame for s in segs) / fps
    if abs(total - edit.duration) > 1e-3:
        problems.append(f"duration {edit.duration} does not match the segments ({total:.3f}s)")
    return problems + _caption_problems(edit)
