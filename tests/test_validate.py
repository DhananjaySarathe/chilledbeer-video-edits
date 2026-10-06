import pytest

from shorts import cli, config
from shorts.plan.validate import validate_edit
from shorts.schemas import AudioSpec, CaptionPage, Captions, CaptionWord, EditFile, OutputSpec, Segment

needs_font = pytest.mark.skipif(not (config.FONTS / "Montserrat-800.ttf").exists(),
                                reason="run `uv run shorts setup` first")


def captions(**kw):
    base = dict(template="bold_pop", font="Montserrat-800.ttf", font_size=88, text_color="#FFFFFF",
                highlight_color="#FFD400", outline_color="#000000", outline_px=6, shadow_px=0, spacing=0.0,
                uppercase=True, center_x=507.6, center_y=1152.0, max_width=853.6,
                pages=[CaptionPage(start=0.0, end=0.5, words=[CaptionWord(text="HI", start=0.0, end=0.4)])])
    return Captions(**(base | kw))


def edit(**kw):
    base = dict(source="in.mp4", source_frames=300, output=OutputSpec(fps=30),
                segments=[Segment(in_frame=0, out_frame=30, first_word=0, last_word=0),
                          Segment(in_frame=60, out_frame=90, first_word=1, last_word=1, zoom=1.08,
                                  crop=[1000, 1778, 40, 22])],
                captions=captions(), audio=AudioSpec(), duration=2.0)
    return EditFile(**(base | kw))


def seg(a, b, **kw):
    return Segment(in_frame=a, out_frame=b, first_word=0, last_word=0, **kw)


@needs_font
def test_a_good_edit_passes():
    assert validate_edit(edit()) == []


@needs_font
def test_overlap_bounds_and_duration():
    problems = " ".join(validate_edit(edit(segments=[seg(0, 30), seg(20, 400)], duration=2.0)))
    assert "overlaps" in problems and "outside the source" in problems and "duration" in problems


@needs_font
def test_crop_must_fit():
    problems = validate_edit(edit(segments=[seg(0, 30), seg(60, 90, zoom=1.08, crop=[1000, 1778, 100, 22])]))
    assert any("crop" in p for p in problems)


@needs_font
def test_captions_must_stay_in_the_safe_zone_and_fit():
    assert any("vertical safe zone" in p for p in validate_edit(edit(captions=captions(center_y=1300.0))))
    wide = [CaptionPage(start=0.0, end=0.5, words=[CaptionWord(text="EXTRAORDINARILY LONGWINDED", start=0, end=0.4)])]
    assert any("wide" in p for p in validate_edit(edit(captions=captions(pages=wide))))


def test_schema_edit_command(capsys):
    assert cli.main(["schema", "edit"]) == 0
    assert '"segments"' in capsys.readouterr().out
