"""The ffmpeg command for an edit: exact trims, concat, libass captions, loudness.

Segments that play forward through the source share one input: it is decoded once and split into one branch per
segment, and `trim` drops everything outside each segment, so nothing is buffered and no frame is decoded twice.
(One input per segment was 1.7x slower and used 3x the memory: phone clips have 4 s keyframe gaps, so every seek
decoded seconds of throwaway frames.) A segment that jumps back in the source starts a new input.
"""
from __future__ import annotations

import json
import math
import re

from shorts.errors import ShortsError
from shorts.schemas import EditFile, Segment

AUDIO_SR = 48000
SEEK_BACK_FRAMES = 0.25       # seek a quarter frame early so the wanted frame is never skipped
PREVIEW_SIZE = (540, 960)
ENCODERS = {
    "preview": ["-c:v", "h264_videotoolbox", "-b:v", "4M", "-realtime", "1"],
    "final": ["-c:v", "h264_videotoolbox", "-b:v", "16M", "-maxrate", "20M", "-bufsize", "32M", "-profile:v", "high"],
    "max": ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high"],
}


def _seek(frame: int, fps: int) -> float:
    return max(0.0, math.floor((frame - SEEK_BACK_FRAMES) / fps * 1e6) / 1e6)


def input_runs(edit: EditFile) -> list[list[int]]:
    """Segment indices grouped into runs that move forward through the source; each run is one input."""
    runs: list[list[int]] = []
    prev_out = None
    for k, s in enumerate(edit.segments):
        if runs and s.in_frame >= prev_out:
            runs[-1].append(k)
        else:
            runs.append([k])
        prev_out = s.out_frame
    return runs


def inputs(edit: EditFile, audio_only: bool = False, hw: bool = True) -> list[str]:
    fps = edit.output.fps
    args: list[str] = []
    for run in input_runs(edit):
        first, last = edit.segments[run[0]], edit.segments[run[-1]]
        ss = _seek(first.in_frame, fps)
        args += (["-hwaccel", "videotoolbox"] if hw and not audio_only else []) + (["-vn"] if audio_only else [])
        args += ["-ss", f"{ss:.6f}", "-t", f"{(last.out_frame + 2) / fps - ss:.6f}", "-i", edit.source]
    return args


SHARPEN_PER_ZOOM = 2.0      # sharpening grows with the zoom: x1.3 at 1.15, x1.6 at a 1.3 punch-in
SHARPEN_MAX = 0.6


def sharpen_amount(grade: float, zoom: float) -> float:
    """Luma unsharp amount for a segment: the grade's 0.45 * g (0.22 at the default: more shows the codec's blocks on
    true 1080p), raised with the zoom because the upscale softens what it enlarges."""
    return min(SHARPEN_MAX, 0.45 * grade * (1 + SHARPEN_PER_ZOOM * max(0.0, zoom - 1)))


def video_chain(src: str, k: int, seg: Segment, base_frame: int, preview: bool, grade: float = 0.0) -> str:
    """Frames of segment k; frame numbers count from the run's first frame (base_frame). With a grade, the final
    render sharpens each segment after its scale, by its zoom (sharpen after scaling, never before)."""
    f = [f"trim=start_frame={seg.in_frame - base_frame}:end_frame={seg.out_frame - base_frame}", "setpts=PTS-STARTPTS"]
    if seg.crop:
        cw, ch, x, y = seg.crop
        f.append(f"crop={cw}:{ch}:{x}:{y}")
    if preview:
        f.append(f"scale={PREVIEW_SIZE[0]}:{PREVIEW_SIZE[1]}:flags=bilinear")
    elif seg.crop:
        f.append("scale=1080:1920:flags=lanczos")
    if not preview and grade > 0:
        f.append(f"unsharp=5:5:{sharpen_amount(grade, seg.zoom if seg.crop else 1.0):.2f}:5:5:0")
    f += ["setsar=1", "format=yuv420p"]
    return src + ",".join(f) + f"[v{k}]"


def audio_chain(src: str, k: int, seg: Segment, fps: int, ss: float, fade_s: float,
                fade_in: bool = True, fade_out: bool = True) -> str:
    """Audio of segment k, trimmed by timestamp (the input starts at ss), with short fades against clicks where
    audio was removed (a zoom cut joins continuous sound, so it gets no fade)."""
    a, b = seg.in_frame / fps - ss, seg.out_frame / fps - ss
    d = (seg.out_frame - seg.in_frame) / fps
    fades = ([f"afade=t=in:d={fade_s:g}"] if fade_in else []) + \
            ([f"afade=t=out:st={max(d - fade_s, 0.0):.6f}:d={fade_s:g}"] if fade_out else [])
    return (f"{src}aresample={AUDIO_SR},atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS"
            + "".join("," + f for f in fades) + f"[a{k}]")


