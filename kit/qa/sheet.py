"""Review sheets from a rendered video, for a fresh critic that sees only the output (never the build notes).

  overview.jpg  first 2 s and last 2 s (every 0.5 s) + one frame every 3 s, timecoded
  seams.jpg     each cut at -0.12 s / at the cut / +0.12 s (only with --cuts), so jump frames and flashes show

    python3 kit/qa/sheet.py final.mp4 out_dir [--cuts=cuts.json] [--every=3] [--width=320]
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw


def arg(name, default=None):
    return next((a.split("=", 1)[1] for a in sys.argv if a.startswith(f"--{name}=")), default)


def grab(video, t, width):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:-2",
                          "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
    from io import BytesIO
    return Image.open(BytesIO(raw)).convert("RGB") if raw else None


def tile(frames, cols, path):
    frames = [(lab, im) for lab, im in frames if im is not None]
    if not frames:
        return
    w, h = frames[0][1].size
    rows = -(-len(frames) // cols)
    sheet = Image.new("RGB", (cols * (w + 4) + 4, rows * (h + 22) + 4), "white")
    d = ImageDraw.Draw(sheet)
    for k, (lab, im) in enumerate(frames):
        x, y = 4 + (k % cols) * (w + 4), 4 + (k // cols) * (h + 22)
        sheet.paste(im, (x, y + 18))
        d.text((x + 2, y + 2), lab, fill="black")
    sheet.save(path, quality=88)


def main():
    video, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    every, width = float(arg("every", 3)), int(arg("width", 320))
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                               capture_output=True, text=True).stdout)
    ts = sorted({round(t, 2) for t in [x * 0.5 for x in range(5)] + [dur - 2 + x * 0.5 for x in range(4)] + [k * every for k in range(int(dur / every) + 1)]
                 if 0 <= t < dur})
    tile([(f"{t:6.2f}s", grab(video, t, width)) for t in ts], 6, out / "overview.jpg")
    if arg("cuts"):
        frames = []
        for c in json.load(open(arg("cuts"))):
            for o in (-0.12, 0.0, 0.12):
                frames.append((f"cut {c:.2f} {o:+.2f}", grab(video, c + o, width)))
        tile(frames, 6, out / "seams.jpg")
    print(f"sheets in {out}: overview ({len(ts)} frames)" + (" + seams" if arg("cuts") else ""))


if __name__ == "__main__":
    main()
