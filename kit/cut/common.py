"""Shared pieces for kit/cut: paths, word loading, text normalisation, the word-id scheme and the lexicon."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from kit.paths import CACHE, ROOT, job_dir, job_source, job_temp  # noqa: E402,F401  (re-exported for sentmap)

MODELS = ROOT / "kit" / "models"
EVAL = CACHE / "cut-eval"                                     # evaluate/calibrate reports (output/temp: regenerated)
os.environ.setdefault("HF_HOME", str(MODELS / "hf"))          # SaT + tokenizer downloads stay in kit/models (gitignored)


def norm(text: str) -> str:
    """Lowercase, outer punctuation stripped, inner kept ("5.5", "it's", "token-wise")."""
    return re.sub(r"^[^\w]+|[^\w]+$", "", text.lower())


def load_words(job: str) -> list[dict]:
    d = json.loads((job_dir(job) / "analysis.json").read_text())
    return [{"i": w["i"], "text": w["text"], "start": float(w["start"]), "end": float(w["end"])} for w in d["words"]]


def job_language(job: str) -> str:
    return json.loads((job_dir(job) / "analysis.json").read_text()).get("language", "en")


# ---------------------------------------------------------------- word ids in an edit -> (job, word index)
class IdMap:
    """An edit's word ids name words in one or more takes: id = base[job] + index, and a copy of a word placed twice
    (a cold open) adds `wrap` (ExpenseWaale: take 1 = i, take 2 = 2000 + i, cold-open copy +10000)."""

    def __init__(self, sources: dict[str, int], wrap: int | None = 10000):
        self.sources = dict(sorted(sources.items(), key=lambda kv: kv[1]))
        self.wrap = wrap

    @classmethod
    def parse(cls, spec: str | None, wrap: int | None = 10000) -> "IdMap":
        """'ew1=0,ew2=2000' or a single job name 'ew2' (base 0)."""
        out = {}
        for part in (spec or "").split(","):
            part = part.strip()
            if not part:
                continue
            job, _, base = part.partition("=")
            out[job] = int(base or 0)
        return cls(out, wrap)

    def resolve(self, wid: int) -> tuple[str, int, bool]:
        """-> (job, index in that take, is_copy)."""
        copy = False
        if self.wrap and wid >= self.wrap:
            wid, copy = wid % self.wrap, True
        job = None
        for j, base in self.sources.items():
            if wid >= base:
                job = j
        if job is None:
            raise KeyError(f"word id {wid} matches no source {self.sources}")
        return job, wid - self.sources[job], copy

    def to_id(self, job: str, index: int) -> int:
        return self.sources[job] + index


# ---------------------------------------------------------------- lexicon (English + romanised Hindi)
# HARD: a piece that ends/starts on one of these is always a FAIL (the words promise or need a neighbour).
# SOFT: a weaker hint, used as a feature of the boundary model (Hinglish right-dislocates: "limit reset hoti hai
# Claude ki" ends on a postposition, and "ki" is also the verb "did", so the Hindi postpositions are soft on the left).
LEFT_HARD = frozenset("""
and but because or nor the a an of to for with from into than which who whom whose where while if unless although
though whether i'm i've i'll i'd we're you're they're it's my your our their its
aur lekin kyunki kyonki jo jab agar matlab ya
""".split())
LEFT_SOFT = frozenset("""
so like in on at by about is are was were am be very really just also then this these those when that what how
ki ke ka ko se mein pe par main toh wala wali wale
""".split())
RIGHT_HARD = frozenset("""
ki ke ka ko se mein hai hain tha thi hoga hogi wala wali wale which of whom whose than
""".split())
RIGHT_SOFT = frozenset("that to is are was were or like".split())
# Hindi clause endings: a verb or auxiliary usually closes a Hindi clause ("...ho jaata hai", "nahi karne wala hoon").
HINDI_FINAL = frozenset("""
hai hain tha thi hoga hogi hoge chahiye hoon hun gaya gayi gaye raha rahi rahe kiya kiye liya diya karta
karti karte karenge karega jaaye jaye jayega sakta sakte haina
""".split())
# Tags that close a thought ("..., right?" "..., na?").
TAGS = frozenset("right na okay ok yeah".split())
# Words that often open a new sentence in this speaker's talk.
STARTERS = frozenset("so but now first by if when toh then basically okay".split())
FILLERS = frozenset("um umm uh uhh uhm erm er hmm hm mm".split())
