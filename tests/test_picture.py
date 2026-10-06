import cv2
import numpy as np
import pytest

from shorts import config
from shorts.analyze.contact import contact_sheet, fmt_tc
from shorts.analyze.picture import blur_score, picture_pass, ranges, scene_score, summarize
from tests.media import make_clip


def test_ranges_merges_consecutive_flags():
    times = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    assert ranges(times, [False, True, True, True, False, False], 0.5, 1.0) == [{"start": 0.5, "end": 2.0}]
    assert ranges(times, [False, True, False, False, False, False], 0.5, 1.0) == []


def test_blur_score_higher_for_sharp_image():
    rng = np.random.default_rng(1)
    sharp = (rng.random((640, 360)) * 255).astype(np.uint8)
    assert blur_score(sharp) > blur_score(cv2.GaussianBlur(sharp, (15, 15), 5))


def test_scene_score_zero_for_identical_frames():
    a = np.full((114, 64), 100, np.uint8)
    assert scene_score(a, a) == 0.0
    assert scene_score(a, np.full((114, 64), 200, np.uint8)) > 0.3


def test_fmt_tc():
    assert fmt_tc(72.46) == "1:12.5"


def test_contact_sheet_shape():
    frames = [(float(k), np.zeros((640, 360, 3), np.uint8)) for k in range(20)]
    assert contact_sheet(frames).shape == (4 * 384, 5 * 216, 3)


@pytest.mark.skipif(not config.FACE_MODEL.exists(), reason="run `uv run shorts setup` first")
def test_picture_pass_on_synthetic_clip(tmp_path):
    src = make_clip(tmp_path / "c.mp4", seconds=2.0)
    samples, thumbs = picture_pass("ffmpeg", str(src), duration=2.0, n_thumbs=4)
    assert 3 <= len(samples) <= 5
    assert len(thumbs) == 4
    s = summarize(samples)
    assert s["face_presence"] == 0.0 and s["face_box"] is None and len(s["face_track"]) == len(samples)
