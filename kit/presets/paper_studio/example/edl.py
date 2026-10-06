"""Edit list for "How I edit my videos with Claude": kept word ranges from the take, cut with the EDITING.md rules.

  - an edge is padded by how the word sounds at its end (vowel +30 ms, sibilant +120 ms, other +50 ms), 40 ms lead-in
  - inside a kept range a pause longer than 0.30 s is shortened to a natural ~0.12 s sliver
  - 25 ms smooth (hsin) fades on every splice, talking plays 1.07x
  - outputs: edl.json and cuts.json here (the edit decisions, small, in git); vo.wav (cleaned voice), aroll.mp4 (the cut
    picture) and aroll.map.json in the film's temp work folder (kit/paths.py: output/temp/films/<name>/work)

    python3 edl.py
    python3 ../../kit/look/grade.py $W/aroll.mp4 $W/aroll_graded.mp4 --track=$T/source.face.json --map=$W/aroll.map.json
        (W = the film's work folder, T = the take's temp folder: python3 build.py --paths)
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "kit/paths.py").exists())
sys.path.insert(0, str(ROOT))
from kit.paths import Film, job_dir, job_source, job_temp  # noqa: E402

TAKE = "howiedit"
F = Film(__file__)
JOB = job_dir(TAKE)                                  # analysis.json (word timings)
SRC = job_source(TAKE)
TRACK = job_temp(TAKE) / "source.face.json"          # the head track of the take (kit/look/grade.py --track-only)
VOICE = job_temp(TAKE) / "voice_raw_DeepFilterNet3.wav"   # DeepFilterNet3 of the take's audio (free, local)
SR, FPS, SPEED = 48000, 30, 1.07
LEAD = 0.04
SLIVER, MAX_GAP = 0.12, 0.30
HOOK = 0.0                     # no title card: the video opens on the speaker
LAUNCH = 7 * 2 * 0.706         # the launch film at the end: 7 shots of 2 beats of the launch track (85 BPM) = 9.9 s
ENDCARD = 3.5
# the room is noisy (speech -36 dB over a -54 dB floor): DeepFilterNet already removed it (keeps the highs, no musical
# noise); this is only the voice chain
VOICE_CLEAN = ("highpass=f=80,"
               "equalizer=f=220:t=q:w=1:g=-2,equalizer=f=3200:t=q:w=1.2:g=3,equalizer=f=9000:t=h:w=1:g=1.5,"
               "acompressor=threshold=-26dB:ratio=3:attack=6:release=110:makeup=4,loudnorm=I=-19:TP=-3:LRA=7")

# (first word, last word, tag). Tags name the moments the graphics key off.
KEEP = [
    (1, 14, "hello"), (28, 36, "noeditor"), (37, 68, "magic"), (69, 84, "workflow"), (85, 113, "screen"),
    (114, 122, "weekend"), (134, 142, "weekend"), (143, 164, "aieditor"), (165, 170, "whole"),
    (193, 195, "record"), (199, 205, "record"), (206, 215, "cleanup"), (221, 227, "skill"), (229, 237, "skill"),
    (238, 242, "plan"), (245, 250, "presets"), (251, 265, "search"), (266, 292, "repos"), (293, 303, "extracted"),
    (304, 308, "suggest"), (315, 317, "suggest"), (324, 335, "suggest"), (336, 350, "code"),
    (351, 373, "hyperframes"), (380, 387, "link"), (395, 404, "assets"), (405, 416, "ncs"),
    (463, 471, "library"), (477, 482, "slow"), (487, 496, "slow"), (497, 513, "optimise"), (514, 531, "lost"),
    (532, 551, "again"), (552, 568, "minutes"), (569, 576, "cache"), (598, 635, "cache"), (644, 649, "faster"),
    (650, 655, "recap"), (664, 694, "repo"), (695, 698, "caveat"), (705, 710, "caveat"), (711, 737, "comment"),
    (764, 777, "style"), (791, 805, "own"), (812, 839, "launchask"), (849, 852, "launchgo"),
]
FIX = {15: "Claude,", 36: "Claude,", 43: "Cowork,", 89: "Claude", 109: "Claude", 157: "Claude", 255: "online,",
       265: "Claude.", 269: "GitHub", 299: "about 15,", 358: "HyperFrames", 505: "optimized", 620: "cache."}


def tail_pad(text):
    w = text.lower().strip(".,?!'\"")
    if w.endswith(("s", "sh", "z", "ch", "x", "ce", "se")):
        return 0.12
    if w and w[-1] in "aeiouy":
        return 0.03
    return 0.05


def main():
    words = json.load(open(JOB / "analysis.json"))["words"]
    # 1) source segments: each kept range, split where a pause is longer than MAX_GAP (that pause becomes a sliver)
    segs = []
    for a, b, tag in KEEP:
        run = [words[a]]
        for w in words[a + 1:b + 1]:
            if w["start"] - run[-1]["end"] > MAX_GAP:
                segs.append((run, tag, True)); run = []
            run.append(w)
        segs.append((run, tag, False))
    pieces, out_words, t = [], [], HOOK
    for k, (run, tag, inner) in enumerate(segs):
        sa = max(0.0, run[0]["start"] - LEAD)
        sb = run[-1]["end"] + tail_pad(run[-1]["text"])
        nxt = segs[k + 1][0][0]["start"] if k + 1 < len(segs) else None
        if nxt is not None and segs[k + 1][0][0]["i"] == run[-1]["i"] + 1:
            sb = min(sb, nxt - LEAD + 0.005)                     # never run into the next kept word
        sa, sb = np.ceil(sa * FPS) / FPS, np.floor(sb * FPS) / FPS  # snap to frames: cuts only shrink
        dur = (sb - sa) / SPEED
        pieces.append({"kind": "face", "tag": tag, "src_a": round(sa, 4), "src_b": round(sb, 4), "speed": SPEED,
                       "out_a": round(t, 4), "out_b": round(t + dur, 4), "w": [run[0]["i"], run[-1]["i"]]})
        for w in run:
            out_words.append({"i": w["i"], "text": FIX.get(w["i"], w["text"]), "tag": tag,
                              "t": round(t + (w["start"] - sa) / SPEED, 3), "e": round(t + (w["end"] - sa) / SPEED, 3)})
        t += dur + (SLIVER / SPEED if inner else 0.0)
    talk_end = t
    total = talk_end + 0.4 + LAUNCH + ENDCARD
    track = json.load(open(TRACK))
    for p in pieces:
        fs = track[int(p["src_a"] * FPS):max(int(p["src_a"] * FPS) + 1, int(p["src_b"] * FPS))]
        p["face"] = [round(float(np.median([f[i] for f in fs])), 1) for i in range(3)]
    edl = {"total": round(total, 3), "hook": HOOK, "talk_end": round(talk_end, 3), "launch": [round(talk_end + 0.4, 3), round(talk_end + 0.4 + LAUNCH, 3)],
           "pieces": pieces, "words": out_words}
    (HERE / "edl.json").write_text(json.dumps(edl, indent=0))
    (HERE / "cuts.json").write_text(json.dumps([p["out_a"] for p in pieces[1:]]))
    # 2) the voice: each piece cleaned (on a padded window so the denoiser settles), sped up, faded, placed
    n = int(total * SR)
    vo = np.zeros(n, np.float32)
    clean = subprocess.run(["ffmpeg", "-v", "error", "-i", str(VOICE), "-vn", "-af", VOICE_CLEAN, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                           capture_output=True, check=True).stdout
    full = np.frombuffer(clean, np.float32)
    for p in pieces:
        x = full[int(p["src_a"] * SR):int(p["src_b"] * SR)]
        raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", "-af",
                              f"atempo={SPEED},afade=t=in:d=0.025:curve=hsin,areverse,afade=t=in:d=0.025:curve=hsin,areverse",
                              "-f", "f32le", "-"], input=x.tobytes(), capture_output=True, check=True).stdout
        y = np.frombuffer(raw, np.float32)
        i = int(p["out_a"] * SR)
        vo[i:i + len(y)] += y[: n - i]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", "-c:a", "pcm_s24le", str(F.work / "vo.wav")],
                   input=vo.tobytes(), check=True)
    # 3) the cut picture on the output timeline (HOOK .. talk_end): source frames streamed once in order, each output
    #    frame takes its piece's source frame; pause slivers hold the previous piece's last frame
    nout = int(round((talk_end - HOOK) * FPS))
    need = []
    for k in range(nout):
        tt = HOOK + (k + 0.5) / FPS
        p = next((q for q in pieces if q["out_a"] <= tt < q["out_b"]), None)
        if p is None:
            p = max((q for q in pieces if q["out_b"] <= tt), key=lambda q: q["out_b"])
            src = p["src_b"] - 0.5 / FPS
        else:
            src = p["src_a"] + (tt - p["out_a"]) * p["speed"]
        need.append(int(src * FPS))
    W, H = 1920, 1080
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(SRC), "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            "-c:v", "libx264", "-crf", "12", "-preset", "medium", "-pix_fmt", "yuv420p", str(F.work / "aroll.mp4")], stdin=subprocess.PIPE)
    idx, frame, j = -1, None, 0
    while j < len(need):
        while idx < need[j]:
            buf = dec.stdout.read(W * H * 3)
            if len(buf) < W * H * 3:
                break
            frame, idx = buf, idx + 1
        enc.stdin.write(frame)
        j += 1
    enc.stdin.close(); enc.wait(); dec.kill()
    (F.work / "aroll.map.json").write_text(json.dumps(need))   # source frame of every cut frame (for the grade's head track)
    kept = sum(p["out_b"] - p["out_a"] for p in pieces)
    print(f"{len(pieces)} pieces, talk {kept:.1f} s (from {words[-1]['end']:.1f} s raw), total {total:.1f} s with hook/launch/end card")


if __name__ == "__main__":
    main()
