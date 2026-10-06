"""`shorts probe`: create a job from a video and make the footage safe to edit."""
from __future__ import annotations

import re
from pathlib import Path

from shorts import config
from shorts.errors import ShortsError
from shorts.job import Job
from shorts.media.normalize import normalize_cmd, plan_normalization
from shorts.media.probe import probe_media
from shorts.proc import run


def slugify(stem: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:48] or "job"
    return s if s[0].isalnum() else "j" + s


def probe(input_path: str, job_name: str | None, landscape: bool = False) -> dict:
    src = Path(input_path).expanduser().resolve()
    if not src.is_file():
        raise ShortsError("E_NO_INPUT", f"{src} does not exist.", "Pass the full path to the video file.")
    job = Job.create(job_name or slugify(src.stem))
    ffmpeg, ffprobe = config.tool("ffmpeg"), config.tool("ffprobe")
    with job.timed("probe"):
        info = probe_media(ffprobe, str(src))
        plan = plan_normalization(info, landscape)
        if plan.needed:
            working = job.source
            try:
                run(normalize_cmd(ffmpeg, info, plan, str(working)), code="E_NORMALIZE",
                    what="Normalising the clip", log=job.work / "normalize.log")
            except ShortsError:              # a codec the media engine can't decode: software decoding
                run(normalize_cmd(ffmpeg, info, plan, str(working), hw=False), code="E_NORMALIZE",
                    what="Normalising the clip", log=job.work / "normalize.log")
            winfo = probe_media(ffprobe, str(working))
        else:
            working, winfo = src, info
        job.write("probe.json", {"input": str(src), "info": info.to_dict(), "plan": plan.to_dict(),
                                 "working_path": str(working), "working": winfo.to_dict()})
    w, h = winfo.display_size
    return {"job": job.name, "working_path": str(working), "normalized": plan.needed, "reasons": plan.reasons,
            "duration": round(winfo.duration, 3), "fps": plan.target_fps, "size": f"{w}x{h}",
            "next": f"shorts analyze {job.name}"}


def add_command(sub) -> None:
    p = sub.add_parser("probe", help="Create a job from a video and make the footage safe to edit.")
    p.add_argument("input")
    p.add_argument("--job", help="job name (default: from the file name)")
    p.add_argument("--landscape", action="store_true", help="a 16:9 take for a long-form edit (kept at 1920x1080)")
    p.set_defaults(func=lambda a: probe(a.input, a.job, a.landscape))
