"""`shorts gfx`: render every scene in visuals.json plus the caption track, all in parallel, cached by content."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import ValidationError

from shorts import config
from shorts.brief import load_brief, load_style
from shorts.errors import ShortsError
from shorts.gfx.library import Template, build_page, captions_mode, check_params, load_library, scene_key
from shorts.gfx.render import render_scenes
from shorts.gfx.speaker import cutout
from shorts.gfx.timeline import extract_window, segment_starts, source_ranges
from shorts.job import Job
from shorts.plan.captions import layout_captions
from shorts.plan.cuts import Seg
from shorts.schemas import Analysis, EditFile, Visuals

FPS_CHECK_TOL = 1e-3
CAPTION_CHUNK_S = 8.0


def load_visuals(job: Job) -> Visuals:
    try:
        return Visuals.model_validate(job.read("visuals.json"))
    except ValidationError as e:
        first = e.errors()[0]
        raise ShortsError("E_VISUALS_INVALID", f"visuals.json is invalid at {'.'.join(map(str, first['loc']))}: {first['msg']}",
                          "Fix visuals.json (see: shorts schema visuals).") from None


def validate_visuals(vis: Visuals, lib: dict[str, Template], duration: float) -> list[str]:
    problems, ids = [], set()
    for s in vis.scenes:
        if s.id in ids:
            problems.append(f"{s.id}: duplicate scene id")
        ids.add(s.id)
        tpl = lib.get(s.template)
        if tpl is None or tpl.meta.internal:
            problems.append(f"{s.id}: unknown template {s.template!r}")
            continue
        problems += [f"{s.id}: {p}" for p in check_params(tpl.meta, s.params)]
        if not (0 <= s.start < s.end <= duration + FPS_CHECK_TOL):
            problems.append(f"{s.id}: {s.start}-{s.end}s is outside the video (0-{duration:.2f}s)")
        length, d = s.end - s.start, tpl.meta.duration
        if length < d.min * 0.75 or length > d.max * 1.25:
            problems.append(f"{s.id}: {length:.2f}s is far outside {s.template}'s range {d.min}-{d.max}s")
    full = sorted((s for s in vis.scenes if s.template in lib and lib[s.template].meta.kind != "overlay"), key=lambda s: s.start)
    for a, b in zip(full, full[1:]):
        if b.start < a.end - FPS_CHECK_TOL:
            problems.append(f"{a.id} and {b.id} are both full-screen at {b.start:.2f}s")
    return problems


def _segs(edit: EditFile) -> tuple[list[Seg], list[float]]:
    fps = edit.output.fps
    return [Seg(s.first_word, s.last_word, s.in_frame / fps, s.out_frame / fps) for s in edit.segments], segment_starts(edit)


def caption_pages(job: Job, edit: EditFile, analysis: Analysis, vis: Visuals, lib: dict[str, Template]) -> tuple[list[dict], float]:
    """Box-style caption pages on the output timeline, dark over cream scenes and hidden where a scene shows the words."""
    brief, style = load_brief(job), load_style(job)
    box_style = style.model_copy(update={"font": "Oswald-700.ttf", "font_size": vis.caption_size, "words_per_page": 3,
                                         "uppercase": True, "outline_px": 0})
    segs, starts = _segs(edit)
    caps, _ = layout_captions(segs, starts, analysis.words, set(), brief.caption_overrides, box_style,
                              analysis.picture.face_box)

    def mode_at(t: float) -> str:
        over = [(lib[s.template].meta, captions_mode(lib[s.template].meta, s.params))
                for s in vis.scenes if s.start <= t < s.end and s.template in lib]
        if any(mode == "hide" for _, mode in over):
            return "hide"
        base = "dark" if any(mode == "dark" and m.kind != "overlay" for m, mode in over) else "show"
        ys = [m.caption_y for m, _ in over if m.kind != "overlay" and m.caption_y]
        return f"{base}@{ys[0]}" if ys else base

    edges = sorted({s.start for s in vis.scenes} | {s.end for s in vis.scenes})
    raw = [{"start": p.start, "end": p.end, "words": [{"text": w.text, "start": w.start, "end": w.end} for w in p.words]}
           for p in caps.pages]
    pages = split_by_mode(raw, mode_at, edges)
    # Graphics own the top and middle of the frame, so the caption track stays in the bottom band the plan chose
    # (face-avoiding placement would push it above the head, into the titles).
    lowest = (1 - config.SAFE_BOTTOM) * config.OUT_H - vis.caption_size * 0.65
    for p in pages:
        if "y" in p:                                   # a scene's own band (meta caption_y) stays out of the UI zone
            p["y"] = round(min(p["y"], lowest), 1)
    return pages, round(min(max(edit.captions.center_y, 0.55 * config.OUT_H), lowest), 1)


def split_by_mode(pages: list[dict], mode_at, edges: list[float]) -> list[dict]:
    """Split caption pages where the scene's caption mode changes, drop the words a scene hides, and keep every
    piece inside its own mode's time span (so a caption never lingers over the next scene)."""
    out = []
    for p in pages:
        groups: list[tuple[str, list[dict]]] = []
        for w in p["words"]:
            m = mode_at((w["start"] + w["end"]) / 2)
            if groups and groups[-1][0] == m:
                groups[-1][1].append(w)
            else:
                groups.append((m, [w]))
        for k, (m, ws) in enumerate(groups):
            if m == "hide":
                continue
            a = p["start"] if k == 0 else ws[0]["start"]
            b = p["end"] if k == len(groups) - 1 else groups[k + 1][1][0]["start"]
            a = max([a] + [e for e in edges if a < e <= ws[0]["start"] and mode_at(e - 1e-3) != m])
            b = min([b] + [e for e in edges if ws[-1]["start"] < e < b and mode_at(e + 1e-3) != m])
            mode, _, frac = m.partition("@")
            page = {"start": a, "end": b, "dark": mode == "dark", "words": ws}
            if frac:
                page["y"] = round(float(frac) * config.OUT_H, 1)
            out.append(page)
    return out


