"""`shorts preview` and `shorts render`: draw the edit with ffmpeg."""
from __future__ import annotations

import shutil
from pathlib import Path

from shorts import config, fonts
from shorts.analyze.contact import contact_sheet, fmt_tc, grab_frames, save_png
from shorts.errors import ShortsError
from shorts.job import Job
from shorts.plan.validate import validate_edit
from shorts.proc import run
from shorts.render.ass import build_ass
from shorts.render.graph import build_cmd, build_measure_cmd, parse_loudnorm
from shorts.schemas import Analysis, EditFile


def _prepare(job: Job) -> EditFile:
    """Validate edit.json, check the source exists, copy the caption font next to it and write captions.ass."""
    edit = EditFile.model_validate(job.read("edit.json"))
    if not Path(edit.source).is_file():
        raise ShortsError("E_NO_INPUT", f"The source video {edit.source} is missing.",
                          f"Restore the file, or start again with: shorts probe <video> --job {job.name}")
    problems = validate_edit(edit)
    if problems:
        raise ShortsError("E_EDIT_INVALID", "edit.json is invalid: " + "; ".join(problems[:5]),
                          f"Re-run: shorts plan {job.name}")
    font = fonts.font_path(edit.captions.font)
    (job.work / "fonts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(font, job.work / "fonts" / font.name)
    (job.work / "captions.ass").write_text(build_ass(edit.captions, fonts.full_name(font)), encoding="utf-8")
    return edit


def cut_list(edit: EditFile, analysis: Analysis) -> list[str]:
    """Each cut on the output timeline and what it removed."""
    out, t, fps = [], 0.0, edit.output.fps
    for a, b in zip(edit.segments, edit.segments[1:]):
        t += (a.out_frame - a.in_frame) / fps
        gone = " ".join(w.text for w in analysis.words[a.last_word + 1: b.first_word])
        out.append(f"{fmt_tc(t)} cut {(b.in_frame - a.out_frame) / fps:.2f}s" + (f" ('{gone}')" if gone else " (pause)"))
    return out


def _graphics(job: Job) -> dict:
    """Overlay scenes, sound cues and caption mode for this job (renders visuals.json first if needed)."""
    if not job.has("visuals.json"):
        return {"overlays": None, "sfx": None, "sfx_files": None, "subtitles": True, "gfx": None, "music": None}
    from shorts.gfx.scenes import gfx_manifest, render_gfx
    from shorts.gfx.sfx import ensure_sfx

    m = gfx_manifest(job)
    gfx = None
    if m is None:
        gfx = render_gfx(job)
        m = gfx_manifest(job)
    order = {"fullscreen": 0, "speaker": 0, "overlay": 1}
    overlays = sorted(m["scenes"], key=lambda s: (2 if s["template"] == "captions_box" else order[s["kind"]], s["start"]))
    cues = [c for s in m["scenes"] for c in s["sfx"]]
    return {"overlays": overlays, "sfx": cues or None, "sfx_files": ensure_sfx() if cues else None,
            "subtitles": m["captions"] != "box", "gfx": gfx, "music": _music(job)}


def _music(job: Job) -> dict | None:
    """visuals.music with its gain worked out: the track's loudness sits level_db under the voice."""
    from shorts.gfx.scenes import load_visuals

    mu = load_visuals(job).music
    if mu is None:
        return None
    src = Path(mu.file).expanduser()
    if not src.is_absolute():
        src = job.dir / src
    if not src.is_file():
        raise ShortsError("E_NO_MUSIC", f"The music file {src} is missing.", "Fix visuals.music.file (a full path works best).")
    st = src.stat()
    key = f"{src}|{st.st_size}|{st.st_mtime_ns}"
    cache = job.work / "music_loudness.json"
    known = job.read_work("music_loudness.json") if cache.exists() else {}
    if known.get("key") != key:
        out = run([config.tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(src), "-vn",
                   "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                  code="E_MUSIC", what="Measuring the music", log=job.work / "music.log")
        known = {"key": key, "input_i": float(parse_loudnorm(out.stderr)["input_i"])}
        job.write_work("music_loudness.json", known)
    edit = EditFile.model_validate(job.read("edit.json"))
    voice = edit.audio.source_integrated if edit.audio.source_integrated is not None else -20.0
    gain = max(-40.0, min(20.0, voice + mu.level_db - known["input_i"]))
    return {"file": str(src), "gain_db": gain, "duck_db": mu.duck_db, "start": mu.start,
            "fade_in": mu.fade_in, "fade_out": mu.fade_out, "enter": mu.enter, "drops": [list(d) for d in mu.drops]}


def _encode(job: Job, edit: EditFile, ffmpeg: str, out: Path, mode: str, measured: dict | None = None,
            g: dict | None = None) -> str:
    """Render with VideoToolbox decoding; if that fails to open or decode, render again with software decoding.
    ffmpeg runs in the job's temp folder, where captions.ass and fonts/ are (the subtitles filter takes relative paths)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    log, out = job.work / f"{out.stem}.log", str(out)
    extra = {k: g[k] for k in ("overlays", "sfx", "sfx_files", "subtitles", "music")} if g else {}
    try:
        run(build_cmd(ffmpeg, edit, out, mode, measured, **extra), code="E_RENDER", what=f"Rendering {out}",
            cwd=job.work, log=log)
        return "videotoolbox"
    except ShortsError:
        run(build_cmd(ffmpeg, edit, out, mode, measured, hw=False, **extra), code="E_RENDER", what=f"Rendering {out}",
            cwd=job.work, log=log)
        return "software"


def preview(job: Job) -> dict:
    edit = _prepare(job)
    ffmpeg = config.tool("ffmpeg")
    with job.timed("preview"):
        g = _graphics(job)
        decode = _encode(job, edit, ffmpeg, job.preview, "preview", g=g)
    strip = job.work / "preview_strip.png"
    frames = grab_frames(ffmpeg, str(job.preview), edit.duration / edit.output.speed, 8, (135, 240))
    save_png(contact_sheet(frames, cols=8, thumb=(135, 240)), strip)
    return {"job": job.name, "preview": str(job.preview), "strip": str(strip),
            "duration": edit.duration, "timing_s": job.read("timings.json")["preview"], "decode": decode,
            "graphics": g["gfx"] or ("cached" if g["overlays"] else None),
            "cuts": cut_list(edit, Analysis.model_validate(job.read("analysis.json"))), "warnings": edit.warnings,
            "next": f"Show preview.mp4 to the user. After notes: edit brief/style/resolutions, re-run plan and "
                    f"preview. When they approve: shorts render {job.name}"}


def render(job: Job, max_quality: bool = False) -> dict:
    edit = _prepare(job)
    ffmpeg = config.tool("ffmpeg")
    with job.timed("render"):
        g = _graphics(job)
        measured = parse_loudnorm(run(build_measure_cmd(ffmpeg, edit, g["sfx"], g["sfx_files"], g.get("music")), code="E_LOUDNESS",
                                      what="Measuring loudness", cwd=job.work, log=job.work / "measure.log").stderr)
        decode = _encode(job, edit, ffmpeg, job.final, "max" if max_quality else "final", measured, g)
    return {"job": job.name, "final": str(job.final), "duration": edit.duration,
            "timing_s": job.read("timings.json")["render"], "decode": decode, "loudness_before": measured,
            "next": f"shorts check {job.name}"}


def add_command(sub) -> None:
    p = sub.add_parser("preview", help="Fast half-resolution preview with captions.")
    p.add_argument("job")
    p.set_defaults(func=lambda a: preview(Job.open(a.job)))
    r = sub.add_parser("render", help="Final 1080x1920 render with two-pass loudness normalisation.")
    r.add_argument("job")
    r.add_argument("--max-quality", action="store_true", help="libx264 slow CRF 18 instead of VideoToolbox (slower)")
    r.set_defaults(func=lambda a: render(Job.open(a.job), a.max_quality))
