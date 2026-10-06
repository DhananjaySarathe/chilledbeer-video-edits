import numpy as np

from shorts.music import library as lib
from shorts.music.run import place


def _clicks(bpm: float, seconds: float = 40.0) -> np.ndarray:
    x = np.zeros(int(seconds * lib.SR), np.float32)
    step = 60 / bpm
    for k in range(int(seconds / step)):
        i = int(k * step * lib.SR)
        x[i:i + 200] += np.hanning(200).astype(np.float32)
    return x + np.random.default_rng(1).normal(0, 1e-3, len(x)).astype(np.float32)


def test_tempo_finds_click_track_bpm():
    for bpm in (90, 105, 124):
        _, _, flux = lib._envelopes(_clicks(bpm))
        got, _ = lib._tempo(flux)
        assert abs(got - bpm) < 1.5, (bpm, got)


def test_drop_found_where_the_track_gets_loud():
    sr = lib.SR
    t = np.arange(int(40 * sr)) / sr
    x = (0.02 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    x[int(18 * sr):] += (0.4 * np.sin(2 * np.pi * 60 * t[int(18 * sr):])).astype(np.float32)
    full, low, flux = lib._envelopes(x)
    drops = lib._drops(full, low, flux, 40.0)
    assert drops and abs(drops[0]["t"] - 18.0) < 0.8


def _s(**kw):
    return {"duration": 120.0, "bpm": 120.0, "beat0": 0.0, "quiet_intro": 0.0, "drops": [], **kw}


def test_place_puts_the_drop_on_the_hit():
    p = place(_s(drops=[{"t": 30.0, "strength": 9.0}]), duration=50.0, hit=6.0, first_word=0.1)
    assert p["start"] == 24.0 and p["enter"] == 0.0


def test_place_enters_late_when_the_drop_comes_early():
    p = place(_s(drops=[{"t": 4.0, "strength": 9.0}]), duration=50.0, hit=10.0, first_word=0.1)
    assert p["start"] == 0.0 and p["enter"] == 6.0


def test_place_without_hit_skips_quiet_intro_on_a_beat():
    p = place(_s(quiet_intro=8.2), duration=50.0, hit=None, first_word=0.3)
    assert 7.0 <= p["start"] <= 8.0