def caption_chunks(pages: list[dict], limit: float = CAPTION_CHUNK_S, fps: int | None = None) -> list[tuple[float, float, list[dict]]]:
    """Split the caption track into chunks (on page boundaries) so the chunks render in parallel.
    With fps, each chunk starts on a whole frame so its frames sample the page times exactly."""
    chunks, cur = [], []
    for p in pages:
        if cur and p["end"] - cur[0]["start"] > limit:
            chunks.append(cur)
            cur = []
        cur.append(p)
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        t0, t1 = c[0]["start"], c[-1]["end"]
        if fps:
            t0 = math.floor(t0 * fps + 1e-6) / fps
        rel = [{**p, "start": round(p["start"] - t0, 3), "end": round(p["end"] - t0, 3),
                "words": [{**w, "start": round(w["start"] - t0, 3), "end": round(w["end"] - t0, 3)} for w in p["words"]]}
               for p in c]
        out.append((t0, t1, rel))
    return out


CHUNK_FRAMES = 45        # ~1.5 s: small enough to balance 8 workers, big enough to amortise page start-up


def split_ranges(todo: list[dict], chunk: int = CHUNK_FRAMES) -> tuple[list[dict], dict[str, list[str]]]:
    """Split long scenes into frame ranges that render in parallel; returns the jobs and final -> part files."""
    jobs, parts_of = [], {}
    for s in todo:
        n = s["frames"]
        if n <= chunk * 1.5:
            jobs.append(s)
            continue
        parts = []
        for k, a in enumerate(range(0, n, chunk)):
            out = s["out"].replace(".mov", f".part{k:03d}.mov")
            jobs.append({**s, "id": f"{s['id']}#{k}", "from": a, "to": min(a + chunk, n), "out": out})
            parts.append(out)
        parts_of[s["out"]] = parts
    return jobs, parts_of


