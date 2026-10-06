"""v8 motion demo: the same 12 s beat sheet built with the v7 vocabulary (K.rise, K.enter, sounds when a move starts)
and with kit/hf/kinetic.js (kinetic type, springs, multi-property entrances, sounds on the landing frame).

    uv run python kit/hf/demos/kinetic/build.py          # build both, render both, mix their cues, compare
    uv run python kit/hf/demos/kinetic/build.py --build  # only the two HyperFrames projects (then lint/snapshot them)

Outputs (kit/paths.py): output/temp/films/kit-hf-demos-kinetic/{hf_before,hf_after,renders,work} and
output/final/kit-hf-demos-kinetic/{kinetic_compare.mp4 (before, then after, with sound), kinetic_side_by_side.mp4}.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "kit/paths.py").exists())
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "kit/hf"))
import vendor  # noqa: E402
from kit.paths import Film  # noqa: E402

F = Film(__file__)
MODES = ("before", "after")
TOTAL, SR = 12.0, 48000
ENV = {**os.environ, "HYPERFRAMES_NO_UPDATE_CHECK": "1"}
SFX = ROOT / "kit/sfx"
CUES_JS = ROOT / "kit/presets/paper_studio/example/cues.mjs"


def run(cmd, **kw):
    subprocess.run([str(c) for c in cmd], check=True, env=ENV, **kw)


def project(mode: str) -> Path:
    return F.temp / f"hf_{mode}"


def build():
    tpl = (HERE / "src/template.html").read_text()
    for mode in MODES:
        d = project(mode)
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / "hyperframes.json", d / "hyperframes.json")
        vendor.copy_assets(d)
        html = vendor.inline(tpl, stickman=False).replace("/*DATA*/", "const D = " + json.dumps({"mode": mode}) + ";")
        (d / "index.html").write_text(html)
        print(f"{d / 'index.html'}")


def render():
    for mode in MODES:
        run(["npx", "hyperframes", "render", project(mode), "-o", F.renders / f"{mode}.mp4", "--fps", "30", "--quality", "delivery", "--quiet"])
        run(["node", CUES_JS, project(mode) / "index.html", F.work / f"cues_{mode}.json"])


def mix(mode: str) -> Path:
    """The composition's sound cues on silence, mastered to -14 LUFS (the demo has no voice)."""
    cues = json.loads((F.work / f"cues_{mode}.json").read_text())
    ins, chains = [], []
    for k, c in enumerate(cues):
        ins += ["-i", SFX / f"{c['name']}.wav"]
        ms = int(round(c["at"] * 1000))
        chains.append(f"[{k + 1}:a]aformat=sample_rates={SR}:channel_layouts=stereo,volume={c['gain_db'] + 12}dB,adelay={ms}|{ms}[s{k}]")
    graph = ";".join(chains) + ";[0:a]" + "".join(f"[s{k}]" for k in range(len(cues))) + \
        f"amix=inputs={len(cues) + 1}:normalize=0,atrim=0:{TOTAL},loudnorm=I=-14:TP=-1.5[a]"
    out = F.work / f"sfx_{mode}.wav"
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", str(TOTAL), "-i", f"anullsrc=r={SR}:cl=stereo", *ins,
         "-filter_complex", graph, "-map", "[a]", "-ar", str(SR), out])
    return out


def compare():
    parts = []
    for mode in MODES:
        p = F.work / f"{mode}_av.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-i", F.renders / f"{mode}.mp4", "-i", mix(mode), "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-c:a", "aac", "-aac_pns", "0", "-b:a", "256k", "-shortest", p])
        parts.append(p)
    lst = F.work / "concat.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart",
         F.final / "kinetic_compare.mp4"])
    run(["ffmpeg", "-v", "error", "-y", "-i", F.renders / "before.mp4", "-i", F.renders / "after.mp4", "-filter_complex",
         "[0:v][1:v]hstack=inputs=2,scale=1440:1280:flags=lanczos[v]", "-map", "[v]", "-c:v", "libx264", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", F.final / "kinetic_side_by_side.mp4"])
    print(f"-> {F.final / 'kinetic_compare.mp4'}\n-> {F.final / 'kinetic_side_by_side.mp4'}")


if __name__ == "__main__":
    build()
    if "--build" not in sys.argv:
        render()
        compare()
