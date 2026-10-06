"""Snap helpers: cut correctly by construction. Given a desired keep range (first word, last word) of a take, return the
nearest valid sentence start/end; on a restart, the end of the previous complete sentence.

    uv run python -m kit.cut.boundaries ew2 2103 2141            (ids in the take; --base=2000 to use edit ids)
    uv run python -m kit.cut.boundaries ew2 --restart 2357        (cut back to the previous sentence end)
    uv run python -m kit.cut.boundaries ew2 --sentences [--from=300 --to=400]   (the take as sentences)

In code (an edl.py / reel_edl.py):
    from kit.cut.boundaries import Boundaries
    B = Boundaries("ew2")
    a, b = B.snap(103, 141)              # -> (86, 146): the whole sentences that cover the range
    a, b = B.snap(103, 141, mode="shrink")   # -> the whole sentences inside it (None if there are none)
    B.restart_cut(357)                   # -> 347: keep up to here, drop the abandoned attempt
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kit.cut.common import FILLERS, norm  # noqa: E402
from kit.cut.sentmap import P_CLAUSE, P_SENT, SentMap  # noqa: E402

# Words that may hang at a sentence edge without being content: dropping them never crops a sentence.
OPENERS = frozenset("so and but yeah okay ok basically anyways anyway now toh matlab like actually well sorry also "
                    "haan accha um umm uh uhh hmm".split())
TAILS = frozenset("right na yeah okay ok basically haina so um uh".split())


class Boundaries:
    def __init__(self, job: str, sm: SentMap | None = None):
        self.job = job
        self.sm = sm or SentMap.load(job)
        self.words = [(g["after"], g["left"]) for g in self.sm.sm["gaps"]]
        self.text = {k: t for k, t in self.words}
        self.n = len(self.words)
        self._cache = {}

    def w(self, k: int) -> str:
        return norm(self.text.get(k, ""))

    # -- effective boundary strength (lets an edit drop a leading "So," or a trailing ", right?")
    def p_start(self, k: int, max_openers: int = 3) -> tuple[float, int]:
        """Strength of a sentence start at word k: the gap before k, or before up to 3 opener words that precede k
        (starting at "as I said" after "So," is a sentence start). -> (p, the gap's word index)."""
        best, at = self.sm.p_start(k), k - 1
        j = k - 1
        for _ in range(max_openers):
            if j < 0 or self.w(j) not in OPENERS:
                break
            p = self.sm.p_start(j)
            if p > best:
                best, at = p, j - 1
            j -= 1
        return best, at

    def p_end(self, k: int, max_tails: int = 2) -> tuple[float, int]:
        """Strength of a sentence end at word k: the gap after k, or after up to 2 tag words that follow k
        ("...max effort | , right?")."""
        best, at = self.sm.p_end(k), k
        j = k + 1
        for _ in range(max_tails):
            if j >= self.n or self.w(j) not in TAILS:
                break
            p = self.sm.p_end(j)
            if p > best:
                best, at = p, j
            j += 1
        return best, at

    # -- snapping
    def starts(self, level: float = P_SENT) -> list[int]:
        """Sentence starts to cut at (the word right after a boundary; openers like "So," are kept, not skipped)."""
        if ("s", level) not in self._cache:
            self._cache[("s", level)] = [k for k in range(self.n) if self.sm.p_start(k) >= level and self.w(k) not in FILLERS]
        return self._cache[("s", level)]

    def ends(self, level: float = P_SENT) -> list[int]:
        if ("e", level) not in self._cache:
            self._cache[("e", level)] = [k for k in range(self.n) if self.sm.p_end(k) >= level and self.w(k) not in FILLERS]
        return self._cache[("e", level)]

    def snap_start(self, k: int, direction: str = "back", level: float = P_SENT) -> int | None:
        cands = self.starts(level)
        if direction == "back":
            c = [s for s in cands if s <= k]
            return c[-1] if c else 0
        if direction == "forward":
            c = [s for s in cands if s >= k]
            return c[0] if c else None
        return min(cands, key=lambda s: (abs(s - k), s > k)) if cands else 0

    def snap_end(self, k: int, direction: str = "forward", level: float = P_SENT) -> int | None:
        cands = self.ends(level)
        if direction == "forward":
            c = [e for e in cands if e >= k]
            return c[0] if c else self.n - 1
        if direction == "back":
            c = [e for e in cands if e <= k]
            return c[-1] if c else None
        return min(cands, key=lambda e: (abs(e - k), e < k)) if cands else self.n - 1

    def snap(self, a: int, b: int, mode: str = "expand", level: float = P_SENT) -> tuple[int | None, int | None]:
        """Keep range [a, b] -> whole sentences. expand: the sentences that cover it; shrink: those inside it;
        nearest: the closest start/end either way."""
        if mode == "expand":
            return self.snap_start(a, "back", level), self.snap_end(b, "forward", level)
        if mode == "shrink":
            s, e = self.snap_start(a, "forward", level), self.snap_end(b, "back", level)
            return (s, e) if s is not None and e is not None and s <= e else (None, None)
        return self.snap_start(a, "nearest", level), self.snap_end(b, "nearest", level)

    def restart_cut(self, k: int, level: float = P_SENT) -> int | None:
        """The speaker abandons the sentence that contains word k and starts again: keep up to the end of the
        previous complete sentence (the last sentence end before that sentence's start)."""
        s = self.snap_start(k, "back", level)
        return s - 1 if s and s > 0 else None

    def sentences(self, lo: int = 0, hi: int | None = None, level: float = P_SENT) -> list[tuple[int, int, str]]:
        hi = self.n - 1 if hi is None else hi
        out, first = [], lo
        for k in range(lo, hi + 1):
            if k == hi or self.sm.p_end(k) >= level:
                out.append((first, k, " ".join(self.text[j] for j in range(first, k + 1))))
                first = k + 1
        return out

    def describe(self, k: int, side: str) -> str:
        p = self.p_start(k)[0] if side == "start" else self.p_end(k)[0]
        lab = "sentence" if p >= P_SENT else "clause" if p >= P_CLAUSE else "mid-sentence"
        return f"{lab} (p {p:.2f})"


def _ctx(B: Boundaries, k: int, before: int = 6, after: int = 6) -> str:
    left = " ".join(B.text[j] for j in range(max(0, k - before), k))
    right = " ".join(B.text[j] for j in range(k, min(B.n, k + after)))
    return f"...{left} | {right}..."


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 1
    job = args[0]
    base = int(next((a.split("=", 1)[1] for a in argv if a.startswith("--base=")), 0))
    B = Boundaries(job)
    if "--sentences" in argv:
        lo = int(next((a.split("=", 1)[1] for a in argv if a.startswith("--from=")), 0)) - base
        hi = next((a.split("=", 1)[1] for a in argv if a.startswith("--to=")), None)
        for s, e, text in B.sentences(max(0, lo), None if hi is None else int(hi) - base):
            print(f"{s + base:5d}-{e + base:<5d} p_end {B.sm.p_end(e):.2f}  {text}")
        return 0
    if "--restart" in argv:
        k = int(args[1]) - base
        e = B.restart_cut(k)
        print(f"restart at {k + base}: keep up to {None if e is None else e + base}  {_ctx(B, (e or 0) + 1)}")
        return 0
    a, b = int(args[1]) - base, int(args[2]) - base
    print(f"range {a + base}-{b + base}: start is {B.describe(a, 'start')}, end is {B.describe(b, 'end')}")
    for mode in ("expand", "shrink", "nearest"):
        s, e = B.snap(a, b, mode)
        if s is None:
            print(f"  {mode:8s} (no whole sentence inside)")
            continue
        print(f"  {mode:8s} {s + base}-{e + base}: \"{' '.join(B.text[j] for j in range(s, min(s + 8, e + 1)))} ... "
              f"{' '.join(B.text[j] for j in range(max(s, e - 7), e + 1))}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
