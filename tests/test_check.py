import subprocess

import pytest

from shorts import cli, config
from shorts.check.run import check, parse_detect
from shorts.render.run import render
from tests.factories import make_edit_job

needs_font = pytest.mark.skipif(not (config.FONTS / "Montserrat-800.ttf").exists(),
                                reason="run `uv run shorts setup` first")

DETECT = """[blackdetect @ 0x1] black_start:0 black_end:0.5 black_duration:0.5
[freezedetect @ 0x2] lavfi.freezedetect.freeze_start: 3.2
[freezedetect @ 0x2] lavfi.freezedetect.freeze_duration: 1.6"""


def test_parse_detect():
    assert parse_detect(DETECT) == ([0.0], [3.2])
    assert parse_detect("nothing here") == ([], [])


@pytest.mark.slow
@needs_font
def test_a_good_render_passes(tmp_path, jobs_root):
    job = make_edit_job("k", tmp_path)
    render(job)
    result = check(job)
    assert result["passed"], result["checks"]
    assert job.has("check.json") and (job.final_dir / "final_contact.png").exists()


@pytest.mark.slow
def test_a_black_video_fails_with_exit_code_3(tmp_path, jobs_root, capsys):
    job = make_edit_job("k", tmp_path)
    job.final_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-shortest", str(job.final)],
                   check=True)
    assert cli.main(["check", "k"]) == 3
    assert '"no_black_frames"' in capsys.readouterr().out
