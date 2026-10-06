import pytest

from shorts import config
from shorts.media.probe import probe_media
from shorts.render.run import preview, render
from tests.factories import make_edit_job

needs_font = pytest.mark.skipif(not (config.FONTS / "Montserrat-800.ttf").exists(),
                                reason="run `uv run shorts setup` first")


@pytest.mark.slow
@needs_font
def test_preview_and_render_a_small_edit(tmp_path, jobs_root):
    job = make_edit_job("r", tmp_path)
    out = preview(job)
    info = probe_media("ffprobe", out["preview"])
    assert info.display_size == (540, 960) and abs(info.duration - 2.0) < 0.1
    assert (job.work / "preview_strip.png").exists() and (job.work / "captions.ass").exists() and out["cuts"]
    out = render(job)
    info = probe_media("ffprobe", out["final"])
    assert info.display_size == (1080, 1920) and abs(info.duration - 2.0) < 0.1
    assert info.fps == pytest.approx(30, abs=0.01) and info.sample_rate == 48000 and info.channels == 2
