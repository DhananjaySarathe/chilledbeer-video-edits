import pytest

from shorts.errors import ShortsError
from shorts.media.probe import probe_media
from shorts.media.run import probe, slugify
from tests.media import make_clip


def test_slugify():
    assert slugify("VID_20260922_025801_186_bsl") == "vid-20260922-025801-186-bsl"


def test_clean_clip_is_not_reencoded(tmp_path, jobs_root):
    src = make_clip(tmp_path / "clean.mp4")
    out = probe(str(src), "clean")
    assert out["normalized"] is False
    assert out["working_path"] == str(src.resolve())
    assert (jobs_root / "clean" / "probe.json").exists()


@pytest.mark.slow
def test_vfr_clip_is_normalized(tmp_path, jobs_root):
    out = probe(str(make_clip(tmp_path / "vfr.mp4", vfr=True)), "vfr")
    info = probe_media("ffprobe", out["working_path"])
    assert "vfr" in out["reasons"]
    assert info.display_size == (1080, 1920) and not info.is_vfr and info.fps == pytest.approx(30, abs=0.01)


@pytest.mark.slow
def test_hdr_clip_is_tonemapped(tmp_path, jobs_root):
    out = probe(str(make_clip(tmp_path / "hdr.mp4", hdr=True)), "hdr")
    info = probe_media("ffprobe", out["working_path"])
    assert "hdr" in out["reasons"] and not info.is_hdr and info.pix_fmt == "yuv420p"


@pytest.mark.slow
def test_rotated_clip_becomes_upright_portrait(tmp_path, jobs_root):
    out = probe(str(make_clip(tmp_path / "rot.mp4", w=1920, h=1080, rotate=90)), "rot")
    info = probe_media("ffprobe", out["working_path"])
    assert "rotation" in out["reasons"]
    assert info.display_size == (1080, 1920) and info.rotation == 0


@pytest.mark.slow
def test_mono_44k_audio_is_fixed(tmp_path, jobs_root):
    out = probe(str(make_clip(tmp_path / "mono.mp4", audio="mono441")), "mono")
    info = probe_media("ffprobe", out["working_path"])
    assert "audio" in out["reasons"] and info.sample_rate == 48000 and info.channels == 2


def test_landscape_is_refused(tmp_path, jobs_root):
    with pytest.raises(ShortsError) as e:
        probe(str(make_clip(tmp_path / "land.mp4", w=1920, h=1080)), "land")
    assert e.value.code == "E_LANDSCAPE"


def test_no_audio_is_refused(tmp_path, jobs_root):
    with pytest.raises(ShortsError) as e:
        probe(str(make_clip(tmp_path / "mute.mp4", audio="none")), "mute")
    assert e.value.code == "E_NO_AUDIO"


def test_missing_input(jobs_root):
    with pytest.raises(ShortsError) as e:
        probe("/no/such/file.mp4", "x")
    assert e.value.code == "E_NO_INPUT"