def _split(parts: list[str], src: str, kind: str, prefix: str, m: int) -> list[str]:
    if m == 1:
        return [src]
    labels = [f"[{prefix}{j}]" for j in range(m)]
    parts.append(f"{src}{kind}={m}" + "".join(labels))
    return labels


def _chains(edit: EditFile, preview: bool, video: bool = True) -> list[str]:
    fps, fade = edit.output.fps, edit.audio.fade_ms / 1000
    parts: list[str] = []
    for r, run in enumerate(input_runs(edit)):
        base = edit.segments[run[0]].in_frame
        ss = _seek(base, fps)
        vsrc = _split(parts, f"[{r}:v]", "split", f"r{r}v", len(run)) if video else []
        asrc = _split(parts, f"[{r}:a]", "asplit", f"r{r}a", len(run))
        for j, k in enumerate(run):
            seg = edit.segments[k]
            if video:
                parts.append(video_chain(vsrc[j], k, seg, base, preview, edit.output.grade))
            segs = edit.segments
            joined_before = k > 0 and segs[k - 1].out_frame == seg.in_frame
            joined_after = k + 1 < len(segs) and segs[k + 1].in_frame == seg.out_frame
            parts.append(audio_chain(asrc[j], k, seg, fps, ss, fade, not joined_before, not joined_after))
    return parts


# voice polish: rumble below 80 Hz off, light spectral denoise, a little less boxiness, a little more presence,
# gentle 2.5:1 compression so quiet words hold up on phone speakers
VOICE_CLEAN = ("highpass=f=80,afftdn=nr=8:nf=-42:tn=1,equalizer=f=250:t=q:w=1:g=-1.5,"
               "equalizer=f=3500:t=q:w=1.2:g=2,acompressor=threshold=-24dB:ratio=2.5:attack=8:release=120:makeup=2")


def grade_chain(g: float, preview: bool) -> str:
    """A light, even grade for flat phone footage: contrast, colour, a touch of warmth. (Its sharpening is per
    segment in video_chain, scaled with the zoom.)"""
    return (f"eq=contrast={1 + 0.08 * g:.3f}:saturation={1 + 0.16 * g:.3f}:gamma={1 - 0.03 * g:.3f},"
            f"colorbalance=rm={0.03 * g:.3f}:bm={-0.03 * g:.3f}")


def _voice(parts: list[str], edit: EditFile) -> str:
    if not edit.audio.clean:
        return "ac"
    parts.append(f"[ac]{VOICE_CLEAN}[acl]")
    return "acl"


def audio_tail(edit: EditFile, mode: str, measured: dict | None = None) -> str:
    a = edit.audio
    if mode == "preview":        # fast: one gain step plus a limiter instead of two-pass loudnorm
        gain = 0.0 if a.source_integrated is None else max(-20.0, min(20.0, a.loudness_i - a.source_integrated))
        return f"volume={gain:.1f}dB,alimiter=limit=0.891:level=false"
    tail = f"loudnorm=I={a.loudness_i:g}:TP={a.true_peak:g}:LRA=11"
    if measured:
        tail += (f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                 f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                 f":offset={measured['target_offset']}:linear=true")
    # loudnorm aims at the true-peak target, but sound-effect transients and the AAC encoder still overshoot it
    # (measured -0.1 dBTP on video2, +0.5 dBTP on video4 with a plain sample limiter): the limiter runs 4x
    # oversampled with a fast attack so it catches inter-sample peaks, 1.2 dB under the target (AAC adds ~0.3-0.7)
    return tail + (f",aresample={4 * AUDIO_SR},alimiter=limit={10 ** ((a.true_peak - 1.2) / 20):.3f}"
                   f":attack=1:release=50:level=false,aresample={AUDIO_SR}")


def _overlay_chain(parts: list[str], base: str, overlays: list[dict], first_input: int, preview: bool) -> str:
    """Lay each rendered scene over the picture on its own time window (the scene file starts at 0)."""
    cur = base
    for k, ov in enumerate(overlays):
        scale = f",scale={PREVIEW_SIZE[0]}:{PREVIEW_SIZE[1]}:flags=bilinear" if preview else ""
        # The joined picture's timestamps run a microsecond late, and overlay counts a scene as over the moment
        # its last frame's timestamp passes, so every scene lost its last frame to raw footage. A transparent
        # padding frame keeps the last real frame on screen for its full duration.
        parts.append(f"[{first_input + k}:v]setpts=PTS-STARTPTS+{ov['start']:.6f}/TB{scale},format=yuva420p,"
                     f"tpad=stop=1:stop_mode=add:color=black@0.0[g{k}]")
        parts.append(f"[{cur}][g{k}]overlay=eof_action=pass:format=auto[o{k}]")
        cur = f"o{k}"
    return cur


