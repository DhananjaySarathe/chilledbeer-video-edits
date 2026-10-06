"""The reel (9:16 teaser for the long video): the strongest lines from the same take, in a new order, then a few
seconds of the launch film, then the CTA. Same cutting rules as ../edl.py (word-end padding, 25 ms fades, 1.07x).

    python3 reel_edl.py      -> edl.json here; vo.wav, aroll.mp4 + aroll.map.json in the reel's temp work folder
                                (kit/paths.py; then graded by kit/look/grade.py)
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from edl import FIX, LEAD, SPEED, SR, FPS, VOICE, VOICE_CLEAN, SRC, TRACK, JOB, tail_pad  # noqa: E402
from kit.paths import Film  # noqa: E402  (edl put the repo root on sys.path)

F = Film(__file__)

GAP = 0.10                     # breath between the reel's lines
KEEP = [(28, 36, "hook"), (144, 164, "built"), (514, 531, "lost"), (534, 538, "again"), (556, 568, "minutes")]
LAUNCH_CLIP = 5.648            # seconds of the long video's launch film (4 shots), placed after "minutes"
CTA = (713, 730, "cta")
END = 1.6


def main():
    words = json.load(open(JOB / "analysis.json"))["words"]
    pieces, out_words, t = [], [], 0.0

    def place(a, b, tag):
        nonlocal t
        run = words[a:b + 1]
        sa = np.ceil(max(0.0, run[0]["start"] - LEAD) * FPS) / FPS
        sb = np.floor((run[-1]["end"] + tail_pad(run[-1]["text"])) * FPS) / FPS
        dur = (sb - sa) / SPEED
        pieces.append({"tag": tag, "src_a": round(sa, 4), "src_b": round(sb, 4), "out_a": round(t, 4), "out_b": round(t + dur, 4)})
        for w in run:
            out_words.append({"i": w["i"], "text": FIX.get(w["i"], w["text"]), "tag": tag,
                              "t": round(t + (w["start"] - sa) / SPEED, 3), "e": round(t + (w["end"] - sa) / SPEED, 3)})
        t += dur + GAP

    for a, b, tag in KEEP:
        place(a, b, tag)
    launch = [round(t, 3), round(t + LAUNCH_CLIP, 3)]
    t += LAUNCH_CLIP + 0.15
    place(*CTA)
    total = round(t - GAP + END, 3)
    track = json.load(open(TRACK))
    for p in pieces:
        fs = track[int(p["src_a"] * FPS):max(int(p["src_a"] * FPS) + 1, int(p["src_b"] * FPS))]
        p["face"] = [round(float(np.median([f[i] for f in fs])), 1) for i in range(3)]
    (HERE / "edl.json").write_text(json.dumps({"total": total, "launch": launch, "pieces": pieces, "words": out_words}, indent=0))
    # voice
    n = int(total * SR)
    vo = np.zeros(n, np.float32)
    full = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(VOICE), "-af", VOICE_CLEAN, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                                        capture_output=True, check=True).stdout, np.float32)
    for p in pieces:
        x = full[int(p["src_a"] * SR):int(p["src_b"] * SR)]
        y = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", "-af",
                                          f"atempo={SPEED},afade=t=in:d=0.025:curve=hsin,areverse,afade=t=in:d=0.025:curve=hsin,areverse", "-f", "f32le", "-"],
                                         input=x.tobytes(), capture_output=True, check=True).stdout, np.float32)
        i = int(p["out_a"] * SR)
        vo[i:i + len(y)] += y[: n - i]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", "-c:a", "pcm_s24le", str(F.work / "vo.wav")],
                   input=vo.tobytes(), check=True)
    # picture: every reel frame takes its piece's source frame (gaps / launch / end hold the nearest piece; they're covered)
    need = []
    for k in range(int(round(total * FPS))):
        tt = (k + 0.5) / FPS
        p = next((q for q in pieces if q["out_a"] <= tt < q["out_b"]), None)
        if p is None:
            p = min(pieces, key=lambda q: min(abs(q["out_a"] - tt), abs(q["out_b"] - tt)))
            src = p["src_b"] - 0.5 / FPS if tt >= p["out_b"] else p["src_a"]
        else:
            src = p["src_a"] + (tt - p["out_a"]) * SPEED
        need.append(int(src * FPS))
    W, H = 1920, 1080
    order = sorted(set(need))
    frames = {}
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(SRC), "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    idx, want = -1, set(order)
    while idx < order[-1]:
        buf = dec.stdout.read(W * H * 3)
        if len(buf) < W * H * 3:
            break
        idx += 1
        if idx in want:
            frames[idx] = buf
    dec.kill()
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            "-c:v", "libx264", "-crf", "12", "-preset", "medium", "-pix_fmt", "yuv420p", str(F.work / "aroll.mp4")], stdin=subprocess.PIPE)
    for f in need:
        enc.stdin.write(frames[f])
    enc.stdin.close(); enc.wait()
    (F.work / "aroll.map.json").write_text(json.dumps(need))
    print(f"reel: {len(pieces)} pieces, total {total:.2f} s, launch {launch}")


if __name__ == "__main__":
    main()
