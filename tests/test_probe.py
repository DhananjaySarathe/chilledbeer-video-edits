import pytest

from shorts.errors import ShortsError
from shorts.media.probe import parse_ffprobe

SAMPLE = {
    "format": {"duration": "57.233333"},
    "streams": [
        {"codec_type": "video", "codec_name": "hevc", "width": 1080, "height": 1920, "pix_fmt": "yuv420p",
         "r_frame_rate": "30/1", "avg_frame_rate": "30/1", "nb_frames": "1717",
         "color_transfer": "bt709", "color_primaries": "bt709"},
        {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
    ],
}


def test_parse_sample_like_phone_clip():
    info = parse_ffprobe(SAMPLE, "in.mp4")
    assert info.display_size == (1080, 1920)
    assert info.fps == 30.0 and not info.is_vfr and not info.is_hdr
    assert info.has_audio and info.sample_rate == 48000 and info.channels == 2
    assert info.nb_frames == 1717


def test_rotation_side_data_swaps_display_size():
    data = {"format": {"duration": "2"}, "streams": [dict(SAMPLE["streams"][0], width=1920, height=1080,
            side_data_list=[{"side_data_type": "Display Matrix", "rotation": -90}]), SAMPLE["streams"][1]]}
    info = parse_ffprobe(data, "r.mp4")
    assert info.rotation == 90
    assert info.display_size == (1080, 1920)


def test_vfr_and_hdr_flags():
    v = dict(SAMPLE["streams"][0], avg_frame_rate="2997/100", color_transfer="arib-std-b67", color_primaries="bt2020")
    info = parse_ffprobe({"format": {"duration": "1"}, "streams": [v]}, "h.mp4")
    assert info.is_vfr and info.is_hdr and not info.has_audio


def test_no_video_stream_is_an_error():
    with pytest.raises(ShortsError) as e:
        parse_ffprobe({"format": {}, "streams": [SAMPLE["streams"][1]]}, "a.m4a")
    assert e.value.code == "E_NO_VIDEO"