def sfx_names(cues: list[dict]) -> list[str]:
    return list(dict.fromkeys(c["name"] for c in cues))


def _sfx_chain(parts: list[str], base: str, cues: list[dict], first_input: int) -> str:
    """Mix sound-effect cues under the voice (one input per distinct sound, split per use)."""
    labels = []
    for j, name in enumerate(sfx_names(cues)):
        mine = [c for c in cues if c["name"] == name]
        srcs = [f"[{first_input + j}:a]"]
        if len(mine) > 1:
            srcs = [f"[x{j}_{i}]" for i in range(len(mine))]
            parts.append(f"[{first_input + j}:a]asplit={len(mine)}" + "".join(srcs))
        for i, (c, src) in enumerate(zip(mine, srcs)):
            ms = max(0, int(round(c["at"] * 1000)))
            parts.append(f"{src}aresample={AUDIO_SR},adelay={ms}|{ms},volume={c['gain_db']:g}dB[s{j}_{i}]")
            labels.append(f"[s{j}_{i}]")
    parts.append(f"[{base}]" + "".join(labels) + f"amix=inputs={len(labels) + 1}:normalize=0:duration=first:dropout_transition=0[am]")
    return "am"


DUCK_RAMP_S = 0.25     # music glides down before a phrase and back up after it
DUCK_JOIN_S = 0.6      # speech gaps shorter than this stay ducked (no pumping between words)


def speech_spans(edit: EditFile, join: float = DUCK_JOIN_S) -> list[tuple[float, float]]:
    """Where the speaker talks on the output timeline (from the caption words), short gaps joined."""
    spans: list[list[float]] = []
    for w in sorted((w for p in edit.captions.pages for w in p.words), key=lambda w: w.start):
        if spans and w.start - spans[-1][1] < join:
            spans[-1][1] = max(spans[-1][1], w.end)
        else:
            spans.append([w.start, w.end])
    return [(round(a, 3), round(b, 3)) for a, b in spans]


def duck_expr(spans: list[tuple[float, float]], duck_db: float, ramp: float = DUCK_RAMP_S) -> str:
    """ffmpeg volume expression (eval=frame): 1 in the gaps, duck_db lower under speech, linear ramps."""
    if not spans or duck_db <= 0:
        return "1"
    low = 10 ** (-duck_db / 20)
    terms = [f"clip(min((t-{a - ramp:.3f})/{ramp:g},({b + ramp:.3f}-t)/{ramp:g}),0,1)" for a, b in spans]
    inside = terms[0]
    for term in terms[1:]:
        inside = f"max({inside},{term})"
    return f"1-{1 - low:.4f}*{inside}"


DROP_RAMP_S = 0.05     # a music drop cuts out and back in this fast (a hard beat, no click)


def drop_expr(drops: list, ramp: float = DROP_RAMP_S) -> str:
    """ffmpeg volume expression (eval=frame): 0 inside each drop window, 1 elsewhere, short linear ramps."""
    terms = [f"clip(min((t-{a:.3f})/{ramp:g},({b:.3f}-t)/{ramp:g}),0,1)" for a, b in drops if b > a]
    if not terms:
        return "1"
    inside = terms[0]
    for term in terms[1:]:
        inside = f"max({inside},{term})"
    return f"1-{inside}"


def _music_chain(parts: list[str], base: str, edit: EditFile, music: dict, index: int) -> str:
    """Loop/trim the track to the short, set its level, duck it under speech, fade it, and mix it in."""
    d = edit.duration
    enter = min(max(music.get("enter", 0.0), 0.0), max(0.0, d - 1.0))
    fo = min(music["fade_out"], (d - enter) / 3)
    delay = f"adelay={int(round(enter * 1000))}|{int(round(enter * 1000))}," if enter > 0 else ""
    drops = music.get("drops") or []
    gate = f"volume='{drop_expr(drops)}':eval=frame," if drops else ""
    parts.append(f"[{index}:a]aresample={AUDIO_SR},aformat=channel_layouts=stereo,{delay}atrim=duration={d:.3f},"
                 f"asetpts=PTS-STARTPTS,volume={music['gain_db']:.2f}dB,"
                 f"volume='{duck_expr(speech_spans(edit), music['duck_db'])}':eval=frame,{gate}"
                 f"afade=t=in:st={enter:.3f}:d={music['fade_in']:g},afade=t=out:st={d - fo:.3f}:d={fo:g}[mus]")
    parts.append(f"[{base}][mus]amix=inputs=2:normalize=0:duration=first:dropout_transition=0[amx]")
    return "amx"


def music_input(music: dict | None) -> list[str]:
    return ["-stream_loop", "-1", "-ss", f"{music['start']:g}", "-i", music["file"]] if music else []


