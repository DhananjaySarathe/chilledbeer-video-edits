"""Blur everything private in the Claude desktop screenshot: session titles (client/project names), branch chips,
and the conversation text of every panel except this video's own session (bottom right), whose body stays readable.
Window chrome, model labels and spinners stay, so it still reads as eight agents at work.

    python3 blur_sessions.py      -> assets/sessions_blurred.png (2000x1266)

The raw screenshot (private) stays in the film's temp work folder, never in films/ or git; only the blurred copy is kept.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "kit/paths.py").exists())
sys.path.insert(0, str(ROOT))
from kit.paths import Film  # noqa: E402

F = Film(__file__)
(HERE / "assets").mkdir(exist_ok=True)
im = Image.open(F.work / "sessions_raw.png").convert("RGB")
# exact layout of this screenshot: columns 1, 2 and 4 hold two panels; column 3 is one tall panel
boxes = [
    # session titles (project / client names)
    (60, 24, 360, 56), (600, 24, 760, 56), (1030, 24, 1200, 56), (1470, 24, 1700, 56),
    (40, 526, 300, 558), (598, 526, 760, 558), (1470, 526, 1700, 558),
    # conversation text
    (18, 60, 536, 332), (572, 60, 968, 362), (1004, 60, 1410, 1126), (1446, 60, 1984, 362),
    (18, 562, 536, 1124), (572, 562, 968, 1124),
    # branch chips (labels and counts)
    (24, 326, 345, 362), (30, 380, 196, 412), (584, 380, 664, 412), (1018, 1134, 1104, 1166),
    (30, 1134, 224, 1166), (1466, 1036, 1606, 1086),
]
for b in boxes:
    region = im.crop(b)
    region = region.filter(ImageFilter.GaussianBlur(9)).filter(ImageFilter.GaussianBlur(6))
    im.paste(region, b)
im.save(HERE / "assets/sessions_blurred.png")
# a review copy with the blurred boxes outlined
rv = im.copy(); d = ImageDraw.Draw(rv)
for b in boxes:
    d.rectangle(b, outline=(255, 60, 60), width=2)
rv.save(F.work / "sessions_blur_review.png")
print(len(boxes), "regions blurred")
