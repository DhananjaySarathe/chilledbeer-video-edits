"""`shorts library`: list, check and preview the graphics templates (all previews render in parallel)."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from shorts import config
from shorts.analyze.contact import contact_sheet, save_png
from shorts.errors import ShortsError
from shorts.gfx.library import GRAPHICS, Template, build_page, check_params, load_library
from shorts.gfx.render import render_scenes
from shorts.gfx.speaker import cutout, extract_frames

PREVIEWS = GRAPHICS / "_previews"     # the preview strips (tracked: Claude reads them when choosing templates)
FPS = 30


def _work() -> Path:
    """Preview videos, page builds, logs and sample frames: output/temp/cache/graphics (safe to delete)."""
    return config.CACHE / "graphics"


def sample_footage() -> Path | None:
    """A talking-head clip to preview speaker templates with: the first job's working video, if any."""
    for probe in sorted(config.JOBS.glob("*/probe.json")) + sorted(config.LEGACY_JOBS.glob("*/probe.json")):
        p = Path(json.loads(probe.read_text())["working_path"])
        if p.exists():
            return p
    return None


def sample_frames(seconds: float, want_cutout: bool) -> list[Path]:
    """Cached speaker frames for previews (real footage if a job exists, else a grey stand-in)."""
    raw = _work() / "sample" / "frames"
    if not raw.exists() or len(list(raw.glob("f*.jpg"))) < int(seconds * FPS):
        src = sample_footage()
        if src is not None:
            extract_frames(config.tool("ffmpeg"), str(src), 20.0, max(seconds, 10.0), raw, FPS)
        else:
            raw.mkdir(parents=True, exist_ok=True)
            img = np.full((1280, 720, 3), 120, np.uint8)
            import cv2
            cv2.circle(img, (360, 470), 150, (200, 200, 200), -1)
            cv2.ellipse(img, (360, 1100), (330, 360), 0, 180, 360, (200, 200, 200), -1)
            for k in range(int(max(seconds, 10.0) * FPS)):
                cv2.imwrite(str(raw / f"f{k + 1:04d}.jpg"), img)
    frames = sorted(raw.glob("f*.jpg"))[: int(round(seconds * FPS)) + 2]
    if not want_cutout:
        return frames
    cut = _work() / "sample" / "cutout"
    if not cut.exists() or len(list(cut.glob("f*.png"))) < len(frames):
        cutout(raw, cut)
    return sorted(cut.glob("f*.png"))[: len(frames)]


