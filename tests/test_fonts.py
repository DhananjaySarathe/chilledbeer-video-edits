import pytest

from shorts import config, fonts
from shorts.errors import ShortsError

TTF = config.FONTS / "Montserrat-800.ttf"
needs_font = pytest.mark.skipif(not TTF.exists(), reason="run `uv run shorts setup` first")


@needs_font
def test_full_name_is_readable():
    assert "Montserrat" in fonts.full_name(TTF)


@needs_font
def test_width_scales_linearly_with_size():
    w1 = fonts.text_width(TTF, "HELLO WORLD", 50)
    w2 = fonts.text_width(TTF, "HELLO WORLD", 100)
    assert w1 > 0
    assert w2 == pytest.approx(2 * w1, rel=1e-6)


@needs_font
def test_longer_text_is_wider():
    assert fonts.text_width(TTF, "HELLO WORLD", 80) > fonts.text_width(TTF, "HELLO", 80)


def test_missing_font_raises():
    with pytest.raises(ShortsError) as e:
        fonts.font_path("Nope.ttf")
    assert e.value.code == "E_FONT"
