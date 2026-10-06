import pytest

from shorts.plan.cuts import Seg
from shorts.plan.zoom import EYE_K, TOP_K, assign_zoom, crop_for, face_center, face_frame
from shorts.schemas import Sentence


def test_no_crop_at_zoom_one():
    assert crop_for(1.0, (540, 768)) is None


def test_crop_zooms_about_the_face_so_it_stays_in_place():
    assert crop_for(1.08, (540, 768)) == [1000, 1778, 40, 56]      # face centre keeps its spot in the frame


def test_crop_stays_inside_the_frame_and_even():
    assert crop_for(1.08, (1050, 100)) == [1000, 1778, 78, 8]
    assert crop_for(1.15, (0, 1920)) == [940, 1670, 0, 250]


def test_face_center_is_the_median_face():
    track = [[400, 500, 300, 360], None, [420, 520, 300, 360], [410, 510, 300, 360]]
    x, y = face_center(track, 2.0, 0.0, 2.0)
    assert x == 560 and y == 510 + 0.45 * 360


def test_short_pieces_keep_the_framing():
    segs = [Seg(0, 1, 0, 2), Seg(2, 3, 2.5, 3.3), Seg(4, 5, 4, 6)]            # the middle piece is 0.8 s
    # the 0.8 s piece opens a new thought but keeps the framing; the next new thought gets the other framing
    sents = [Sentence(id="s1", first=0, last=1, text="", start=0, end=2),
             Sentence(id="s2", first=2, last=3, text="", start=2.5, end=3.3),
             Sentence(id="s3", first=4, last=5, text="", start=4, end=6)]
    assert [z for z, _ in assign_zoom(segs, sents, set(), [], 2.0, 1.15, 1.3)] == [1.0, 1.0, 1.15]


def test_framing_changes_at_new_thoughts_not_on_every_cut():
    segs = [Seg(0, 1, 0, 1.5), Seg(2, 3, 2, 3.5), Seg(4, 5, 4, 5.5), Seg(6, 7, 6, 7.5)]
    sents = [Sentence(id="s1", first=0, last=3, text="", start=0, end=2.5),
             Sentence(id="s2", first=4, last=7, text="", start=3, end=5.5)]
    zs = [z for z, _ in assign_zoom(segs, sents, set(), [], 2.0, 1.15, 1.3)]
    assert zs == [1.0, 1.0, 1.15, 1.15]                    # a mid-sentence cut keeps the framing (a plain jump cut)
    zs = [z for z, _ in assign_zoom(segs, sents, {"s2"}, [], 2.0, 1.15, 1.3)]
    assert zs == [1.0, 1.0, 1.3, 1.0]                      # punch in on the sentence, cut back out after it


def test_a_long_hold_changes_at_the_next_cut():
    segs = [Seg(0, 1, 0, 2.5), Seg(2, 3, 2.5, 5.0), Seg(4, 5, 5.0, 7.0)]       # one long sentence, split for zoom
    sents = [Sentence(id="s1", first=0, last=5, text="", start=0, end=7)]
    assert [z for z, _ in assign_zoom(segs, sents, set(), [], 2.0, 1.15, 1.3)] == [1.0, 1.0, 1.15]


def test_cut_back_from_a_punch_is_never_a_glitch_step():
    segs = [Seg(0, 1, 0, 2), Seg(2, 3, 2, 4), Seg(4, 5, 4, 6), Seg(6, 7, 6, 8)]
    sents = [Sentence(id=f"s{k}", first=2 * k, last=2 * k + 1, text="", start=2 * k, end=2 * k + 2) for k in range(4)]
    zs = [z for z, _ in assign_zoom(segs, sents, {"s2"}, [], 2.0, 1.2, 1.28)]
    # 1.2 -> 1.28 is under 1.1x: the punch goes further; the cut back out of it skips the framing within 1.1x
    assert zs[1] == 1.2 and zs[2] == pytest.approx(1.32) and zs[3] == 1.0


def test_recompose_puts_the_eyes_on_the_upper_third():
    track = [[340, 500, 400, 520]] * 4                                       # eyes at 687 (36% of the height)
    eye, top = face_frame(track, 2.0, 0.0, 2.0)
    assert eye == 500 + EYE_K * 520 and top == 500 - TOP_K * 520
    cw, ch, x, y = crop_for(1.15, (540, 734), (eye, top))
    assert (eye - y) * 1920 / ch == pytest.approx(1920 / 3, abs=2)          # eyes on the third line
    assert crop_for(1.3, (540, 500), (300, 120))[3] == 0                     # a face near the top: clamped to the edge
