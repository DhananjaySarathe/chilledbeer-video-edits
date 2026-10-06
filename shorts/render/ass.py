"""Captions as an ASS subtitle file, drawn by ffmpeg's libass: no browser, no extra installs."""
from __future__ import annotations

from shorts import config
from shorts.schemas import CaptionPage, Captions

POP_MS = (90, 160)       # bold_pop: grow to 108% by 90 ms, settle at 100% by 160 ms
KARAOKE_DIM = 0x80       # clean_karaoke: words not yet spoken are drawn at half opacity

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{primary},{secondary},{outline},{back},0,0,0,0,100,100,{spacing},0,1,{outline_px},{shadow_px},5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR for style lines (alpha 00 is opaque)."""
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_bgr(hex_rgb: str) -> str:
    """#RRGGBB -> &HBBGGRR& for colour override tags inside dialogue text."""
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H{b}{g}{r}&".upper()


def ass_time(t: float) -> str:
    cs = int(round(max(t, 0.0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _bold_pop(cap: Captions, page: CaptionPage, pos: str) -> str:
    s = page.scale * 100
    grow, settle = POP_MS
    head = (f"{{{pos}\\fscx{s * 0.88:.0f}\\fscy{s * 0.88:.0f}\\t(0,{grow},\\fscx{s * 1.08:.0f}\\fscy{s * 1.08:.0f})"
            f"\\t({grow},{settle},\\fscx{s:.0f}\\fscy{s:.0f})}}")
    hl, base = ass_bgr(cap.highlight_color), ass_bgr(cap.text_color)
    return head + " ".join(f"{{\\c{hl}}}{w.text}{{\\c{base}}}" if w.highlight else w.text for w in page.words)


def _karaoke(cap: Captions, page: CaptionPage, pos: str) -> str:
    s = page.scale * 100
    hl, base = ass_bgr(cap.highlight_color), ass_bgr(cap.text_color)
    out = [f"{{{pos}\\fscx{s:.0f}\\fscy{s:.0f}}}"]

    def cum(t: float) -> int:          # centiseconds since the page appeared
        return int(round((t - page.start) * 100))

    prev = max(cum(page.words[0].start), 0)
    if prev:
        out.append(f"{{\\k{prev}}}")
    for k, w in enumerate(page.words):
        last = k + 1 == len(page.words)
        c = max(cum(w.end if last else page.words[k + 1].start), prev)
        out.append(f"{{\\k{c - prev}\\1c{hl}}}{w.text}{{\\1c{base}}}" if w.highlight else f"{{\\k{c - prev}}}{w.text}")
        if not last:
            out.append(" ")
        prev = c
    return "".join(out)


def build_ass(cap: Captions, font_name: str) -> str:
    dim = KARAOKE_DIM if cap.template == "clean_karaoke" else 0
    head = HEADER.format(w=config.OUT_W, h=config.OUT_H, font=font_name, size=cap.font_size,
                         primary=ass_color(cap.text_color), secondary=ass_color(cap.text_color, dim),
                         outline=ass_color(cap.outline_color), back=ass_color("#000000", 0x80),
                         spacing=f"{cap.spacing:g}", outline_px=cap.outline_px, shadow_px=cap.shadow_px)
    pos = f"\\pos({cap.center_x:g},{cap.center_y:g})"
    draw = _bold_pop if cap.template == "bold_pop" else _karaoke
    events = [f"Dialogue: 0,{ass_time(p.start)},{ass_time(p.end)},Cap,,0,0,0,,{draw(cap, p, pos)}"
              for p in cap.pages if p.words]
    return head + "\n".join(events) + "\n"
