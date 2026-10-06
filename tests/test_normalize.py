import dataclasses

import pytest

from shorts.errors import ShortsError
from shorts.media.normalize import normalize_cmd, plan_normalization
from shorts.media.probe import MediaInfo

CLEAN = MediaInfo(path="in.mp4", duration=10.0, width=1080, height=1920, rotation=0, fps=30.0, fps_nominal=30.0,
                  nb_frames=300, video_codec="hevc", pix_fmt="yuv420p", color_transfer="bt709",
                  color_primaries="bt709", has_audio=True, audio_stream=0, sample_rate=48000, channels=2)


def with_(**kw):
    return dataclasses.replace(CLEAN, **kw)


def test_clean_clip_needs_nothing():
    plan = plan_normalization(CLEAN)
    assert plan.needed is False and plan.target_fps == 30


def test_hdr_needs_tonemap():
    plan = plan_normalization(with_(color_transfer="arib-std-b67", color_primaries="bt2020", pix_fmt="yuv420p10le"))
    assert plan.tonemap and "hdr" in plan.reasons and "pixfmt" not in plan.reasons


def test_vfr_size_rotation_audio_reasons():
    plan = plan_normalization(with_(fps=29.98, width=1920, height=1080, rotation=90, sample_rate=44100, channels=1))
    assert set(plan.reasons) >= {"vfr", "rotation", "audio"}
    assert plan.needed


def test_sixty_fps_source_keeps_sixty():
    assert plan_normalization(with_(fps=60.0, fps_nominal=60.0)).target_fps == 60


def test_landscape_refused():
    with pytest.raises(ShortsError) as e:
        plan_normalization(with_(width=1920, height=1080))
    assert e.value.code == "E_LANDSCAPE"


def test_no_audio_refused():
    with pytest.raises(ShortsError) as e:
        plan_normalization(with_(has_audio=False, audio_stream=None, sample_rate=None, channels=None))
    assert e.value.code == "E_NO_AUDIO"


def test_far_from_9x16_refused():
    with pytest.raises(ShortsError) as e:
        plan_normalization(with_(width=1080, height=1350))
    assert e.value.code == "E_ASPECT"


def test_normalize_cmd_contents():
    info = with_(color_transfer="arib-std-b67", color_primaries="bt2020")
    cmd = normalize_cmd("ffmpeg", info, plan_normalization(info), "out.mp4")
    vf = cmd[cmd.index("-vf") + 1]
    assert "zscale=tin=arib-std-b67" in vf and "fps=30" in vf and "crop=1080:1920" in vf
    assert "h264_videotoolbox" in cmd and cmd[-1] == "out.mp4"
    assert cmd[cmd.index("-hwaccel") + 1] == "videotoolbox" and cmd.index("-hwaccel") < cmd.index("-i")
    assert "-hwaccel" not in normalize_cmd("ffmpeg", info, plan_normalization(info), "out.mp4", hw=False)
