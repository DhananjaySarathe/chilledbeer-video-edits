"""`shorts decide`: build the editing questions; Jev answers the zoom-in ones, Claude answers the rest.

Measured over three videos (2026-09-27): on cut questions (false starts, fillers, pauses, duplicate takes) Jev was
confident enough to act on 8 of 102 and removed nothing itself, so those go straight to Claude. Its highlight-word
answers were never used (box captions ignore them), so that question is gone. Zoom-in (punch-in) picks were
applied as-is and landed well, so Jev keeps that job.
"""
from __future__ import annotations

from collections import Counter

from shorts import config
from shorts.brief import load_brief
from shorts.decide.jev import Asker, JevAsker
from shorts.decide.questions import build, load_templates
from shorts.decide.router import route
from shorts.job import Job
from shorts.schemas import Analysis, Decision, Decisions


JEV_GROUPS = {"punch_in"}


def describe(d: Decision) -> dict:
    """What Claude needs to resolve one pending decision."""
    out = {"id": d.id, "question": d.question, "safe_default": d.effective,
           "answer_with": ("one of: " + ", ".join(d.subject["takes"])) if d.group == "duplicate_take" else "true or false"}
    if d.value is not None:
        out.update(jev_answer=d.value, jev_confidence=d.confidence)
    return out


def decide(job: Job, asker: Asker | None = None) -> dict:
    from typesafe_sdk import TypeSafeError

    analysis = Analysis.model_validate(job.read("analysis.json"))
    state, specs, auto = build(analysis, load_brief(job), load_templates())
    answers, meta, error = {}, {"model": None, "input_tokens": 0}, None
    use_jev = asker is not None or config.jev_enabled()
    for_jev = [s for s in specs if s.group in JEV_GROUPS] if use_jev else []
    with job.timed("decide"):
        if for_jev:
            try:
                answers, meta = (asker or JevAsker()).ask(state, {s.id: s.payload for s in for_jev})
            except TypeSafeError as e:          # no key, no network, API down: Claude and safe defaults take over
                error = f"{type(e).__name__}: {e}"
        items = []
        for s in specs:
            ans = answers.get(s.id)
            r, effective = route(s, ans)
            if not use_jev and s.group in JEV_GROUPS:
                r = "claude"                    # no Jev: Claude picks the zoom-ins, like the cut questions
            items.append(Decision(
                id=s.id, group=s.group, question=s.payload["instructions"], subject=s.subject, kind=s.kind,
                value=None if ans is None else ans.value,
                confidence=None if ans is None else round(ans.confidence, 4),
                probabilities={} if ans is None else {k: round(v, 4) for k, v in ans.probabilities.items()},
                route=r, effective=effective))
        decisions = Decisions(model=meta["model"], input_tokens=meta["input_tokens"], auto_fillers=auto, items=items,
                              pending=[d.id for d in items if d.route == "claude"], jev_error=error)
        job.write("decisions.json", decisions.model_dump())
    routes = Counter(d.route for d in items)
    pending = [describe(d) for d in items if d.route == "claude"]
    return {
        "job": job.name, "questions": len(items), "asked_jev": len(for_jev), "model": meta["model"],
        "input_tokens": meta["input_tokens"],
        "timing_s": job.read("timings.json").get("decide"), "applied": routes["apply"], "defaults": routes["default"],
        "auto_fillers": [f"{analysis.words[i].text}@{analysis.words[i].start:.2f}s" for i in auto],
        "jev": "on" if use_jev else "off (no TYPESAFE_API_KEY): the zoom-in questions are in pending",
        "jev_error": error, "pending": pending,
        "next": (f"Answer each pending item in {job.dir / 'resolutions.json'} as {{id: value}}, then: shorts plan {job.name}"
                 if pending else f"shorts plan {job.name}"),
    }


def add_command(sub) -> None:
    p = sub.add_parser("decide", help="Build the editing questions: Jev picks zoom-ins, Claude answers the cut questions.")
    p.add_argument("job")
    p.set_defaults(func=lambda a: decide(Job.open(a.job)))
