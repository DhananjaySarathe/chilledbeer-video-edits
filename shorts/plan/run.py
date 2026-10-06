"""`shorts plan`: turn decisions into edit.json (segments, zoom, captions), validated before rendering."""
from __future__ import annotations

from typing import Any

import numpy as np

from shorts.brief import load_brief, load_style
from shorts.errors import ShortsError
from shorts.job import Job
from shorts.plan.captions import layout_captions
from shorts import config
from shorts.plan.cuts import Seg, build_segments, runs, split_for_zoom, teaser_segment
from shorts.plan.validate import validate_edit
from shorts.plan.zoom import assign_zoom
from shorts.schemas import Analysis, AudioSpec, Decisions, EditFile, OutputSpec, Segment


def resolve(decisions: Decisions, resolutions: dict) -> tuple[dict[str, Any], list[str]]:
    """Final value of every decision: Claude's resolution when given, otherwise the routed value."""
    items = {d.id: d for d in decisions.items}
    unknown = sorted(set(resolutions) - items.keys())
    if unknown:
        raise ShortsError("E_RESOLUTION", f"resolutions.json has unknown ids: {unknown}",
                          "Use the ids listed under 'pending' by `shorts decide`.")
    values: dict[str, Any] = {}
    for d in decisions.items:
        v = resolutions.get(d.id, d.effective)
        if d.kind == "noul":
            ok = isinstance(v, bool)
        elif d.group == "duplicate_take":
            ok = v in d.subject["takes"]
        else:
            ok = isinstance(v, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in v)
        if not ok:
            raise ShortsError("E_RESOLUTION", f"{d.id} = {v!r} is not a valid answer.",
                              "Nouls take true or false; duplicate takes take one of the listed sentence ids; "
                              "highlights take a list of word indices.")
        values[d.id] = v
    return values, [p for p in decisions.pending if p not in resolutions]


def edit_choices(decisions: Decisions, values: dict[str, Any], analysis: Analysis):
    """(removed word indices, deliberate pauses (index of the word before), punch-in sentence ids, highlighted words)."""
    by_sid = {s.id: s for s in analysis.sentences}
    removed, deliberate, punch, highlights = set(decisions.auto_fillers), set(), set(), set()
    dropped, winners = set(), set()
    for d in decisions.items:
        v = values[d.id]
        if d.group == "false_start" and v:
            dropped.add(d.subject["sentence"])
        elif d.group == "duplicate_take":
            winners.add(v)
            dropped |= set(d.subject["takes"]) - {v}
        elif d.group == "filler_word" and v:
            removed.add(d.subject["word"])
        elif d.group == "deliberate_pause" and v:
            deliberate.add(d.subject["pause_after"])
        elif d.group == "punch_in" and v:
            punch.add(d.subject["sentence"])
    for sid in dropped - winners:
        s = by_sid[sid]
        removed |= set(range(s.first, s.last + 1))
    return removed, deliberate, punch, highlights


