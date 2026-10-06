"""Build "How I edit my videos with Claude" (16:9) as a HyperFrames composition.

Generated files never land in this folder (kit/paths.py): W = output/temp/films/<name>/work, HF = .../hf (the
HyperFrames project), R = .../renders, and the deliverables go to output/final/<name>/. Print them: python3 build.py --paths

    python3 edl.py                     # cut list, cleaned voice, the cut picture (W/aroll.mp4)
    python3 ../../kit/look/grade.py $W/aroll.mp4 $W/aroll_graded.mp4 --track=<take temp>/source.face.json --map=$W/aroll.map.json
    python3 blur_sessions.py && node capture.mjs
    python3 build.py                   # HF project: assets + index.html (+ captions.srt in output/final)
    python3 build.py --cues && python3 audio.py      # the mix (our mixer), from the composition's sound cues
    npx hyperframes render $HF -o $R/raw.mp4 --quality delivery && python3 build.py --mux
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "kit/paths.py").exists())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kit/hf"))
import vendor  # noqa: E402
from kit.paths import Film  # noqa: E402

F = Film(__file__)
A = F.assets
EDL = json.load(open(HERE / "edl.json"))
FPS = 30


def run(cmd):
    subprocess.run(cmd, check=True)


AROLL = "assets/aroll.mp4"


def broll():
    """Past edits as B-roll (muted, 30 fps, dense keyframes) + template preview tiles + the end frames."""
    D = ROOT / "jobs/_deliverables"
    clips = {"short_a": (D / "video4_final.mp4", 6.0), "short_b": (D / "video3_final.mp4", 8.0), "short_c": (D / "sample1_final.mp4", 5.0),
             "reel_hf": (ROOT / "films/model-compare-hf/reel_hf.mp4", 0.2), "desi": (ROOT / "films/desi-ai-intro/desi_ai_intro.mp4", 3.0),
             "pitch": (D / "pitch1_2founders_final.mp4", 4.0)}
    (A / "broll").mkdir(exist_ok=True)
    for name, (src, ss) in clips.items():
        out = A / "broll" / f"{name}.mp4"
        if out.exists():
            continue
        vert = "1080:1920" if name != "pitch" else "1920:1080"
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-i", str(src), "-t", "9", "-an", "-vf", f"scale={vert}:flags=lanczos,fps={FPS}",
             "-c:v", "libx264", "-crf", "20", "-g", "10", "-keyint_min", "10", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)])
    (A / "tiles").mkdir(exist_ok=True)
    prev = sorted((ROOT / "kit/graphics/_previews").glob("*.png"))
    for f in prev:
        im = Image.open(f).convert("RGB")
        w = im.width // 4
        im.crop((2 * w, 0, 3 * w, im.height)).save(A / "tiles" / f"{f.stem}.jpg", quality=86)
    return [f.stem for f in prev]


def snippets():
    """Real code from a past edit, and real lines from the skill file (the transcript clean-up rules), wrapped to fit."""
    import re
    import textwrap
    code = (ROOT / "films/model-compare-hf/template.html").read_text().splitlines()
    i = next(k for k, l in enumerate(code) if "MORE POWERFUL ... FREE" in l)
    code_lines = [l.rstrip()[:92] for l in code[i:i + 15]]
    skill = (ROOT / ".claude/skills/video-shorts/SKILL.md").read_text().splitlines()
    j = next(k for k, l in enumerate(skill) if "`caption_overrides`" in l)
    doc_lines = []
    for l in skill[j:j + 5]:
        l = re.sub(r"[*`]", "", l.strip().lstrip("- "))
        doc_lines += textwrap.wrap(l, 64)
    return code_lines, doc_lines[:11]


def stills():
    """Before / after of the grade for the launch film (the same source frame, raw and graded)."""
    for name, f in (("ba_before", F.work / "aroll.mp4"), ("ba_after", F.work / "aroll_graded.mp4")):
        run(["ffmpeg", "-v", "error", "-y", "-ss", "60", "-i", str(f), "-frames:v", "1", "-vf", "crop=1100:800:410:120,scale=800:582", "-q:v", "2", str(A / f"{name}.jpg")])


def build():
    F.stage()                                   # hyperframes.json + this film's own assets/ into the HF project
    vendor.copy_assets(F.hf)                    # fonts + gsap
    tiles = broll()
    g = F.work / "aroll_graded.mp4"
    if g.exists():
        stills()
    code_lines, doc_lines = snippets()
    if g.exists() and (not (A / "aroll.mp4").exists() or (A / "aroll.mp4").stat().st_mtime < g.stat().st_mtime):
        run(["cp", str(g), str(A / "aroll.mp4")])
    D = {"total": EDL["total"], "launch": EDL["launch"], "pieces": EDL["pieces"], "words": EDL["words"],
         "tiles": tiles, "code": code_lines, "doc": doc_lines}
    html = (HERE / "src/template.html").read_text()
    html = html.replace("/*DATA*/", "const D = " + json.dumps(D) + ";").replace("__TOTAL__", f"{EDL['total']}")
    talk1 = EDL["talk_end"]
    html = html.replace("<!--AROLL-->", f'<video id="aroll" class="clip" src="{AROLL}" muted playsinline data-start="0" '
                                         f'data-duration="{talk1:.3f}" data-media-start="0" data-track-index="2"></video>')
    (F.hf / "index.html").write_text(html)
    print(f"{F.hf / 'index.html'}: {len(EDL['pieces'])} pieces, {len(tiles)} tiles, {len(doc_lines)} skill lines")


def srt():
    """YouTube captions from the cut's word map (with the spelling fixes): a caption ends at a sentence end, at 42
    characters, at a pause, or after 3.2 s."""
    def ts(t):
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    caps, cur = [], []
    for w in EDL["words"]:
        if cur and (len(" ".join(x["text"] for x in cur + [w])) > 42 or w["t"] - cur[-1]["e"] > 0.6 or w["e"] - cur[0]["t"] > 3.2):
            caps.append(cur); cur = []
        cur.append(w)
        if w["text"].endswith((".", "?", "!")):
            caps.append(cur); cur = []
    if cur:
        caps.append(cur)
    out = []
    for k, c in enumerate(caps):
        end = min(c[-1]["e"] + 0.25, caps[k + 1][0]["t"] - 0.02) if k + 1 < len(caps) else c[-1]["e"] + 0.4
        text = " ".join(x["text"] for x in c)
        out.append(f"{k + 1}\n{ts(c[0]['t'])} --> {ts(end)}\n{text[0].upper() + text[1:]}\n")
    (F.final / "captions.srt").write_text("\n".join(out))
    print(f"{F.final / 'captions.srt'}: {len(caps)} captions")


def mux():
    """Picture from HyperFrames + our mix (already at -14 LUFS)."""
    out = F.final / "how_i_edit_with_claude.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(F.renders / "raw.mp4"), "-i", str(F.work / "mix.wav"), "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-aac_pns", "0", "-b:a", "320k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)])
    print(f"-> {out}")


def cues():
    """The composition's sound cues (its sfx() calls), read from the built page -> W/cues.json (for audio.py)."""
    run(["node", str(HERE / "cues.mjs"), str(F.hf / "index.html"), str(F.work / "cues.json")])


if __name__ == "__main__":
    if "--paths" in sys.argv:
        print(f"W={F.work}\nHF={F.hf}\nR={F.renders}\nFINAL={F.final}")
    elif "--cues" in sys.argv:
        cues()
    elif "--mux" in sys.argv:
        mux()
    else:
        build()
        srt()
