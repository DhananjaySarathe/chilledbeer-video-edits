import numpy as np

from shorts.analyze.audio import energy_db, extract_wav, levels, parse_ebur128, read_wav
from tests.media import make_clip


def tone(sr, seconds, amp=0.3, f=220.0):
    t = np.arange(int(sr * seconds)) / sr
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def test_energy_db_levels():
    sr = 16000
    x = np.concatenate([tone(sr, 0.5), np.zeros(int(sr * 0.5), np.float32)])
    db = energy_db(x, sr)
    assert len(db) == 100
    assert db[:50].mean() > -15
    assert db[60:].max() < -100


def test_levels_are_ordered():
    sr = 16000
    rng = np.random.default_rng(0)
    x = np.concatenate([tone(sr, 1.0), 0.001 * rng.standard_normal(sr).astype(np.float32)])
    speech, floor, quiet, dip = levels(energy_db(x, sr))
    assert floor < quiet < dip < speech


EBUR = """[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -19.6 LUFS
    Threshold: -30.0 LUFS

  Loudness range:
    LRA:         5.6 LU
    Threshold: -40.1 LUFS
    LRA low:   -23.5 LUFS
    LRA high:  -17.9 LUFS

  True peak:
    Peak:       -0.4 dBFS
"""


def test_parse_ebur128():
    assert parse_ebur128(EBUR) == {"integrated": -19.6, "lra": 5.6, "true_peak": -0.4}


def test_parse_ebur128_silence():
    assert parse_ebur128("Summary:\n I: -inf LUFS\n LRA: 0.0 LU\n Peak: -inf dBFS")["integrated"] is None


def test_extract_wav_is_16k_mono(tmp_path):
    src = make_clip(tmp_path / "c.mp4", seconds=1.0)
    samples, sr = read_wav(extract_wav("ffmpeg", str(src), tmp_path / "a.wav"))
    assert sr == 16000
    assert abs(len(samples) / sr - 1.0) < 0.05
