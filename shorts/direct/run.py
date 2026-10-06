"""`shorts direct`: Jev picks a visual for every beat of the edited video -> visuals_draft.json.

Beats are 1-3.5 s slices of the edited timeline. For each beat Jev answers one multiple-choice question: stay on
the speaker, one of the library templates (chosen by their descriptions), or "new" (Claude makes a template).
Claude then fills the picked templates' words into visuals.json.
"""
from __future__ import annotations

import json
import re

from shorts import config
from shorts.brief import load_brief
from shorts.decide.jev import Asker, JevAsker
from shorts.errors import ShortsError
from shorts.gfx.library import load_library
from shorts.gfx.timeline import source_to_output, word_timeline
from shorts.job import Job
from shorts.schemas import Analysis, EditFile

MAX_BEAT_S = 3.4
PAUSE_BREAK_S = 0.3
_END = re.compile(r"[.?!…]['\"”’)]*$")
_SOFT = re.compile(r"[,;:—–]$")
SPEAKER, NEW = "speaker", "new"


STARTERS = {"and", "but", "so", "because", "which", "who", "that", "to", "from", "for", "like", "when", "if", "then",
            "or", "while", "with", "before", "after"}


def _dur(ws: list[dict]) -> float:
    return ws[-1]["end"] - ws[0]["start"]


def beats(words: list[dict]) -> list[dict]:
    """Split the edited timeline into beats: clauses (sentence ends, commas, pauses), long clauses cut at a clause
    word (and, but, which, to...) near their middle, tiny pieces merged into a neighbour."""
    clauses, cur = [], []
    for k, w in enumerate(words):
        cur.append(w)
        nxt = words[k + 1] if k + 1 < len(words) else None
        if nxt is None or _END.search(w["text"]) or _SOFT.search(w["text"]) or nxt["start"] - w["end"] >= PAUSE_BREAK_S:
            clauses.append(cur)
            cur = []
    parts: list[list[dict]] = []
    queue = list(clauses)
    while queue:
        x = queue.pop(0)
        if _dur(x) <= MAX_BEAT_S or len(x) < 4:
            parts.append(x)
            continue
        mid = x[0]["start"] + _dur(x) / 2
        cands = [j for j in range(2, len(x) - 1) if re.sub(r"[^a-z']", "", x[j]["text"].lower()) in STARTERS] \
            or list(range(2, len(x) - 1))
        j = min(cands, key=lambda j: abs(x[j]["start"] - mid))
        queue[0:0] = [x[:j], x[j:]]
    merged: list[list[dict]] = []
    for part in parts:
        if merged and (_dur(part) < 0.9 or _dur(merged[-1]) < 0.9) and _dur(merged[-1] + part) <= MAX_BEAT_S:
            merged[-1] = merged[-1] + part
        else:
            merged.append(part)
    out = [{"id": f"b{k + 1}", "start": round(m[0]["start"], 3), "end": round(m[-1]["end"], 3),
            "text": " ".join(w["text"] for w in m), "first": m[0]["i"], "last": m[-1]["i"]} for k, m in enumerate(merged)]
    for a, b in zip(out, out[1:]):          # contiguous: each beat runs until the next begins
        a["end"] = b["start"]
    return out


REQUEST_TOKENS = 22000    # Jev rejects requests past its context; pack questions under this estimate


def options(lib) -> dict[str, str]:
    """Choice criteria: one short line per template (the longer 'fits' notes travel once, in the state)."""
    crit = {SPEAKER: "No graphic: the speaker talks full screen (personal or connecting lines; rests the eye)."}
    for t in lib.values():
        if t.meta.internal:
            continue
        crit[t.id] = f"{t.meta.name}: {t.meta.description}"[:220]
    crit[NEW] = "None of these fit well; this line deserves a custom graphic made for it."
    return crit


def catalog(lib) -> dict[str, str]:
    return {t.id: t.meta.use_when for t in lib.values() if not t.meta.internal}