def filter_graph(edit: EditFile, mode: str, measured: dict | None = None, overlays: list[dict] | None = None,
                 sfx: list[dict] | None = None, subtitles: bool = True, music: dict | None = None) -> str:
    n = len(edit.segments)
    parts = _chains(edit, mode == "preview")
    parts.append("".join(f"[v{k}][a{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
    runs = len(input_runs(edit))
    base = "vc"
    if edit.output.grade > 0:
        parts.append(f"[vc]{grade_chain(edit.output.grade, mode == 'preview')}[vg]")
        base = "vg"
    video = _overlay_chain(parts, base, overlays or [], runs, mode == "preview") if overlays else base
    sp = edit.output.speed
    vout = "vs" if sp != 1 else "vo"
    parts.append(f"[{video}]subtitles=filename=captions.ass:fontsdir=fonts[{vout}]" if subtitles
                 else f"[{video}]null[{vout}]")
    if sp != 1:                  # the finished programme plays faster: graphics and captions stay in sync
        parts.append(f"[vs]setpts=PTS/{sp:g}[vo]")
    voice = _voice(parts, edit)
    audio = _sfx_chain(parts, voice, sfx, runs + len(overlays or [])) if sfx else voice
    if music:
        audio = _music_chain(parts, audio, edit, music, runs + len(overlays or []) + len(sfx_names(sfx or [])))
    audio = _speed(parts, audio, sp)
    parts.append(f"[{audio}]{audio_tail(edit, mode, measured)}[ao]")
    return ";".join(parts)


def _speed(parts: list[str], audio: str, speed: float) -> str:
    """Speed the mixed programme up without changing pitch (atempo), after music ducking and sound effects."""
    if speed == 1:
        return audio
    parts.append(f"[{audio}]atempo={speed:g}[asp]")
    return "asp"


def extra_inputs(overlays: list[dict] | None, sfx: list[dict] | None, sfx_files: dict | None) -> list[str]:
    args: list[str] = []
    for ov in overlays or []:
        args += ["-i", ov["mov"]]
    for name in sfx_names(sfx or []):
        args += ["-i", str(sfx_files[name])]
    return args


def build_cmd(ffmpeg: str, edit: EditFile, out: str, mode: str = "final", measured: dict | None = None,
              hw: bool = True, overlays: list[dict] | None = None, sfx: list[dict] | None = None,
              sfx_files: dict | None = None, subtitles: bool = True, music: dict | None = None) -> list[str]:
    graph = filter_graph(edit, mode, measured, overlays, sfx, subtitles, music)
    return [ffmpeg, "-v", "error", "-y", *inputs(edit, hw=hw), *extra_inputs(overlays, sfx, sfx_files), *music_input(music),
            "-filter_complex", graph,
            "-map", "[vo]", "-map", "[ao]", *ENCODERS[mode], "-r", str(edit.output.fps), "-pix_fmt", "yuv420p",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-c:a", "aac", "-aac_pns", "0", "-b:a", "192k", "-ar", str(AUDIO_SR), "-ac", "2", "-movflags", "+faststart", out]


def build_measure_cmd(ffmpeg: str, edit: EditFile, sfx: list[dict] | None = None, sfx_files: dict | None = None,
                      music: dict | None = None) -> list[str]:
    """Audio-only pass that measures the loudness of the edited programme, sound effects and music included (loudnorm pass 1)."""
    n, a = len(edit.segments), edit.audio
    parts = _chains(edit, preview=False, video=False)
    parts.append("".join(f"[a{k}]" for k in range(n)) + f"concat=n={n}:v=0:a=1[ac]")
    runs = len(input_runs(edit))
    voice = _voice(parts, edit)
    audio = _sfx_chain(parts, voice, sfx, runs) if sfx else voice
    if music:
        audio = _music_chain(parts, audio, edit, music, runs + len(sfx_names(sfx or [])))
    audio = _speed(parts, audio, edit.output.speed)
    parts.append(f"[{audio}]loudnorm=I={a.loudness_i:g}:TP={a.true_peak:g}:LRA=11:print_format=json[ao]")
    return [ffmpeg, "-hide_banner", "-nostats", "-y", *inputs(edit, audio_only=True), *extra_inputs(None, sfx, sfx_files),
            *music_input(music),
            "-filter_complex", ";".join(parts), "-map", "[ao]", "-f", "null", "-"]


def parse_loudnorm(stderr: str) -> dict:
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S)
    if not m:
        raise ShortsError("E_LOUDNESS", "Could not read the loudness measurement from ffmpeg.",
                          "See measure.log in the job's temp folder (output/temp/jobs/<name>).")
    data = json.loads(m.group(0))
    return {k: data[k] for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
