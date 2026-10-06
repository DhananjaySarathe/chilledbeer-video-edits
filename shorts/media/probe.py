"""Read what a video file really is: size, rotation, frame rate, colour and audio."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from shorts.errors import ShortsError
from shorts.proc import run


@dataclass(frozen=True)
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    rotation: int                 # 0, 90, 180 or 270
    fps: float                    # average frame rate
    fps_nominal: float            # r_frame_rate
    nb_frames: int | None
    video_codec: str
    pix_fmt: str
    color_transfer: str
    color_primaries: str
    has_audio: bool
    audio_stream: int | None      # position among audio streams (0 = first)
    sample_rate: int | None
    channels: int | None

    @property
    def display_size(self) -> tuple[int, int]:
        return (self.height, self.width) if self.rotation in (90, 270) else (self.width, self.height)

    @property
    def is_hdr(self) -> bool:
        return self.color_transfer in ("arib-std-b67", "smpte2084") or self.color_primaries == "bt2020"

    @property
    def is_vfr(self) -> bool:
        return self.fps_nominal > 0 and abs(self.fps - self.fps_nominal) > 0.0005 * self.fps_nominal

    def to_dict(self) -> dict:
        return asdict(self) | {"display_size": list(self.display_size), "is_hdr": self.is_hdr, "is_vfr": self.is_vfr}


def _ratio(value: str | None) -> float:
    if not value:
        return 0.0
    if "/" not in value:
        return float(value)
    num, den = value.split("/")
    return float(num) / float(den) if float(den) else 0.0


def _rotation(stream: dict) -> int:
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return int(round(abs(float(side["rotation"])))) % 360
    tag = (stream.get("tags") or {}).get("rotate")
    return int(tag) % 360 if tag else 0


def parse_ffprobe(data: dict, path: str) -> MediaInfo:
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ShortsError("E_NO_VIDEO", f"{path} has no video stream.", "Use a real video file (mp4 or mov).")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    nb = str(video.get("nb_frames") or "")
    return MediaInfo(
        path=path,
        duration=float((data.get("format") or {}).get("duration") or video.get("duration") or 0),
        width=int(video["width"]), height=int(video["height"]), rotation=_rotation(video),
        fps=_ratio(video.get("avg_frame_rate")), fps_nominal=_ratio(video.get("r_frame_rate")),
        nb_frames=int(nb) if nb.isdigit() else None, video_codec=video.get("codec_name", ""),
        pix_fmt=video.get("pix_fmt", ""), color_transfer=video.get("color_transfer") or "",
        color_primaries=video.get("color_primaries") or "", has_audio=audio is not None,
        audio_stream=0 if audio is not None else None,
        sample_rate=int(audio["sample_rate"]) if audio is not None and audio.get("sample_rate") else None,
        channels=int(audio["channels"]) if audio is not None and audio.get("channels") else None,
    )


def probe_media(ffprobe: str, path: str) -> MediaInfo:
    proc = run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
               code="E_UNREADABLE", what=f"Reading {path}")
    return parse_ffprobe(json.loads(proc.stdout), path)
