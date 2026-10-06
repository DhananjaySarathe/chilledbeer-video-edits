import numpy as np
import pytest

from shorts.plan.cuts import build_segments, runs
from shorts.schemas import Word

DIP = -38.0


def W(i, s, e, gaps=True):
    return Word(i=i, text=f"w{i}", start=s, end=e, start_gap=gaps, end_gap=gaps)


def db_for(words, n=300):
    db = np.full(n, -60.0, np.float32)
    for w in words:
        db[int(round(w.start / 0.01)):int(round(w.end / 0.01))] = -20.0
    return db


def spans(result):
    return [(s.first, s.last, s.t_in, s.t_out) for s in result.segments]


def test_runs():
    assert runs({1, 2, 3, 5, 7, 8}) == [(1, 3), (5, 5), (7, 8)]


def test_no_removal_is_one_segment_with_lead_and_tail():
    ws = [W(0, 0.5, 0.8), W(1, 0.85, 1.2), W(2, 1.25, 1.6)]
    r = build_segments(ws, set(), set(), db_for(ws), DIP, 3.0)
    assert spans(r) == [(0, 2, 0.45, 1.67)]


def test_removal_between_silences():
    ws = [W(0, 0.5, 1.0), W(1, 1.05, 1.3), W(2, 1.35, 2.0)]
    r = build_segments(ws, {1}, set(), db_for(ws), DIP, 3.0)
    assert spans(r) == [(0, 0, 0.45, 1.05), (2, 2, 1.3, 2.07)]
    assert r.kept_back == [] and r.warnings == []


def test_fused_filler_without_a_dip_is_kept():
    ws = [W(0, 0.2, 0.8, False), W(1, 0.8, 1.0, False), W(2, 1.0, 1.6, False)]
    db = np.full(300, -60.0, np.float32)
    db[20:160] = -20.0
    r = build_segments(ws, {1}, set(), db, DIP, 3.0)
    assert spans(r) == [(0, 2, 0.15, 1.67)]
    assert r.kept_back == [1] and "no clean cut point" in r.warnings[0]


def test_fused_filler_with_dips_is_cut_at_the_dips():
    ws = [W(0, 0.2, 0.8, False), W(1, 0.8, 1.0, False), W(2, 1.0, 1.6, False)]
    db = np.full(300, -60.0, np.float32)
    db[20:160] = -20.0
    db[79:82] = -50.0
    db[99:102] = -50.0
    r = build_segments(ws, {1}, set(), db, DIP, 3.0)
    assert [(s.first, s.last) for s in r.segments] == [(0, 0), (2, 2)]
    assert r.segments[0].t_out == pytest.approx(0.795, abs=0.011)
    assert r.segments[1].t_in == pytest.approx(0.995, abs=0.011)


def test_long_pause_keeps_200ms_inside_a_sentence_and_350ms_after_one():
    ws = [W(0, 0.5, 1.0), W(1, 2.0, 2.5)]
    r = build_segments(ws, set(), set(), db_for(ws), DIP, 3.0)
    assert spans(r) == [(0, 0, 0.45, 1.15), (1, 1, 1.95, 2.57)]          # 0.15 tail + 0.05 lead = 0.2 s
    ws[0] = ws[0].model_copy(update={"text": "done."})
    r = build_segments(ws, set(), set(), db_for(ws), DIP, 3.0)
    assert spans(r)[0][3] == pytest.approx(1.30)                         # 0.30 + 0.05 = 0.35 s after a sentence


def test_gap_to_keep_follows_punctuation():
    from shorts.plan.cuts import gap_to_keep
    assert (gap_to_keep("roti"), gap_to_keep("roti,"), gap_to_keep("roti?"), gap_to_keep("roti", True)) == (0.2, 0.25, 0.35, 0.6)


def test_short_pause_is_left_alone():
    ws = [W(0, 0.5, 1.0), W(1, 1.2, 1.7)]
    assert len(build_segments(ws, set(), set(), db_for(ws), DIP, 3.0).segments) == 1


def test_deliberate_pause_keeps_600ms():
    ws = [W(0, 0.5, 1.0), W(1, 2.0, 2.5)]
    r = build_segments(ws, set(), {0}, db_for(ws), DIP, 3.0)
    kept_silence = (r.segments[0].t_out - 1.0) + (2.0 - r.segments[1].t_in)
    assert kept_silence == pytest.approx(0.6)


def test_short_segment_is_merged_and_removal_restored():
    ws = [W(0, 0.5, 0.7), W(1, 0.75, 0.95), W(2, 1.0, 1.6), W(3, 1.65, 2.25)]
    r = build_segments(ws, {1}, set(), db_for(ws), DIP, 3.0)
    assert spans(r) == [(0, 3, 0.45, 2.32)]
    assert r.kept_back == [1] and "restored" in r.warnings[0]


def test_removing_every_word_is_refused():
    ws = [W(0, 0.5, 1.0), W(1, 1.05, 1.5)]
    r = build_segments(ws, {0, 1}, set(), db_for(ws), DIP, 3.0)
    assert len(r.segments) == 1 and "refused" in r.warnings[0]


def test_long_takes_split_at_sentence_ends_without_losing_time():
    from shorts.plan.cuts import Seg, split_for_zoom
    texts = ["a", "b.", "c", "d,", "e", "f.", "g", "h."]
    ws = [Word(i=i, text=t, start=i * 1.5, end=i * 1.5 + 1.2) for i, t in enumerate(texts)]
    out = split_for_zoom([Seg(0, 7, 0.0, 11.9)], ws)
    assert len(out) >= 2 and out[0].t_in == 0.0 and out[-1].t_out == 11.9
    assert all(a.t_out == b.t_in and a.last + 1 == b.first for a, b in zip(out, out[1:]))   # back to back
    assert all(ws[s.last].text[-1] in ".," for s in out[:-1])                                  # at a sentence/clause end
    assert all(s.t_out - s.t_in >= 2.5 for s in out)
    short = [Seg(0, 1, 0.0, 2.7)]
    assert split_for_zoom(short, ws) == short


def test_fast_pace_keeps_shorter_pauses_but_not_chopped():
    from shorts.plan.cuts import gap_to_keep
    fast = (gap_to_keep("roti", pace="fast"), gap_to_keep("roti,", pace="fast"), gap_to_keep("roti?", pace="fast"))
    assert fast == (0.17, 0.19, 0.26) and min(fast) > 0.12
    assert gap_to_keep("roti", True, "fast") == 0.6          # a deliberate pause stays deliberate


def test_fast_pace_trims_a_pause_the_normal_pace_keeps():
    ws = [W(0, 0.5, 0.8), W(1, 1.12, 1.4)]                   # 0.32 s gap inside a phrase
    assert len(build_segments(ws, set(), set(), db_for(ws), DIP, 3.0).segments) == 1
    assert len(build_segments(ws, set(), set(), db_for(ws), DIP, 3.0, pace="fast").segments) == 2


def test_teaser_segment_cuts_the_line_out_with_a_beat_after_it():
    from shorts.plan.cuts import teaser_segment
    ws = [W(0, 0.5, 0.8), W(1, 1.2, 1.5), W(2, 1.55, 1.9), W(3, 2.4, 2.7)]
    t = teaser_segment(ws, 1, 2, db_for(ws), DIP, 3.0)
    assert (t.first, t.last, t.t_in) == (1, 2, 1.15) and t.t_out == 2.2
