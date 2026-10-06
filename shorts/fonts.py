"""Font facts needed to lay out captions: the name libass matches, and text width in pixels."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont

from shorts import config
from shorts.errors import ShortsError


def font_path(name: str) -> Path:
    p = config.FONTS / name
    if not p.is_file():
        raise ShortsError("E_FONT", f"Font {name!r} not found in kit/fonts.",
                          "Pick one listed by `shorts doctor` (fonts), or run `shorts setup`.")
    return p


@lru_cache(maxsize=32)
def _font(path: str) -> TTFont:
    return TTFont(path, lazy=True)


def full_name(path: Path) -> str:
    """Name ID 4 (full name), e.g. 'Montserrat ExtraBold'. libass matches this in ASS Fontname."""
    return _font(str(path))["name"].getDebugName(4)


def em_px(path: Path, font_size: float) -> float:
    """libass (like VSFilter) scales a font so usWinAscent + usWinDescent equals the ASS font size."""
    f = _font(str(path))
    upm = f["head"].unitsPerEm
    os2 = f["OS/2"] if "OS/2" in f else None
    height = (os2.usWinAscent + os2.usWinDescent) if os2 is not None and os2.usWinAscent else (f["hhea"].ascent - f["hhea"].descent)
    return font_size * upm / height


def text_width(path: Path, text: str, font_size: float, spacing: float = 0.0) -> float:
    f = _font(str(path))
    cmap = f.getBestCmap()
    hmtx = f["hmtx"].metrics
    fallback = cmap.get(ord("M"))
    units = sum(hmtx[cmap.get(ord(ch), fallback)][0] for ch in text)
    return units * em_px(path, font_size) / f["head"].unitsPerEm + spacing * max(len(text) - 1, 0)


def available() -> list[str]:
    return sorted(p.name for p in config.FONTS.glob("*.ttf"))
