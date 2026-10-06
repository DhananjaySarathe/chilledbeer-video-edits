import shutil
import subprocess

import cv2
import numpy as np
import pytest

from shorts import config, fonts
from shorts.render.ass import ass_bgr, ass_color, ass_time, build_ass
from shorts.schemas import CaptionPage, Captions, CaptionWord

TTF = config.FONTS / "Montserrat-800.ttf"
needs_font = pytest.mark.skipif(not TTF.exists(), reason="run `uv run shorts setup` first")


def caps(template="bold_pop", **kw):
    base = dict(template=template, font="Montserrat-800.ttf", font_size=88, text_color="#FFFFFF",
                highlight_color="#FFD400", outline_color="#000000", outline_px=6, shadow_px=0, spacing=0.0,
                uppercase=True, center_x=507.6, center_y=1152.0, max_width=853.6,
                pages=[CaptionPage(start=0.5, end=1.3, words=[CaptionWord(text="THIS", start=0.5, end=0.8),
                                                             CaptionWord(text="WORKS", start=0.85, end=1.25,
                                                                         highlight=True)])])
    return Captions(**(base | kw))


def dialogue(ass):
    return [line for line in ass.splitlines() if line.startswith("Dialogue:")]


def test_colours_and_times():
    assert ass_color("#FFD400") == "&H0000D4FF"
    assert ass_color("#FFFFFF", 0x80) == "&H80FFFFFF"
    assert ass_bgr("#FFD400") == "&H00D4FF&"
    assert ass_time(61.234) == "0:01:01.23"


def test_bold_pop_event():
    ass = build_ass(caps(), "Montserrat ExtraBold")
    assert "Style: Cap,Montserrat ExtraBold,88,&H00FFFFFF,&H00FFFFFF," in ass
    line = dialogue(ass)[0]
    assert line.startswith(r"Dialogue: 0,0:00:00.50,0:00:01.30,Cap,,0,0,0,,{\pos(507.6,1152)\fscx88\fscy88")
    assert r"\t(0,90,\fscx108\fscy108)\t(90,160,\fscx100\fscy100)}THIS " in line
    assert line.endswith(r"{\c&H00D4FF&}WORKS{\c&HFFFFFF&}")


def test_karaoke_event_times_each_word():
    ass = build_ass(caps("clean_karaoke"), "Montserrat ExtraBold")
    assert "Style: Cap,Montserrat ExtraBold,88,&H00FFFFFF,&H80FFFFFF," in ass
    line = dialogue(ass)[0]
    assert line.endswith(r"{\pos(507.6,1152)\fscx100\fscy100}{\k35}THIS {\k40\1c&H00D4FF&}WORKS{\1c&HFFFFFF&}")


def test_page_scale_shrinks_the_pop():
    page = CaptionPage(start=0.0, end=1.0, scale=0.5, words=[CaptionWord(text="LONG", start=0.0, end=1.0)])
    assert r"\fscx44\fscy44" in dialogue(build_ass(caps(pages=[page]), "X"))[0]


@pytest.mark.slow
@needs_font
def test_libass_uses_the_kit_font_at_the_expected_width(tmp_path):
    (tmp_path / "fonts").mkdir()
    shutil.copy2(TTF, tmp_path / "fonts" / TTF.name)
    page = CaptionPage(start=0.0, end=2.0, words=[CaptionWord(text="HELLO", start=0.0, end=1.0),
                                                  CaptionWord(text="WORLD", start=1.0, end=2.0)])
    cap = caps(font_size=100, outline_px=0, center_x=540.0, center_y=960.0, pages=[page])
    (tmp_path / "c.ass").write_text(build_ass(cap, fonts.full_name(TTF)))
    proc = subprocess.run(["ffmpeg", "-v", "verbose", "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=1",
                           "-vf", "subtitles=filename=c.ass:fontsdir=fonts", "-ss", "0.5", "-frames:v", "1", "out.png"],
                          cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "Montserrat-800.ttf" in proc.stderr            # libass picked our font, not a system fallback
    img = cv2.imread(str(tmp_path / "out.png"), cv2.IMREAD_GRAYSCALE)
    cols = np.where((img > 128).any(axis=0))[0]
    assert cols[-1] - cols[0] + 1 == pytest.approx(fonts.text_width(TTF, "HELLO WORLD", 100), rel=0.12)