def _background_video(seconds: float, out: Path) -> Path:
    """The speaker clip overlays are previewed on."""
    src = sample_footage()
    ff = config.tool("ffmpeg")
    if src is not None:
        cmd = [ff, "-v", "error", "-y", "-ss", "20", "-i", str(src), "-t", f"{seconds:.3f}", "-an",
               "-vf", "fps=30,scale=1080:1920", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", str(out)]
    else:
        cmd = [ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x6f7a80:s=1080x1920:r=30:d={seconds:.3f}",
               "-c:v", "libx264", "-preset", "ultrafast", str(out)]
    subprocess.run(cmd, check=True)
    return out


def _finish_preview(tpl: Template, mov: Path, seconds: float) -> tuple[Path, Path]:
    """preview.mp4 (overlays composited on footage) and a 4-frame strip PNG.

    The tracked strip in kit/graphics/_previews is only replaced when it was drawn over real footage (or is new):
    on a machine with no takes yet the stand-in grey background would overwrite the good strips.
    """
    ff = config.tool("ffmpeg")
    real = sample_footage() is not None
    tracked = PREVIEWS / f"{tpl.id}.png"
    mp4 = _work() / f"{tpl.id}.mp4"
    strip = tracked if real or not tracked.exists() else _work() / f"{tpl.id}.png"
    if tpl.meta.kind == "overlay":
        bg = _background_video(seconds, _work() / f".{tpl.id}_bg.mp4")
        cmd = [ff, "-v", "error", "-y", "-i", str(bg), "-i", str(mov), "-filter_complex", "[0:v][1:v]overlay=format=auto",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(mp4)]
    else:
        cmd = [ff, "-v", "error", "-y", "-i", str(mov), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", str(mp4)]
    subprocess.run(cmd, check=True)
    frames = []
    for frac in (0.2, 0.45, 0.7, 0.92):
        t = seconds * frac
        raw = subprocess.run([ff, "-v", "error", "-ss", f"{t:.3f}", "-i", str(mp4), "-frames:v", "1", "-vf", "scale=270:480",
                              "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"], capture_output=True).stdout
        if len(raw) == 270 * 480 * 3:
            frames.append((t, np.frombuffer(raw, np.uint8).reshape(480, 270, 3)))
    save_png(contact_sheet(frames, cols=4, thumb=(270, 480)), strip)
    (_work() / f".{tpl.id}_bg.mp4").unlink(missing_ok=True)
    return mp4, strip


def check(ids: list[str] | None = None, workers: int = 8) -> dict:
    """Render every template's example in parallel and report errors, clipped text and speed."""
    skipped: dict[str, str] = {}
    lib = load_library(skipped=skipped)
    broken = {i: skipped[i] for i in (ids or skipped) if i in skipped}
    if ids and broken:
        raise ShortsError("E_TEMPLATE", "; ".join(broken.values()), "Fix the template files listed.")
    unknown = sorted(set(ids or []) - set(lib))
    if unknown:
        raise ShortsError("E_TEMPLATE", f"No such templates: {unknown}", "See: shorts library")
    todo = [lib[i] for i in ids] if ids else list(lib.values())
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    work = _work()
    work.mkdir(parents=True, exist_ok=True)
    scenes, problems = [], {}
    for tpl in todo:
        params = tpl.example
        problems[tpl.id] = check_params(tpl.meta, params)
        seconds = tpl.meta.duration.default
        frames = sample_frames(seconds, tpl.meta.cutout) if tpl.meta.kind == "speaker" else None
        html = build_page(tpl, params, seconds, work / f".{tpl.id}.html", fps=FPS, speaker_frames=frames)
        scenes.append({"id": tpl.id, "html": str(html), "frames": int(round(seconds * FPS)), "fps": FPS,
                       "alpha": tpl.meta.kind == "overlay", "out": str(work / f".{tpl.id}.mov"),
                       "check_at": round(seconds * 700)})
    t0 = time.perf_counter()
    result = render_scenes(scenes, workers, log=work / "_render.log")
    render_s = time.perf_counter() - t0
    report = []
    for r in sorted(result["scenes"], key=lambda r: r["id"]):
        tpl = lib[r["id"]]
        issues = problems[r["id"]] + [f"JS: {e}" for e in r["errors"]]
        issues += [f"text {'clipped' if o['clipped'] else 'off-frame'}: '{o['text']}' {o['rect']}" for o in r["overflow"]]
        strip = None
        if not r["errors"]:
            _, strip = _finish_preview(tpl, work / f".{tpl.id}.mov", tpl.meta.duration.default)
        report.append({"id": r["id"], "ok": not issues, "issues": issues, "frames": r["frames"],
                       "captured": r["captured"], "ms": r["ms"], "preview": str(strip) if strip else None})
    for tpl in todo:                      # only our own temp files: other checks may be running in parallel
        for tmp in work.glob(f".{tpl.id}.*"):
            tmp.unlink(missing_ok=True)
    return {"passed": all(x["ok"] for x in report) and not broken, "templates": len(report),
            "render_s": round(render_s, 2), "skipped": broken, "results": report}


def list_templates() -> dict:
    return {"templates": [{"id": t.id, "kind": t.meta.kind, "category": t.meta.category, "description": t.meta.description}
                          for t in load_library().values()]}


def sheet(out: Path | None = None) -> dict:
    """Stack every template's preview strip into one image for review."""
    strips = [(tid, PREVIEWS / f"{tid}.png") for tid in load_library()]
    import cv2
    rows = []
    for tid, p in strips:
        if not p.exists():
            continue
        img = cv2.imread(str(p))
        bar = np.full((44, img.shape[1], 3), 20, np.uint8)
        cv2.putText(bar, tid, (12, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        rows.append(np.vstack([bar, img]))
    if not rows:
        raise ShortsError("E_TEMPLATE", "No previews yet.", "Run: shorts library check")
    out = out or _work() / "_sheet.png"
    save_png(np.vstack(rows), out)
    return {"sheet": str(out), "templates": len(rows)}


def add_command(sub) -> None:
    p = sub.add_parser("library", help="List, check and preview graphics templates.")
    p.add_argument("action", nargs="?", default="list", choices=["list", "check", "sheet"])
    p.add_argument("ids", nargs="*", help="template ids (default: all)")
    p.add_argument("--workers", type=int, default=8)
    p.set_defaults(func=_dispatch)


def _dispatch(a) -> dict:
    if a.action == "check":
        return check(a.ids or None, a.workers)
    if a.action == "sheet":
        return sheet()
    return list_templates()
