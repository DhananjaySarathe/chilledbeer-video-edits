"""Decide whether a clip needs fixing before editing, and build the ffmpeg command that fixes it."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from shorts import config
from shorts.errors import ShortsError
from shorts.media.probe import MediaInfo


@dataclass(frozen=True)
class NormalizePlan:
    needed: bool
    reasons: list[str]
    target_fps: int
    tonemap: bool
    out_w: int = config.OUT_W
    out_h: int = config.OUT_H

    def to_dict(self) -> dict:
        return asdict(self)


def plan_normalization(info: MediaInfo, landscape: bool = False) -> NormalizePlan:
    """landscape: a 16:9 take for a long-form edit (analysed and cut like a short, laid out at 1920x1080)."""
    if not info.has_audio:
        raise ShortsError("E_NO_AUDIO", "The clip has no audio track.",
                          "Talking-head shorts need the speaker's audio; export the clip with sound.")
    w, h = info.display_size
    out_w, out_h = (1920, 1080) if landscape else (config.OUT_W, config.OUT_H)
    if landscape:
        if not 1.6 <= w / h <= 1.95:
            raise ShortsError("E_ASPECT", f"The clip is {w}x{h}, too far from 16:9.", "Export it at 16:9, for example 1920x1080.")
    elif w >= h:
        raise ShortsError("E_LANDSCAPE", f"The clip is landscape ({w}x{h}).",
                          "Shorts need vertical (9:16) video; for a 16:9 long-form edit use: shorts probe --landscape.")
    elif not 1.6 <= h / w <= 1.95:
        raise ShortsError("E_ASPECT", f"The clip is {w}x{h}, too far from 9:16.", "Export it at 9:16, for example 1080x1920.")
    reasons: list[str] = []
    if info.is_hdr:
        reasons.append("hdr")
    target = 60 if info.fps >= 45 else 30
    if info.is_vfr:
        reasons.append("vfr")
    elif abs(info.fps - target) > 0.01:
        reasons.append("fps")
    if (w, h) != (out_w, out_h):
        reasons.append("size")
    if info.rotation:
        reasons.append("rotation")
    if info.sample_rate != 48000 or info.channels != 2:
        reasons.append("audio")
    if info.pix_fmt not in ("yuv420p", "yuvj420p") and not info.is_hdr:
        reasons.append("pixfmt")
    return NormalizePlan(needed=bool(reasons), reasons=reasons, target_fps=target, tonemap=info.is_hdr, out_w=out_w, out_h=out_h)


def normalize_cmd(ffmpeg: str, info: MediaInfo, plan: NormalizePlan, dst: str, hw: bool = True) -> list[str]:
    """hw: decode on the media engine. 4K HEVC decodes 2.5x faster that way (15 s of a 77 Mbit/s phone clip:
    11.6 s -> 4.7 s, measured 2026-09-27); the decoded pixels are the same, so the output is too."""
    vf: list[str] = []
    if plan.tonemap:
        tin = info.color_transfer if info.color_transfer in ("arib-std-b67", "smpte2084") else "arib-std-b67"
        vf.append(f"zscale=tin={tin}:pin=bt2020:min=bt2020nc:t=linear:npl=100,format=gbrpf32le,"
                  "zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
    vf.append(f"scale={plan.out_w}:{plan.out_h}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={plan.out_w}:{plan.out_h}")
    vf.append(f"fps={plan.target_fps}")
    vf.append("setsar=1,format=yuv420p")
    return [ffmpeg, "-v", "error", "-y", *(["-hwaccel", "videotoolbox"] if hw else []), "-i", info.path, "-map", "0:v:0", "-map", f"0:a:{info.audio_stream or 0}",
            "-vf", ",".join(vf), "-fps_mode", "cfr",
            "-c:v", "h264_videotoolbox", "-b:v", "20M", "-profile:v", "high", "-g", str(plan.target_fps),
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-c:a", "aac", "-aac_pns", "0", "-b:a", "256k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", dst]
