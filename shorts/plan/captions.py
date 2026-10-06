"""Word-by-word caption pages: which words show together, when, where, and at what scale."""
from __future__ import annotations

import re

from shorts import config, fonts
from shorts.plan.cuts import Seg
from shorts.plan.zoom import EYE_K, TOP_K, crop_for
from shorts.schemas import CaptionPage, Captions, CaptionWord, FaceBox, Style, Word

STRIP = ".,;:—–-…\"“”()[]"
PAGE_GAP_S = 0.35        # a silence longer than this starts a new page
HOLD_S = 0.15            # how long a page stays up after its last word when nothing follows at once
MIN_PAGE_S = 0.25
_SENTENCE_END = re.compile(r"[.?!…]['\"”’)]*$")


def display_text(text: str, uppercase: bool) -> str:
    t = text.replace("{", "").replace("}", "").replace("\\", "").strip().strip(STRIP)
    return t.upper() if uppercase else t


def block_height(font_size: int, outline_px: int) -> float:
    return font_size * 1.3 + 2 * outline_px


def max_width(outline_px: int) -> float:
    return (1 - config.SAFE_LEFT - config.SAFE_RIGHT) * config.OUT_W - 2 * outline_px - 20


def face_rows(face: FaceBox, zoom: float) -> tuple[float, float]:
    """Top and bottom of the face box on screen at this zoom, framed the way zoom.crop_for frames it."""
    crop = crop_for(zoom, (face.x + face.w / 2, face.y + 0.45 * face.h), (face.y + EYE_K * face.h, face.y - TOP_K * face.h))
    if crop is None:
        return face.y, face.y + face.h
    s = config.OUT_H / crop[1]
    return (face.y - crop[3]) * s, (face.y + face.h - crop[3]) * s


def place(style: Style, face: FaceBox | None, zoom: float) -> tuple[float, float, list[str]]:
    """Caption centre (x, y) inside the safe zone. Tries the requested height, then just below the face, then just
    above it, and takes the first that covers at most a quarter of the caption height of the face (zoomed about
    the way crop_for frames it). Close selfies can fill the whole band; then the least overlap wins."""
    W, H = config.OUT_W, config.OUT_H
    cx = (config.SAFE_LEFT + 1 - config.SAFE_RIGHT) / 2 * W
    bh = block_height(style.font_size, style.outline_px)
    lo, hi = config.SAFE_TOP * H + bh / 2, (1 - config.SAFE_BOTTOM) * H - bh / 2
    cy = min(max(style.position_y * H, lo), hi)
    if face is None:
        return round(cx, 1), round(cy, 1), []
    top, bottom = face_rows(face, zoom)

    def overlap(y: float) -> float:
        return max(0.0, min(y + bh / 2, bottom) - max(y - bh / 2, top))

    options = [cy, min(max(bottom + bh / 2 + 20, lo), hi), min(max(top - bh / 2 - 20, lo), hi)]
    fine = [y for y in options if overlap(y) <= 0.25 * bh]
    cy = fine[0] if fine else min(options, key=overlap)
    warnings = [f"captions cover {overlap(cy):.0f}px of the face"] if overlap(cy) > 0.25 * bh else []
    return round(cx, 1), round(cy, 1), warnings


def layout_captions(segs: list[Seg], out_starts: list[float], words: list[Word], highlights: set[int],
                    overrides: dict[int, str], style: Style, face: FaceBox | None,
                    zoom: float | None = None) -> tuple[Captions, list[str]]:
    """Caption pages on the output timeline; zoom is the largest zoom the edit uses (default: the punch-in)."""
    font = fonts.font_path(style.font)
    maxw = max_width(style.outline_px)

    def width(items: list[tuple]) -> float:
        return fonts.text_width(font, " ".join(t[1] for t in items), style.font_size, style.spacing)

    timed: list[tuple] = []     # (word index, display text, out start, out end, ends a sentence)
    for seg, o in zip(segs, out_starts):
        for i in range(seg.first, seg.last + 1):
            w = words[i]
            text = display_text(overrides.get(i, w.text), style.uppercase)
            if not text:
                continue
            s = o + min(max(w.start - seg.t_in, 0.0), seg.duration)
            e = max(o + min(max(w.end - seg.t_in, 0.0), seg.duration), s + 0.05)
            # an override may be several words (Whisper merged them): share the time out by length so each
            # one lights up in turn instead of one big box
            parts = text.split()
            total = sum(len(p) for p in parts)
            t = s
            for k, part in enumerate(parts):
                t1 = e if k == len(parts) - 1 else t + (e - s) * len(part) / total
                last = k == len(parts) - 1
                timed.append((i, part, round(t, 3), round(t1, 3), last and bool(_SENTENCE_END.search(w.text))))
                t = t1
    groups: list[list[tuple]] = []
    for item in timed:
        if groups:
            cur, prev = groups[-1], groups[-1][-1]
            if (len(cur) < style.words_per_page and not prev[4] and item[2] - prev[3] <= PAGE_GAP_S
                    and width(cur + [item]) <= maxw):
                cur.append(item)
                continue
        groups.append([item])
    total = out_starts[-1] + segs[-1].duration if segs else 0.0
    pages = []
    for k, g in enumerate(groups):
        start, last_end = g[0][2], g[-1][3]
        nxt = groups[k + 1][0][2] if k + 1 < len(groups) else None
        end = nxt if nxt is not None and nxt - last_end <= PAGE_GAP_S else last_end + HOLD_S
        end = max(end, start + MIN_PAGE_S)
        end = min(end, nxt if nxt is not None else total)
        w_px = width(g)
        pages.append(CaptionPage(start=start, end=round(end, 3), scale=round(min(1.0, maxw / w_px), 3) if w_px else 1.0,
                                 words=[CaptionWord(text=t[1], start=t[2], end=t[3], highlight=t[0] in highlights)
                                        for t in g]))
    cx, cy, warnings = place(style, face, style.zoom_punch if zoom is None else zoom)
    return Captions(template=style.caption_template, font=style.font, font_size=style.font_size,
                    text_color=style.text_color, highlight_color=style.highlight_color,
                    outline_color=style.outline_color, outline_px=style.outline_px, shadow_px=style.shadow_px,
                    spacing=style.spacing, uppercase=style.uppercase, center_x=cx, center_y=cy,
                    max_width=round(maxw, 1), pages=pages), warnings