def join_parts(ffmpeg: str, parts_of: dict[str, list[str]]) -> None:
    """Concatenate frame-range parts back into one scene video (stream copy, lossless)."""
    for final, parts in parts_of.items():
        lst = Path(final).with_suffix(".txt")
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        run_cmd = [ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", final]
        proc = subprocess.run(run_cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ShortsError("E_GFX", f"Joining scene parts failed: {proc.stderr.strip()[-300:]}", "Run shorts gfx again.")
        lst.unlink()
        for p in parts:
            Path(p).unlink(missing_ok=True)


def _digest(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


CUT_REACH_S = 0.2


def snap_to_cuts(vis: Visuals, cuts: list[float], reach: float = CUT_REACH_S) -> Visuals:
    """Move scene edges onto a cut within `reach` s, so the jump in the footage happens exactly when the graphic
    changes (hidden) instead of a frame or two before it (a visible flash of the jumped shot)."""
    def near(t: float) -> float:
        best = min(cuts, key=lambda c: abs(c - t), default=None)
        return best if best is not None and abs(best - t) <= reach else t
    return vis.model_copy(update={"scenes": [s.model_copy(update={"start": near(s.start), "end": near(s.end)})
                                            for s in vis.scenes]})


def snap_to_frames(vis: Visuals, fps: int) -> Visuals:
    """Start and end every scene on a whole frame. The compositor holds a scene's last frame only until that
    frame's own timestamp, so a scene starting between frames dropped its last frame and one frame of raw
    footage flashed before the next scene (seen at 33.6 s and 37.6 s of video2)."""
    return vis.model_copy(update={"scenes": [s.model_copy(update={"start": round(s.start * fps) / fps,
                                                                 "end": round(s.end * fps) / fps})
                                            for s in vis.scenes]})


def render_gfx(job: Job, workers: int = 8) -> dict:
    """Render all scenes (cached) and write work/gfx/manifest.json for the compositor."""
    edit = EditFile.model_validate(job.read("edit.json"))
    analysis = Analysis.model_validate(job.read("analysis.json"))
    vis = load_visuals(job)
    lib = load_library()
    problems = validate_visuals(vis, lib, edit.duration)
    if problems:
        raise ShortsError("E_VISUALS_INVALID", "visuals.json has problems: " + "; ".join(problems[:6]),
                          "Fix the listed scenes in visuals.json, then run again.")
    ffmpeg, fps = config.tool("ffmpeg"), edit.output.fps
    vis = snap_to_frames(snap_to_cuts(vis, segment_starts(edit)[1:]), fps)
    gdir = job.work / "gfx"
    gdir.mkdir(parents=True, exist_ok=True)
    face = analysis.picture.face_box.model_dump() if analysis.picture.face_box else None
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    # 1. speaker footage for speaker scenes (extract, then cut out), in parallel
    speaker_scenes = [s for s in vis.scenes if lib[s.template].meta.kind == "speaker"]

    def frames_for(s):
        ranges = source_ranges(edit, s.start, s.end)
        cut = lib[s.template].meta.cutout
        sid = _digest(edit.source, ranges, cut)
        folder = gdir / "speaker" / sid
        done = folder / ("cut" if cut else "raw")
        if not done.exists() or not any(done.iterdir()):
            raw = extract_window(ffmpeg, edit.source, edit, s.start, s.end, folder / "raw")
            if cut:
                cutout(folder / "raw", folder / "cut")
        return s.id, sid, sorted(done.glob("f*.png" if cut else "f*.jpg"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        speaker = {sid_: (sid, frames) for sid_, sid, frames in pool.map(frames_for, speaker_scenes)}
    timings["speaker_frames"] = round(time.perf_counter() - t0, 2)

    # 2. pages for every scene + caption chunks; skip what is cached
    todo, manifest = [], []
    for s in vis.scenes:
        tpl = lib[s.template]
        sid, frames = speaker.get(s.id, ("", None))
        dur = s.end - s.start
        key = scene_key(tpl, s.params, dur, vis.theme, sid)
        mov = gdir / f"{s.id}-{key}.mov"
        if not mov.exists():
            html = build_page(tpl, s.params, dur, gdir / f"{s.id}-{key}.html", fps=fps, theme=vis.theme,
                              speaker_frames=frames, face=face)
            todo.append({"id": s.id, "html": str(html), "frames": int(round(dur * fps)), "fps": fps,
                         "alpha": tpl.meta.kind == "overlay", "out": str(mov)})
        manifest.append({"id": s.id, "template": s.template, "kind": tpl.meta.kind, "start": s.start, "end": s.end,
                         "mov": str(mov), "sfx": [{"at": c.at, "name": c.name, "gain_db": c.gain_db}
                                                  for c in tpl.meta.sfx if c.at < dur]})
    if vis.captions == "box":
        pages, y = caption_pages(job, edit, analysis, vis, lib)
        ctpl = lib["captions_box"]
        for k, (c0, c1, rel) in enumerate(caption_chunks(pages, fps=fps)):
            params = {"pages": rel, "y": y, "size": vis.caption_size}
            dur = c1 - c0
            key = scene_key(ctpl, params, dur, vis.theme)
            mov = gdir / f"cap{k}-{key}.mov"
            if not mov.exists():
                html = build_page(ctpl, params, dur, gdir / f"cap{k}-{key}.html", fps=fps, theme=vis.theme)
                todo.append({"id": f"cap{k}", "html": str(html), "frames": int(round(dur * fps)) + 1, "fps": fps,
                             "alpha": True, "out": str(mov)})
            manifest.append({"id": f"cap{k}", "template": "captions_box", "kind": "overlay", "start": c0, "end": c1,
                             "mov": str(mov), "sfx": []})

    # 3. render everything that is not cached, in parallel; long scenes are split into frame ranges
    t1 = time.perf_counter()
    jobs, parts_of = split_ranges(todo)
    result = render_scenes(jobs, workers, log=gdir / "render.log") if jobs else {"scenes": [], "ms": 0}
    timings["render"] = round(time.perf_counter() - t1, 2)
    failed = [r for r in result["scenes"] if r["errors"]]
    if not failed:
        join_parts(ffmpeg, parts_of)
    if failed:
        raise ShortsError("E_GFX", "Some scenes failed to render: " + "; ".join(f"{r['id']}: {r['errors'][0]}" for r in failed[:4]),
                          "Fix the scene params or template, then run again.")
    for html in gdir.glob("*.html"):
        html.unlink()
    # sound cues the templates emitted (they follow params and length) replace the fixed meta cues
    emitted = {}
    for r in result["scenes"]:
        sid, _, part = r["id"].partition("#")
        if (r.get("out") or {}).get("cues") and part in ("", "0"):
            emitted[sid] = r["out"]["cues"]
    for m in manifest:
        side = Path(m["mov"]).with_suffix(".cues.json")
        if m["id"] in emitted:
            side.write_text(json.dumps(emitted[m["id"]]))
        if side.exists():
            m["sfx"] = json.loads(side.read_text())
        dur = m["end"] - m["start"]
        m["sfx"] = [{**c, "at": round(m["start"] + c["at"], 3)} for c in m["sfx"] if 0 <= c["at"] < dur]
    info = {"visuals": _digest(job.read("visuals.json")), "edit": _digest(job.read("edit.json")),
            "captions": vis.captions, "scenes": manifest}
    job.write_work("gfx/manifest.json", info)
    captured = sum(r["captured"] for r in result["scenes"])
    frames = sum(r["frames"] for r in result["scenes"])
    timings["total"] = round(time.perf_counter() - t0, 2)
    return {"job": job.name, "scenes": len(vis.scenes), "caption_chunks": sum(1 for m in manifest if m["template"] == "captions_box"),
            "rendered": len(todo), "cached": len(manifest) - len(todo), "frames": frames, "captured": captured,
            "timing_s": timings, "next": f"shorts preview {job.name}"}


def gfx_manifest(job: Job) -> dict | None:
    """The rendered-scenes manifest if it matches the current visuals.json and edit.json."""
    if not (job.has("visuals.json") and (job.work / "gfx/manifest.json").exists()):
        return None
    m = job.read_work("gfx/manifest.json")
    if m.get("visuals") != _digest(job.read("visuals.json")) or m.get("edit") != _digest(job.read("edit.json")):
        return None
    if not all(Path(s["mov"]).exists() for s in m["scenes"]):
        return None
    return m


def add_command(sub) -> None:
    p = sub.add_parser("gfx", help="Render the graphics in visuals.json (parallel, cached).")
    p.add_argument("job")
    p.add_argument("--workers", type=int, default=8)
    p.set_defaults(func=lambda a: render_gfx(Job.open(a.job), a.workers))
