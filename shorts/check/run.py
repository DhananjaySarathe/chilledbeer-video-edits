"""`shorts check`: verify the final file (format, loudness, black or frozen picture) before delivery."""
from __future__ import annotations

import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from shorts import config
from shorts.analyze.audio import measure_loudness
from shorts.analyze.contact import contact_sheet, grab_frames, save_png
from shorts.errors import ShortsError
from shorts.job import Job
from shorts.media.probe import probe_media
from shorts.schemas import EditFile

BLACK_RE = re.compile(r"black_start:\s*([\d.]+)")
FREEZE_RE = re.compile(r"freeze_start:\s*([\d.]+)")


def parse_detect(stderr: str) -> tuple[list[float], list[float]]:
    return [float(x) for x in BLACK_RE.findall(stderr)], [float(x) for x in FREEZE_RE.findall(stderr)]


def _detect(ffmpeg: str, path: str) -> tuple[list[float], list[float]]:
    # Software decoding: for one sequential pass it ran 2.6x faster here than VideoToolbox with copy-back.
    proc = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", path, "-an",
                           "-vf", "scale=270:480:flags=fast_bilinear,"             # detection needs no full res
                           "blackdetect=d=0.25:pix_th=0.10,freezedetect=n=0.0003:d=1.5", "-f", "null", "-"],
                          capture_output=True, text=True)
    return parse_detect(proc.stderr)


def check(job: Job) -> dict:
    edit = EditFile.model_validate(job.read("edit.json"))
    final, sheet = job.final, job.final_dir / "final_contact.png"
    if not final.exists():
        raise ShortsError("E_MISSING_FILE", f"{final} not found.", f"Run: shorts render {job.name}")
    ffmpeg, ffprobe = config.tool("ffmpeg"), config.tool("ffprobe")
    checks: list[dict] = []

    def add(name: str, ok, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    with job.timed("check"):
        info = probe_media(ffprobe, str(final))
        fps, (w, h) = edit.output.fps, info.display_size
        add("size", (w, h) == (edit.output.width, edit.output.height), f"{w}x{h}")
        add("frame_rate", abs(info.fps - fps) < 0.01 and not info.is_vfr, f"{info.fps:.3f} fps (planned {fps})")
        sp = edit.output.speed
        planned = round(sum(s.out_frame - s.in_frame for s in edit.segments) / sp)
        slack = 1 if sp == 1 else 2                   # a sped-up picture can gain or lose a frame at the end
        if info.nb_frames:
            add("duration", abs(info.nb_frames - planned) <= slack, f"{info.nb_frames} frames (planned {planned})")
        else:
            add("duration", abs(info.duration - edit.duration / sp) <= (slack + 0.5) / fps,
                f"{info.duration:.3f}s (planned {edit.duration / sp:.3f}s)")
        add("audio", info.has_audio and info.sample_rate == 48000 and info.channels == 2,
            f"{info.sample_rate} Hz, {info.channels} channels")
        with ThreadPoolExecutor(max_workers=3) as pool:        # the three passes are independent
            f_loud = pool.submit(measure_loudness, ffmpeg, str(final))
            f_detect = pool.submit(_detect, ffmpeg, str(final))
            f_frames = pool.submit(grab_frames, ffmpeg, str(final), info.duration, 20, (216, 384))
            loud, (black, frozen), frames = f_loud.result(), f_detect.result(), f_frames.result()
        li, tp, max_tp = loud["integrated"], loud["true_peak"], edit.audio.true_peak + 0.5
        add("loudness", li is not None and abs(li - edit.audio.loudness_i) <= 1.0,
            f"{li} LUFS (target {edit.audio.loudness_i:g} ± 1)")
        add("true_peak", tp is not None and tp <= max_tp, f"{tp} dBTP (max {max_tp:g})")
        add("no_black_frames", not black, f"black from {black} s" if black else "none")
        add("no_frozen_video", not frozen, f"frozen from {frozen} s" if frozen else "none")
        last = edit.captions.pages[-1].end if edit.captions.pages else 0.0
        add("captions_inside_video", last <= edit.duration + 0.05, f"last caption ends at {last:.2f}s")
        save_png(contact_sheet(frames), sheet)
    result = {"job": job.name, "passed": all(c["ok"] for c in checks), "checks": checks, "final": str(final),
              "contact_sheet": str(sheet)}
    job.write("check.json", result)
    return result


def add_command(sub) -> None:
    p = sub.add_parser("check", help="Verify final.mp4 before delivery (exit code 3 if a check fails).")
    p.add_argument("job")
    p.set_defaults(func=lambda a: check(Job.open(a.job)))
