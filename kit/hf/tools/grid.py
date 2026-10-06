"""A frame of a screen recording (or a screenshot) with a labelled pixel grid, to read coordinates for HF.screen.

    python3 kit/hf/tools/grid.py <video|image> <seconds> [out.png] [--step=100] [--ocr]   (--ocr also boxes every text line)
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from locate import boxes, frame  # noqa: E402


def main():
    src, t = sys.argv[1], float(sys.argv[2])
    out = next((a for a in sys.argv[3:] if not a.startswith("--")), "grid.png")
    step = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--step=")), 100))
    f = frame(src, t)
    im = Image.open(f).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    try:
        font = ImageFont.truetype(str(Path(__file__).resolve().parents[2] / "fonts/Inter-700.ttf"), 14)
    except OSError:
        font = ImageFont.load_default()
    for x in range(0, im.width, step):
        d.line([(x, 0), (x, im.height)], fill=(226, 86, 43, 90 if x % (step * 5) else 170), width=1)
        d.text((x + 3, 3), str(x), fill=(226, 86, 43, 255), font=font)
    for y in range(0, im.height, step):
        d.line([(0, y), (im.width, y)], fill=(226, 86, 43, 90 if y % (step * 5) else 170), width=1)
        d.text((3, y + 3), str(y), fill=(226, 86, 43, 255), font=font)
    if "--ocr" in sys.argv:
        for ln in boxes(f):
            d.rectangle([ln["x"], ln["y"], ln["x"] + ln["w"], ln["y"] + ln["h"]], outline=(47, 138, 91, 220), width=2)
    im.save(out)
    print(f"{out}: {im.width}x{im.height}, grid every {step} px")


if __name__ == "__main__":
    main()