def batch_size(questions: dict, state: dict) -> int:
    per_q = max(len(json.dumps(q)) for q in questions.values()) / 3.2 if questions else 1
    room = REQUEST_TOKENS - len(json.dumps(state)) / 3.2
    return max(1, int(room // per_q))


def direct(job: Job, asker: Asker | None = None, use_jev: bool | None = None) -> dict:
    from typesafe_sdk import TypeSafeError

    edit = EditFile.model_validate(job.read("edit.json"))
    analysis = Analysis.model_validate(job.read("analysis.json"))
    brief = load_brief(job)
    lib = load_library()
    if not lib:
        raise ShortsError("E_TEMPLATE", "The graphics library is empty.", "Add templates to kit/graphics.")
    bs = beats(word_timeline(edit, analysis, brief.caption_overrides))
    crit = options(lib)
    questions = {}
    for k, b in enumerate(bs):
        prev = bs[k - 1]["text"] if k else "(start of the video)"
        nxt = bs[k + 1]["text"] if k + 1 < len(bs) else "(end of the video)"
        questions[b["id"]] = {"type": "choice", "criteria": crit, "instructions": (
            f"A vertical short is being edited with motion graphics. Beat {b['id']} lasts {b['end'] - b['start']:.1f} s "
            f"and the speaker says: \"{b['text']}\". Just before: \"{prev}\". Just after: \"{nxt}\". "
            "Which visual should be on screen during this beat so it illustrates exactly what is said?")}
    state = {"topic": brief.topic or "not given", "script": [{"beat": b["id"], "text": b["text"]} for b in bs],
             "what each visual fits": catalog(lib)}
    if brief.visual_notes:
        state["what the camera shows (seconds of the edit)"] = [
            {"from": source_to_output(edit, n.start), "to": source_to_output(edit, n.end), "note": n.note}
            for n in brief.visual_notes]
        state["camera rule"] = ("While the speaker points at or shows something on camera, prefer 'speaker' or an "
                                "overlay so the viewer can still see it; full-screen graphics suit talking moments.")
    error, meta = None, {"model": None, "input_tokens": 0}
    answers = {}
    # Jev's graphics picks made 11 of 16 final scenes on the English take but 4 of 20 and 3 of 10 on the Hinglish
    # ones (2026-09-27): on Hinglish, Claude directs from the beats alone
    if use_jev is None:
        use_jev = analysis.language == "en" and (asker is not None or config.jev_enabled())
    skipped = None if use_jev else (
        "Jev not asked: no TYPESAFE_API_KEY (optional): direct from the beats" if analysis.language == "en" and asker is None
        and not config.jev_enabled() else f"Jev not asked: its picks were not useful for {analysis.language} takes")
    with job.timed("direct"):
        if use_jev:
            try:
                answers, meta = (asker or JevAsker(batch_size=batch_size(questions, state))).ask(state, questions)
            except TypeSafeError as e:
                error = f"{type(e).__name__}: {e}"
        draft, prev_pick, streak = [], None, 0
        for b in bs:
            if not use_jev:
                draft.append({**b, "pick": None, "confidence": 0.0, "alternatives": [], "params": {}, "duration": None})
                continue
            ans = answers.get(b["id"])
            ranked = sorted(ans.probabilities.items(), key=lambda kv: -kv[1]) if ans else [(SPEAKER, 0.0)]
            pick = ranked[0][0]
            # pacing: no template twice in a row; at most three full-screen graphics in a row (overlays keep
            # the speaker visible, so they don't count), then give the eye the speaker
            if pick == prev_pick and pick != SPEAKER:
                pick = next((k for k, _ in ranked[1:] if k != prev_pick), SPEAKER)
            hides_speaker = pick in lib and lib[pick].meta.kind != "overlay"
            streak = streak + 1 if hides_speaker else 0
            if streak > 3:
                pick = next((k for k, _ in ranked if k in lib and lib[k].meta.kind == "overlay" and k != prev_pick), SPEAKER)
                streak = 0
            prev_pick = pick
            tpl = lib.get(pick)
            draft.append({
                **b, "pick": pick, "confidence": round(dict(ranked).get(pick, 0.0), 3),
                "alternatives": [k for k, p in ranked[:4] if k != pick][:3],
                "params": {n: {"type": p.type, "required": p.required, "help": p.help, "max_len": p.max_len}
                           for n, p in tpl.meta.params.items()} if tpl else {},
                "duration": tpl.meta.duration.model_dump() if tpl else None,
            })
        job.write("visuals_draft.json", {"beats": draft, "model": meta["model"], "input_tokens": meta["input_tokens"],
                                         "jev_error": error, "jev_skipped": skipped})
    counts: dict[str, int] = {}
    for d in draft:
        if d["pick"]:
            counts[d["pick"]] = counts.get(d["pick"], 0) + 1
    return {"job": job.name, "beats": len(draft), "model": meta["model"], "input_tokens": meta["input_tokens"],
            "timing_s": job.read("timings.json").get("direct"), "jev_error": error, "picks": counts,
            "new_templates_wanted": [d["id"] for d in draft if d["pick"] == NEW],
            "jev_skipped": skipped,
            "plan": [f"{d['id']} {d['start']:5.1f}-{d['end']:5.1f}s {d['pick'] or '-':<18} {d['confidence']:.2f}  {d['text'][:60]}"
                     for d in draft],
            "next": f"Fill {job.dir / 'visuals.json'} from visuals_draft.json (words for each picked template), "
                    f"then: shorts preview {job.name}"}


def add_command(sub) -> None:
    p = sub.add_parser("direct", help="Split the edit into beats; for English takes Jev drafts a visual per beat.")
    p.add_argument("job")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--jev", dest="use_jev", action="store_true", default=None, help="ask Jev even for a non-English take")
    g.add_argument("--no-jev", dest="use_jev", action="store_false", help="beats only, no Jev picks")
    p.set_defaults(func=lambda a: direct(Job.open(a.job), use_jev=a.use_jev))