def plan(job: Job) -> dict:
    analysis = Analysis.model_validate(job.read("analysis.json"))
    brief, style = load_brief(job), load_style(job)
    decisions = Decisions.model_validate(job.read("decisions.json"))
    words, src = analysis.words, analysis.source
    bad = sorted(i for i in brief.caption_overrides if not 0 <= i < len(words))
    if bad:
        raise ShortsError("E_BRIEF_INVALID", f"caption_overrides uses word indices that do not exist: {bad}",
                          f"Word indices run from 0 to {len(words) - 1} (see analysis.json).")
    bad_cuts = [list(c) for c in brief.cut_words if not 0 <= c[0] <= c[1] < len(words)]
    if bad_cuts:
        raise ShortsError("E_BRIEF_INVALID", f"cut_words has ranges outside the transcript: {bad_cuts}",
                          f"Use inclusive [first, last] word indices from 0 to {len(words) - 1} (see analysis.json).")
    resolutions = job.read("resolutions.json") if job.has("resolutions.json") else {}
    with job.timed("plan"):
        values, unresolved = resolve(decisions, resolutions)
        removed, deliberate, punch, highlights = edit_choices(decisions, values, analysis)
        removed |= {i for a, b in brief.cut_words for i in range(a, b + 1)}
        energy = np.load(job.work / "energy.npy")
        cut = build_segments(words, removed, deliberate, energy, analysis.dip_db, src.duration, style.pace)
        segs, frames, prev_out = [], [], 0
        for s in split_for_zoom(cut.segments, words, every=config.PACES[style.pace][4]):   # whole frames, no overlap
            fi = max(int(round(s.t_in * src.fps)), prev_out)
            fo = min(max(int(round(s.t_out * src.fps)), fi + 1), src.frames)
            if fo <= fi:
                continue
            segs.append(Seg(s.first, s.last, fi / src.fps, fo / src.fps))
            frames.append((fi, fo))
            prev_out = fo
        n_open = 0
        if brief.cold_open:                               # flash-forward: the teaser line plays before the story
            a, b = brief.cold_open
            t = teaser_segment(words, a, b, energy, analysis.dip_db, src.duration) if 0 <= a <= b < len(words) else None
            if t is None:
                cut.warnings.append(f"cold_open {list(brief.cold_open)} skipped: no clean cut around those words")
            else:
                fi, fo = int(round(t.t_in * src.fps)), min(int(round(t.t_out * src.fps)), src.frames)
                segs.insert(0, Seg(t.first, t.last, fi / src.fps, fo / src.fps))
                frames.insert(0, (fi, fo))
                n_open = 1
        zooms = assign_zoom(segs, analysis.sentences, punch, analysis.picture.face_track, analysis.picture.fps,
                            style.zoom_jump, style.zoom_punch)
        out_starts, t = [], 0.0
        for fi, fo in frames:
            out_starts.append(t)
            t += (fo - fi) / src.fps
        captions, cap_warnings = layout_captions(segs, out_starts, words, highlights, brief.caption_overrides,
                                                 style, analysis.picture.face_box,
                                                 zoom=max((z for z, _ in zooms), default=1.0))
        duration = round(sum(fo - fi for fi, fo in frames) / src.fps, 6)
        warnings = cut.warnings + cap_warnings
        if unresolved:
            warnings.append(f"{len(unresolved)} pending decisions used safe defaults: {unresolved}")
        if not brief.target.min <= duration <= brief.target.max:
            warnings.append(f"length {duration:.1f}s is outside the target {brief.target.min:g}-{brief.target.max:g}s "
                            "(M2 only reports this; trimming to a target comes in M3)")
        edit = EditFile(
            source=src.working_path, source_frames=src.frames,
            output=OutputSpec(fps=src.fps, grade=style.grade, speed=style.speed), cold_open=n_open,
            segments=[Segment(in_frame=fi, out_frame=fo, first_word=s.first, last_word=s.last, zoom=z, crop=crop,
                              text=" ".join(w.text for w in words[s.first:s.last + 1]))
                      for (fi, fo), s, (z, crop) in zip(frames, segs, zooms)],
            captions=captions, audio=AudioSpec(source_integrated=analysis.loudness.integrated, clean=style.voice_clean),
            duration=duration, warnings=warnings)
        problems = validate_edit(edit)
        if problems:
            job.write_work("edit_problems.json", {"problems": problems, "edit": edit.model_dump()})
            raise ShortsError("E_EDIT_INVALID", "The planned edit is invalid: " + "; ".join(problems[:5]),
                              f"This is a planner bug; details in {job.work / 'edit_problems.json'}.")
        job.write("edit.json", edit.model_dump())
    kept = {i for s in segs for i in range(s.first, s.last + 1)}
    gone = [i for i in range(len(words)) if i not in kept]
    return {
        "job": job.name, "duration": duration, "source_duration": src.duration, "segments": len(segs),
        "speed": style.speed, "plays_for": round(duration / style.speed, 2), "cold_open": n_open,
        "removed": [f"'{' '.join(w.text for w in words[a:b + 1])}' at {words[a].start:.2f}s" for a, b in runs(gone)],
        "kept_back": [f"{words[i].text}@{words[i].start:.2f}s" for i in cut.kept_back],
        "punch_ins": sorted(punch), "highlights": [words[i].text for i in sorted(highlights) if i in kept],
        "caption_pages": len(captions.pages), "warnings": warnings,
        "timing_s": job.read("timings.json").get("plan"), "next": f"shorts preview {job.name}",
    }


def add_command(sub) -> None:
    p = sub.add_parser("plan", help="Turn decisions (and resolutions.json) into a validated edit.json.")
    p.add_argument("job")
    p.set_defaults(func=lambda a: plan(Job.open(a.job)))
