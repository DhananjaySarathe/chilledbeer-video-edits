"""Exact word times from aligner spans plus the energy envelope, then sentences and pauses."""
from __future__ import annotations

import re

import numpy as np

from shorts.analyze.transcribe import RawWord
from shorts.schemas import Pause, Sentence, Word

HOP = 0.01
START_SEARCH_S = 0.35   # aligned starts run late (vowel onsets): look back this far for the real onset
END_SEARCH_S = 0.20
MIN_GAP_FRAMES = 3      # 30 ms of quiet counts as a real gap
START_BIAS_S = 0.05     # correction when no quiet frame precedes the word
_END = re.compile(r"[.?!…]['\"”’)]*$")
OBVIOUS_FILLERS = frozenset({"um", "umm", "uh", "uhh", "uhm", "erm", "er", "hmm", "hm", "mm"})


def bare(text: str) -> str:
    """Lowercase letters and apostrophes only: 'Uh,' -> 'uh'."""
    return re.sub(r"[^a-z']", "", text.lower())


def _quiet_run(quiet: np.ndarray, k: int, step: int) -> int:
    n = 0
    while 0 <= k < len(quiet) and quiet[k] and n < MIN_GAP_FRAMES:
        n += 1
        k += step
    return n


def _onset(quiet: np.ndarray, gap: np.ndarray, s: float, e: float, floor_t: float) -> tuple[float, bool]:
    """Word start snapped to the audio onset (strict `quiet` mask); the flag says a real gap precedes it (`gap` mask)."""
    n = len(quiet)
    if n == 0:
        return s, False
    k = min(max(int(round(s / HOP)), 0), n - 1)
    if quiet[k]:                                   # aligned start sits in silence: the word begins at the next loud frame
        stop = min(n, max(k + 1, int(round(e / HOP))))
        j = k
        while j < stop and quiet[j]:
            j += 1
        return j * HOP, _quiet_run(gap, j - 1, -1) >= MIN_GAP_FRAMES
    lo = max(int(round(floor_t / HOP)), int(round((s - START_SEARCH_S) / HOP)), 0)
    while k >= lo and not quiet[k]:
        k -= 1
    if k >= lo:
        return (k + 1) * HOP, _quiet_run(gap, k, -1) >= MIN_GAP_FRAMES
    return max(s - START_BIAS_S, floor_t), False


def _offset(quiet: np.ndarray, gap: np.ndarray, e: float, ceil_t: float) -> tuple[float, bool]:
    n = len(quiet)
    if n == 0:
        return e, False
    hi = min(int(round(min(ceil_t, e + END_SEARCH_S) / HOP)), n - 1)
    k = min(max(int(round(e / HOP)), 0), n - 1)
    while k <= hi and not quiet[k]:
        k += 1
    if k <= hi:
        return k * HOP, _quiet_run(gap, k, +1) >= MIN_GAP_FRAMES
    return e, False


def blobs(db: np.ndarray, dip_db: float, t0: float, t1: float, min_s: float = 0.08) -> list[tuple[float, float]]:
    """Bursts of sound louder than dip_db between t0 and t1, split at every dip, at least min_s long."""
    a, b = max(0, int(round(t0 / HOP))), min(len(db), int(round(t1 / HOP)))
    loud = db[a:b] > dip_db
    out, k = [], 0
    while k < len(loud):
        if not loud[k]:
            k += 1
            continue
        j = k
        while j < len(loud) and loud[j]:
            j += 1
        if (j - k) * HOP >= min_s - 1e-9:
            out.append((round((a + k) * HOP, 3), round((a + j) * HOP, 3)))
        k = j
    return out


def place_fillers(texts: list[str], spans: list[tuple[float, float] | None], db: np.ndarray,
                  dip_db: float) -> list[tuple[float, float] | None]:
    """Move obvious fillers onto their own burst of sound. The aligner (trained on read speech) hears "uh" as
    silence, squeezes it into a neighbour's tail and leaves the real sound unassigned."""
    spans = list(spans)
    for i, text in enumerate(texts):
        if bare(text) not in OBVIOUS_FILLERS or spans[i] is None:
            continue
        lo = next((spans[k][1] for k in range(i - 1, -1, -1) if spans[k]), 0.0)
        hi = next((spans[k][0] for k in range(i + 1, len(spans)) if spans[k]), len(db) * HOP)
        cands = blobs(db, dip_db, lo, hi)
        if not cands:
            continue
        s, e = spans[i]

        def covers(c: tuple[float, float]) -> bool:
            return min(c[1], e) - max(c[0], s) > 0.5 * (e - s)

        spans[i] = max(cands, key=lambda c: (covers(c), c[1] - c[0]))
    return spans


def _fill_unaligned(base: list[list]) -> None:
    """Spread words the aligner could not place between their aligned neighbours, by length."""
    n, i = len(base), 0
    while i < n:
        if base[i][2]:
            i += 1
            continue
        j = i
        while j < n and not base[j][2]:
            j += 1
        lo = base[i - 1][1] if i > 0 else base[i][0]
        hi = base[j][0] if j < n else base[j - 1][1]
        if hi > lo:
            lens = [max(len(base[k][3]), 1) for k in range(i, j)]
            t, total = lo, sum(lens)
            for k, length in zip(range(i, j), lens):
                d = (hi - lo) * length / total
                base[k][0], base[k][1] = t, t + d
                t += d
        i = j


def refine_words(raw: list[RawWord], spans: list[tuple[float, float] | None], db: np.ndarray,
                 quiet_db: float, gap_db: float | None = None) -> list[Word]:
    """Exact word times. Edges snap to strict silence (quiet_db); gap flags use gap_db (the cut-safe dip level),
    so a breath or room noise between two words does not hide a usable gap."""
    base = [[sp[0], sp[1], True, w.text] if sp else [w.start, w.end, False, w.text] for w, sp in zip(raw, spans)]
    _fill_unaligned(base)
    quiet = db < quiet_db
    gap = db < (quiet_db if gap_db is None else gap_db)
    out: list[Word] = []
    prev_end = 0.0
    for i, (s, e, aligned, _) in enumerate(base):
        s = max(s, prev_end)
        e = max(e, s + 0.03)
        start, start_gap = _onset(quiet, gap, s, e, prev_end)
        next_s = base[i + 1][0] if i + 1 < len(base) else len(db) * HOP
        end, end_gap = _offset(quiet, gap, e, next_s)
        start = max(start, prev_end)
        end = max(end, start + 0.03)
        out.append(Word(i=i, text=raw[i].text, start=round(start, 3), end=round(end, 3), p=round(raw[i].p, 3),
                        aligned=aligned, start_gap=start_gap, end_gap=end_gap))
        prev_end = end
    return out


def group_sentences(words: list[Word], max_words: int = 40, gap_s: float = 1.0) -> list[Sentence]:
    out: list[Sentence] = []
    first = 0
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        boundary = (nxt is None or (_END.search(w.text) and nxt.text[:1].isupper())
                    or nxt.start - w.end > gap_s or i - first + 1 >= max_words)
        if boundary:
            seg = words[first:i + 1]
            out.append(Sentence(id=f"s{len(out) + 1}", first=first, last=i, text=" ".join(x.text for x in seg),
                                start=seg[0].start, end=seg[-1].end))
            first = i + 1
    return out


def find_pauses(words: list[Word], min_s: float = 0.15) -> list[Pause]:
    out = []
    for a, b in zip(words, words[1:]):
        gap = b.start - a.end
        if gap >= min_s:
            out.append(Pause(after=a.i, start=a.end, end=b.start, duration=round(gap, 3)))
    return out
