"""Turn an analysis into the small questions Jev answers. The wording lives in kit/questions/*.yaml."""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml

from shorts import config
from shorts.analyze.words import OBVIOUS_FILLERS, bare
from shorts.errors import ShortsError
from shorts.schemas import Analysis, Brief, Word

MAYBE_FILLERS = frozenset({"like", "basically", "actually", "literally", "so", "right", "okay", "ok", "well", "just",
                           "matlab", "na", "yaar", "toh", "acha", "accha", "yani"})
STOPWORDS = frozenset("""
the and but for with you your are was were this that these those have has had not can will from they them their
there then than what when where which who how its it's i'm i've you're we're they're our out all any about into also
very really some get got going gonna want more much one lot thing things here now let's don't didn't doesn't isn't
did does been being would could should because over only even yeah yes hai hain aur bhi kya nahi mein main yeh woh
par
""".split())
PAUSE_ASK_S = 0.35
TEMPLATES = ("false_start", "filler_word", "duplicate_take", "deliberate_pause", "punch_in")
POLICY = {"false_start": "destructive", "filler_word": "destructive", "duplicate_take": "destructive",
          "deliberate_pause": "shaping", "punch_in": "cosmetic"}
WORD_STRIP = ".,;:!?—–-…\"“”'()[]"


@dataclass
class Spec:
    id: str
    group: str
    subject: dict
    kind: str          # "noul" or "choice"
    payload: dict      # the question exactly as sent to Jev
    policy: str        # "destructive", "shaping" or "cosmetic"
    default: Any       # used when Jev is unsure or unreachable


def load_templates(folder: Path = config.QUESTIONS) -> dict[str, dict]:
    tpl: dict[str, dict] = {}
    for f in sorted(Path(folder).glob("*.yaml")):
        tpl.update(yaml.safe_load(f.read_text()) or {})
    missing = [t for t in TEMPLATES if t not in tpl]
    if missing:
        raise ShortsError("E_QUESTIONS", f"Question templates missing from {folder}: {missing}",
                          "Restore kit/questions/*.yaml from git.")
    return tpl


def clean(text: str) -> str:
    """Safe inside a double-quoted phrase in a question."""
    return " ".join(text.replace('"', "'").split())


def noul(tpl: dict, **fields) -> dict:
    crit = tpl.get("criteria") or {}
    return {"type": "noul", "instructions": tpl["instructions"].format(**fields).strip(),
            "criteria": {"true": crit.get("if_true"), "false": crit.get("if_false")}}


def choice(tpl: dict, options: dict[str, str], **fields) -> dict:
    return {"type": "choice", "instructions": tpl["instructions"].format(**fields).strip(), "criteria": options}




def duplicate_groups(analysis: Analysis, window: int = 3, threshold: float = 0.6) -> list[list[str]]:
    """Sentences that say nearly the same thing close together (retakes), as lists of sentence ids in order."""
    sents = analysis.sentences
    toks = [[bare(w.text) for w in analysis.words[s.first:s.last + 1]] for s in sents]
    parent = list(range(len(sents)))

    def find(i: int) -> int:
        while parent[i] != i:
            i = parent[i]
        return i

    for i in range(len(sents)):
        if len(toks[i]) < 3:
            continue
        for j in range(i + 1, min(len(sents), i + 1 + window)):
            if len(toks[j]) >= 3 and SequenceMatcher(a=toks[i], b=toks[j], autojunk=False).ratio() >= threshold:
                parent[find(j)] = find(i)
    groups: dict[int, list[str]] = {}
    for i, s in enumerate(sents):
        groups.setdefault(find(i), []).append(s.id)
    return [g for g in groups.values() if len(g) > 1]


