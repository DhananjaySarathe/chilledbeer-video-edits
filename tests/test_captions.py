import pytest

from shorts import config
from shorts.plan.captions import display_text, layout_captions, place
from shorts.plan.cuts import Seg
from shorts.schemas import FaceBox, Style, Word

needs_font = pytest.mark.skipif(not (config.FONTS / "Montserrat-800.ttf").exists(),
                                reason="run `uv run shorts setup` first")


def words_from(spec):
    return [Word(i=i, text=t, start=s, end=e) for i, (t, s, e) in enumerate(spec)]


def one_segment(words):
    return [Seg(0, len(words) - 1, 0.0, words[-1].end + 0.2)], [0.0]


def texts(cap):
    return [[w.text for w in p.words] for p in cap.pages]


def test_display_text():
    assert display_text("Hello,", True) == "HELLO"
    assert display_text("{sneaky}", False) == "sneaky"
    assert display_text("—", True) == ""


@needs_font
def test_two_word_pages_break_at_sentence_ends():
    ws = words_from([("Hi.", 0.0, 0.3), ("This", 0.35, 0.5), ("is", 0.55, 0.7), ("my", 0.75, 0.9), ("app", 0.95, 1.3)])
    cap, _ = layout_captions(*one_segment(ws), ws, set(), {}, Style(), None)
    assert texts(cap) == [["HI"], ["THIS", "IS"], ["MY", "APP"]]
    assert cap.pages[0].end == pytest.approx(0.35)      # the next page follows within 0.35 s
    assert cap.pages[-1].end == pytest.approx(1.45)     # last word end + 0.15 s hold


@needs_font
def test_silence_starts_a_page_and_highlights_and_overrides_apply():
    ws = words_from([("so", 0.0, 0.2), ("good", 0.8, 1.1)])
    cap, _ = layout_captions(*one_segment(ws), ws, {1}, {0: "toh"}, Style(), None)
    assert texts(cap) == [["TOH"], ["GOOD"]]
    assert cap.pages[1].words[0].highlight and not cap.pages[0].words[0].highlight
    assert cap.pages[0].end == pytest.approx(0.35)


@needs_font
def test_times_follow_the_cut_timeline():
    ws = words_from([("one", 0.5, 0.8), ("two", 0.85, 1.1), ("three", 3.0, 3.4)])
    segs = [Seg(0, 1, 0.45, 1.17), Seg(2, 2, 2.95, 3.47)]
    cap, _ = layout_captions(segs, [0.0, 0.72], ws, set(), {}, Style(words_per_page=1), None)
    assert [p.words[0].start for p in cap.pages] == pytest.approx([0.05, 0.40, 0.77])


@needs_font
def test_a_very_long_word_is_scaled_down():
    ws = words_from([("Supercalifragilisticexpialidocious", 0.0, 1.0)])
    cap, _ = layout_captions(*one_segment(ws), ws, set(), {}, Style(font_size=120), None)
    assert cap.pages[0].scale < 1.0


def test_captions_move_off_the_face():
    style = Style(position_y=0.55)
    _, cy, warn = place(style, FaceBox(x=340, y=900, w=400, h=400), zoom=1.0)
    assert cy <= 900 - 20 and warn == []
    _, cy, _ = place(style, None, 1.0)
    assert cy == pytest.approx(0.55 * 1920)


def test_close_selfie_face_puts_captions_at_the_least_overlap():
    style = Style()                                       # position_y 0.60 lands on the chin of a close selfie
    _, cy, warn = place(style, FaceBox(x=235, y=412, w=518, h=688), zoom=1.3)        # at the default punch-in
    # the recomposed punch-in (eyes on the third) lifts the face: the forehead now overlaps less than the chin
    assert cy == pytest.approx(0.14 * 1920 + (88 * 1.3 + 12) / 2, abs=0.1)          # highest safe position
    assert len(warn) == 1 and "of the face" in warn[0]                               # and it says so


@needs_font
def test_a_multi_word_override_lights_up_word_by_word():
    ws = words_from([("focus", 0.0, 0.4), ("increased,", 0.5, 1.3)])
    cap, _ = layout_captions(*one_segment(ws), ws, set(), {1: "badh gaya"}, Style(words_per_page=3), None)
    words = [w for p in cap.pages for w in p.words]
    assert [w.text for w in words] == ["FOCUS", "BADH", "GAYA"]
    assert words[1].start == pytest.approx(0.5) and words[2].end == pytest.approx(1.3)
    assert words[1].end == pytest.approx(words[2].start) and words[1].end == pytest.approx(0.9)
