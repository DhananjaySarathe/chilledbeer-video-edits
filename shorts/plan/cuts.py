"""Turn the words to keep into source segments, cutting only where the audio allows a clean cut."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shorts import config
from shorts.schemas import Word

HOP = 0.01
DIP_SEARCH_S = 0.06      # how far either side of a word boundary to look for the quietest moment


@dataclass
class Seg:
    first: int
    last: int
    t_in: float
    t_out: float

    @property
    def duration(self) -> float:
        return self.t_out - self.t_in


@dataclass
class CutResult:
    segments: list[Seg]
    kept_back: list[int]
    warnings: list[str]


def runs(indices) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for i in sorted(indices):
        if out and i == out[-1][1] + 1:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return out


def min_energy(db: np.ndarray, t0: float, t1: float) -> tuple[float, float]:
    """(time, level in dB) of the quietest 10 ms frame between t0 and t1."""
    a, b = max(0, int(round(t0 / HOP))), min(len(db), int(round(t1 / HOP)) + 1)
    if b <= a:
        return t0, 0.0
    k = a + int(np.argmin(db[a:b]))
    return (k + 0.5) * HOP, float(db[k])


def silent_gap(a: Word, b: Word) -> bool:
    return a.end_gap and b.start_gap and b.start > a.end


def dip_cut(a: Word, b: Word, db: np.ndarray, dip_db: float) -> float | None:
    """The quietest point where word a runs into word b, if it is quiet enough to cut through unnoticed."""
    lo = max(min(a.end, b.start) - DIP_SEARCH_S, (a.start + a.end) / 2)
    hi = min(max(a.end, b.start) + DIP_SEARCH_S, (b.start + b.end) / 2)
    t, level = min_energy(db, lo, hi)
    return t if level <= dip_db else None


def end_after(a: Word, b: Word | None, db: np.ndarray, dip_db: float, duration: float,
              tail: float = config.TAIL_S) -> float | None:
    """Where a segment whose last word is a should end (b is the next word in the source)."""
    if b is None:
        return min(a.end + tail, duration)
    if silent_gap(a, b):
        return min(a.end + tail, b.start)
    return dip_cut(a, b, db, dip_db)


def start_before(z: Word | None, b: Word, db: np.ndarray, dip_db: float) -> float | None:
    """Where a segment whose first word is b should start (z is the previous word in the source)."""
    if z is None:
        return max(b.start - config.LEAD_S, 0.0)
    if silent_gap(z, b):
        return max(b.start - config.LEAD_S, z.end)
    return dip_cut(z, b, db, dip_db)


def _text(words: list[Word], i0: int, i1: int) -> str:
    return " ".join(w.text for w in words[i0:i1 + 1])


def gap_to_keep(text: str, deliberate: bool = False, pace: str = "normal") -> float:
    """Silence left after a word when the pause behind it is trimmed: longer after a sentence than inside one."""
    if deliberate:
        return config.DELIBERATE_PAUSE_MAX_S
    phrase, clause, sentence = config.PACES[pace][:3]
    t = text.rstrip("\"')”’")
    if t.endswith((".", "?", "!")):
        return sentence
    if t.endswith((",", ";", ":")):
        return clause
    return phrase


def _group(words: list[Word], removed: set[int], deliberate: set[int],
           pace: str = "normal") -> tuple[list[list[int]], dict[int, float]]:
    """Kept words in runs that play without a cut; tails[i] = custom tail after word i (deliberate pauses)."""
    groups: list[list[int]] = []
    tails: dict[int, float] = {}
    for w in words:
        if w.i in removed:
            continue
        if groups and groups[-1][-1] == w.i - 1:
            a = words[w.i - 1]
            keep = gap_to_keep(a.text, a.i in deliberate, pace)
            if not (silent_gap(a, w) and w.start - a.end > keep + config.PACES[pace][3]):
                groups[-1].append(w.i)
                continue
            tails[a.i] = keep - config.LEAD_S
        groups.append([w.i])
    return groups, tails


def _merge_short(segs: list[Seg], words: list[Word], kept_back: list[int], warnings: list[str]) -> list[Seg]:
    segs = list(segs)
    while len(segs) > 1:
        k = next((i for i, s in enumerate(segs) if s.duration < config.MIN_SEGMENT_S - 1e-6), None)
        if k is None:
            break
        left = segs[k].t_in - segs[k - 1].t_out if k > 0 else float("inf")
        right = segs[k + 1].t_in - segs[k].t_out if k + 1 < len(segs) else float("inf")
        a = k - 1 if left <= right else k
        restored = list(range(segs[a].last + 1, segs[a + 1].first))
        if restored:
            kept_back += restored
            warnings.append(f"restored '{_text(words, restored[0], restored[-1])}' at "
                            f"{words[restored[0]].start:.2f}s to avoid a flash cut")
        segs[a:a + 2] = [Seg(segs[a].first, segs[a + 1].last, segs[a].t_in, segs[a + 1].t_out)]
    return segs


def build_segments(words: list[Word], removed: set[int], deliberate: set[int], db: np.ndarray, dip_db: float,
                   duration: float, pace: str = "normal") -> CutResult:
    removed = {i for i in removed if 0 <= i < len(words)}
    kept_back: list[int] = []
    warnings: list[str] = []
    if words and len(removed) == len(words):
        warnings.append("refused to remove every word")
        kept_back, removed = sorted(removed), set()
    for r0, r1 in runs(removed):
        z = words[r0 - 1] if r0 > 0 else None
        b = words[r1 + 1] if r1 + 1 < len(words) else None
        clean_start = z is None or end_after(z, words[r0], db, dip_db, duration) is not None
        clean_end = b is None or start_before(words[r1], b, db, dip_db) is not None
        if not (clean_start and clean_end):
            removed -= set(range(r0, r1 + 1))
            kept_back += list(range(r0, r1 + 1))
            warnings.append(f"kept '{_text(words, r0, r1)}' at {words[r0].start:.2f}s: no clean cut point")
    groups, tails = _group(words, removed, deliberate, pace)
    segs = []
    for g in groups:
        f, l = g[0], g[-1]
        z = words[f - 1] if f > 0 else None
        b = words[l + 1] if l + 1 < len(words) else None
        t_in = start_before(z, words[f], db, dip_db)
        t_out = end_after(words[l], b, db, dip_db, duration, tails.get(l, config.TAIL_S))
        segs.append(Seg(f, l, round(t_in, 3), round(t_out, 3)))
    segs = _merge_short(segs, words, kept_back, warnings)
    return CutResult(segs, sorted(kept_back), warnings)


def teaser_segment(words: list[Word], first: int, last: int, db: np.ndarray, dip_db: float,
                   duration: float) -> Seg | None:
    """The cold-open clip: words first..last cut cleanly out of the source, with a short beat after the line."""
    z = words[first - 1] if first > 0 else None
    b = words[last + 1] if last + 1 < len(words) else None
    t_in = start_before(z, words[first], db, dip_db)
    t_out = end_after(words[last], b, db, dip_db, duration, config.COLD_OPEN_TAIL_S)
    if t_in is None or t_out is None:
        return None
    return Seg(first, last, round(t_in, 3), round(t_out, 3))


def split_for_zoom(segs: list[Seg], words: list[Word], every: float = config.ZOOM_CUT_EVERY_S,
                   min_s: float = config.ZOOM_CUT_MIN_S) -> list[Seg]:
    """Break long takes at sentence or clause ends into ~`every`-second pieces that play back to back (nothing
    removed), so the framing can change there. The split sits midway between the two words."""
    out: list[Seg] = []
    for seg in segs:
        cur = seg
        while cur.t_out - cur.t_in > every + min_s:
            best = None
            for i in range(cur.first, cur.last):
                if not words[i].text.rstrip("\"')”’").endswith((".", "?", "!", ",", ";", ":")):
                    continue
                t = (words[i].end + words[i + 1].start) / 2
                if t - cur.t_in < min_s or cur.t_out - t < min_s:
                    continue
                score = abs(t - cur.t_in - every) - (0.6 if words[i].text.rstrip("\"')”’").endswith((".", "?", "!")) else 0)
                if best is None or score < best[0]:
                    best = (score, i, t)
            if best is None:
                break
            _, i, t = best
            out.append(Seg(cur.first, i, cur.t_in, round(t, 3)))
            cur = Seg(i + 1, cur.last, round(t, 3), cur.t_out)
        out.append(cur)
    return out
