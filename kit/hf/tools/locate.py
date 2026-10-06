"""Find on-screen text in a screen recording or screenshot and print its box in source pixels, for HF.screen
annotations (zoom / highlight / arrow / cursor targets). Uses kit/bin/ocrboxes (Apple Vision, on-device).

    python3 kit/hf/tools/locate.py <video|image> <seconds> "Render"            -> [x, y, w, h] of the best match
    python3 kit/hf/tools/locate.py rec.mp4 12.5 "Pull requests" --all --pad=8  -> every match, padded
    python3 kit/hf/tools/locate.py rec.mp4 12.5 --dump                         -> every text line with its box
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BIN = Path(__file__).resolve().parents[2] / "bin/ocrboxes"


def frame(src: str, t: float) -> Path:
    if src.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        return Path(src)
    out = Path(tempfile.mkdtemp(prefix="locate_")) / "f.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", str(out)], check=True)
    return out


def boxes(img: Path) -> list[dict]:
    out = subprocess.run([str(BIN), str(img)], capture_output=True, text=True, check=True).stdout
    return [json.loads(l) for l in out.splitlines() if l.strip()]


def find(lines: list[dict], query: str) -> list[dict]:
    q = query.lower().strip()
    hits = []
    for ln in lines:
        words = ln.get("words") or []
        for i in range(len(words)):                                   # consecutive words that spell the query
            for j in range(i, min(len(words), i + 8)):
                s = " ".join(w["text"] for w in words[i:j + 1]).lower()
                if s == q or (j == i and q in s and len(q) >= 3):
                    ws = words[i:j + 1]
                    x0, y0 = min(w["x"] for w in ws), min(w["y"] for w in ws)
                    x1, y1 = max(w["x"] + w["w"] for w in ws), max(w["y"] + w["h"] for w in ws)
                    hits.append({"text": " ".join(w["text"] for w in ws), "box": [x0, y0, x1 - x0, y1 - y0], "exact": s == q})
        if q in ln["text"].lower() and not any(h["text"].lower() == q for h in hits):
            hits.append({"text": ln["text"], "box": [ln["x"], ln["y"], ln["w"], ln["h"]], "exact": ln["text"].lower() == q})
    hits.sort(key=lambda h: (not h["exact"], h["box"][1], h["box"][0]))
    return hits


def main():
    src, t = sys.argv[1], float(sys.argv[2])
    flags = [a for a in sys.argv[3:] if a.startswith("--")]
    query = next((a for a in sys.argv[3:] if not a.startswith("--")), None)
    pad = int(next((f.split("=")[1] for f in flags if f.startswith("--pad=")), 0))
    lines = boxes(frame(src, t))
    if "--dump" in flags or not query:
        for ln in lines:
            print(json.dumps({"text": ln["text"], "box": [ln["x"], ln["y"], ln["w"], ln["h"]]}))
        return
    hits = find(lines, query)
    if not hits:
        raise SystemExit(f"'{query}' not found at {t}s ({len(lines)} text lines on screen; try --dump)")
    for h in hits if "--all" in flags else hits[:1]:
        x, y, w, hh = h["box"]
        print(json.dumps({"text": h["text"], "box": [x - pad, y - pad, w + 2 * pad, hh + 2 * pad]}))


if __name__ == "__main__":
    main()
