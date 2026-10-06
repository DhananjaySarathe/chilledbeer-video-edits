"""Map between the edited (output) timeline and the source footage."""
from __future__ import annotations

import shutil
from pathlib import Path

from shorts.proc import run
from shorts.schemas import Analysis, EditFile


def segment_starts(edit: EditFile) -> list[float]:
    """Output time where each segment begins."""
    out, t = [], 0.0
    for s in edit.segments:
        out.append(t)
        t += (s.out_frame - s.in_frame) / edit.output.fps
    return out


def word_timeline(edit: EditFile, analysis: Analysis, overrides: dict[int, str] | None = None) -> list[dict]:
    """Every kept word with its output-timeline start/end: [{i, text, start, end}].
    With caption overrides, words read as the captions do (an empty override drops the word)."""
    fps, words, out, overrides = edit.output.fps, analysis.words, [], overrides or {}
    for seg, o in zip(edit.segments, segment_starts(edit)):
        t_in, dur = seg.in_frame / fps, (seg.out_frame - seg.in_frame) / fps
        for i in range(seg.first_word, seg.last_word + 1):
            w = words[i]
            text = w.text
            if i in overrides:
                text = overrides[i].strip()
                if not text:
                    continue
                if w.text[-1:] in ",.?!" and text[-1:] not in ",.?!":
                    text += w.text[-1]          # keep the clause breaks beats split on
            s = o + min(max(w.start - t_in, 0.0), dur)
            e = o + min(max(w.end - t_in, 0.0), dur)
            out.append({"i": i, "text": text, "start": round(s, 3), "end": round(max(e, s + 0.05), 3)})
    return out


def source_to_output(edit: EditFile, t: float) -> float:
    """Output time where source time t plays; a moment that was cut maps to where the next kept piece starts."""
    fps = edit.output.fps
    for seg, o in zip(edit.segments, segment_starts(edit)):
        a, b = seg.in_frame / fps, seg.out_frame / fps
        if t < b:
            return round(o + max(0.0, t - a), 3)
    return round(edit.duration, 3)


def source_ranges(edit: EditFile, t0: float, t1: float) -> list[tuple[int, int]]:
    """Source (first_frame, frame_count) pieces that play during output [t0, t1)."""
    fps, pieces = edit.output.fps, []
    f0, f1 = int(round(t0 * fps)), int(round(t1 * fps))
    cursor = 0
    for seg in edit.segments:
        n = seg.out_frame - seg.in_frame
        a, b = max(f0, cursor), min(f1, cursor + n)
        if b > a:
            pieces.append((seg.in_frame + (a - cursor), b - a))
        cursor += n
    return pieces


def extract_window(ffmpeg: str, source: str, edit: EditFile, t0: float, t1: float, out_dir: Path,
                   width: int = 720) -> list[Path]:
    """JPEG frames of the speaker for output [t0, t1), uncropped (templates frame him themselves)."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    fps, number = edit.output.fps, 1
    for first, count in source_ranges(edit, t0, t1):
        run([ffmpeg, "-v", "error", "-y", "-ss", f"{max(0.0, (first - 0.25) / fps):.6f}", "-i", source,
             "-frames:v", str(count), "-vf", f"scale={width}:-2:flags=lanczos", "-q:v", "2",
             "-start_number", str(number), str(out_dir / "f%04d.jpg")], code="E_FRAMES", what="Extracting speaker frames")
        number += count
    return sorted(out_dir.glob("f*.jpg"))