def sentence_notes(analysis: Analysis, brief: Brief) -> list[str]:
    """Visual notes and picture problems keyed by sentence id. Jev is weak with timecodes, so it never sees them."""
    def ids(start: float, end: float) -> str:
        return ", ".join(s.id for s in analysis.sentences if s.start < end and s.end > start)

    notes = [f"{ids(n.start, n.end) or 'between sentences'}: {n.note}" for n in brief.visual_notes]
    pic = analysis.picture
    for label, ranges in (("face not visible", pic.no_face), ("picture blurry", pic.blurry), ("picture dark", pic.dark)):
        notes += [f"{ids(r.start, r.end)}: {label}" for r in ranges if ids(r.start, r.end)]
    return notes


def said(words: list[Word], i0: int, i1: int, overrides: dict[int, str]) -> str:
    """Words i0..i1 as the captions read them (Hinglish respellings applied; an empty override drops a word)."""
    out = []
    for w in words[i0:i1 + 1]:
        t = overrides[w.i].strip() if w.i in overrides else w.text
        if not t:
            continue
        if w.i in overrides and w.text[-1:] in ",.?!" and t[-1:] not in ",.?!":
            t += w.text[-1]
        out.append(t)
    return " ".join(out)


def build(analysis: Analysis, brief: Brief, tpl: dict[str, dict]) -> tuple[dict, list[Spec], list[int]]:
    """(state shared by every question, question specs, word indices removed by rule without asking)."""
    words, sents, ov = analysis.words, analysis.sentences, brief.caption_overrides
    text_of = {s.id: said(words, s.first, s.last, ov) for s in sents}
    state = {
        "topic": brief.topic or "not given",
        "language": analysis.language,
        "sentences": [{"id": s.id, "text": text_of[s.id]} for s in sents],
        "notes": sentence_notes(analysis, brief),
    }
    auto = [w.i for w in words if bare(w.text) in OBVIOUS_FILLERS]
    sentence_of = {i: s for s in sents for i in range(s.first, s.last + 1)}
    specs: list[Spec] = []

    def add(id_: str, group: str, subject: dict, kind: str, payload: dict, default: Any) -> None:
        specs.append(Spec(id_, group, subject, kind, payload, POLICY[group], default))

    for k, s in enumerate(sents):
        text = clean(text_of[s.id])
        if k + 1 < len(sents):
            add(f"false_start:{s.id}", "false_start", {"sentence": s.id}, "noul",
                noul(tpl["false_start"], sid=s.id, sentence=text, next_sentence=clean(text_of[sents[k + 1].id])), False)
        add(f"punch_in:{s.id}", "punch_in", {"sentence": s.id}, "noul",
            noul(tpl["punch_in"], sid=s.id, sentence=text), False)
    for w in words:
        if bare(w.text) in MAYBE_FILLERS and w.i in sentence_of:
            s = sentence_of[w.i]
            marked = " ".join(f"[{said(words, x.i, x.i, ov) or x.text}]" if x.i == w.i else said(words, x.i, x.i, ov)
                              for x in words[s.first:s.last + 1])
            add(f"filler:{w.i}", "filler_word", {"word": w.i, "sentence": s.id}, "noul",
                noul(tpl["filler_word"], sid=s.id, word=bare(w.text), marked=clean(marked)), False)
    for p in analysis.pauses:
        if p.duration >= PAUSE_ASK_S:
            before = said(words, max(0, p.after - 5), p.after, ov)
            after = said(words, p.after + 1, min(len(words) - 1, p.after + 6), ov)
            add(f"pause:{p.after}", "deliberate_pause", {"pause_after": p.after, "duration": p.duration}, "noul",
                noul(tpl["deliberate_pause"], duration=f"{p.duration:.2f}", before=clean(before), after=clean(after)),
                False)
    by_id = {s.id: s for s in sents}
    for group in duplicate_groups(analysis):
        t = tpl["duplicate_take"]
        options = {sid: t["option"].format(n=n + 1, sid=sid, sentence=clean(text_of[sid]))
                   for n, sid in enumerate(group)}
        add("dup:" + "+".join(group), "duplicate_take", {"takes": group}, "choice",
            choice(t, options, takes=", ".join(group)), group[-1])
    return state, specs, auto
