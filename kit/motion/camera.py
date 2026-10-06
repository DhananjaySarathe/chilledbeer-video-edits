"""The A-roll camera for HyperFrames films: plan the camera moves (kit/hf/motion.js, run in Node) and bake the
motion-blurred frames of the fast moves into a small clip the composition plays over the A-roll for those frames.

Why bake: a snap zoom, an eased punch or a zoom transition needs motion blur, which is the average of N sub-frame
transforms of the SAME source frame. Done here it is exact (float accumulation, sub-pixel cv2.warpAffine) and cheap
(only the frames that move). The measurements are in kit/hf/README.md, section "v7 camera".

    from camera import plan, bake, for_page
    P = plan({"pieces": ..., "words": ..., "fps": 30, "framing": {...}, "tags": {...}})   # the director's decisions
    blur = bake("assets/aroll.mp4", P, "assets/aroll_motion")                            # -> assets/aroll_motion_1920x1080.mp4
    D["camera"] = for_page(P, blur, "assets/aroll_motion")                               # what HF.camera({plan}) reads

    uv run python kit/motion/camera.py camera_in.json assets/aroll.mp4 assets/aroll_motion [plan_out.json]
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PLAN_JS = HERE / "plan.cjs"
SRC_W, SRC_H = 1920, 1080


def plan(inp: dict) -> dict:
    """Run the director (HF.motion.direct) and the blur sampler in Node: the plan plus `windows` (frames that need
    blur, each with its sub-frame matrices). The same code runs in the page, so the page and the bake agree."""
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "in.json", Path(d) / "out.json"
        src.write_text(json.dumps(inp))
        subprocess.run(["node", str(PLAN_JS), str(src), str(out)], check=True)
        return json.loads(out.read_text())


def _decode(path: Path, f0: int, n: int, fps: int, size: tuple[int, int]) -> np.ndarray:
    """n frames from frame f0 as (n, H, W, 3) planar-interleaved Y'CbCr 4:4:4 (no RGB round trip: the warp and the
    average are linear, so they commute with the colour matrix)."""
    w, h = size
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{(f0 - 0.5) / fps:.6f}", "-i", str(path), "-frames:v", str(n),
           "-f", "rawvideo", "-pix_fmt", "yuv444p", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.uint8)
    got = a.size // (w * h * 3)
    if got < n:
        raise SystemExit(f"{path}: wanted frames {f0}-{f0 + n - 1}, got {got}")
    return a[: n * w * h * 3].reshape(n, 3, h, w).transpose(0, 2, 3, 1)


def blur_frame(src: np.ndarray, mats: list, view: tuple[int, int]) -> np.ndarray:
    """Average of the source warped by each sub-frame matrix (CSS matrix(a, b, c, d, e, f) = src -> view)."""
    acc = np.zeros((view[1], view[0], 3), np.float32)
    for a, b, c, d, e, f in mats:
        M = np.array([[a, c, e], [b, d, f]], np.float64)
        acc += cv2.warpAffine(src, M, view, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return np.clip(acc / len(mats) + 0.5, 0, 255).astype(np.uint8)


def bake(aroll: str | Path, P: dict, out_prefix: str | Path, crf: int = 10) -> dict:
    """Render every blur window of plan P from the A-roll; one clip per view size (all-intra, so any frame seeks
    exactly). Returns {"windows": [{f0, f1, at, src, view, top}], "stats": {...}}."""
    aroll, out_prefix = Path(aroll), Path(out_prefix)
    fps, wins = P["fps"], P.get("windows") or []
    by_view: dict[tuple, list] = {}
    for w in wins:
        by_view.setdefault(tuple(w["view"]), []).append(w)
    out, frames, samples, t_warp = [], 0, 0, 0.0
    for view, ws in by_view.items():
        dst = out_prefix.parent / f"{out_prefix.name}_{view[0]}x{view[1]}.mp4"
        tags = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
        # the input is tagged like the output, or swscale converts the colour matrix on the way (measured: luma -1.5)
        enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv444p", "-s", f"{view[0]}x{view[1]}",
                                "-r", str(fps), *tags, "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-g", "1",
                                "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709",
                                "-color_trc", "bt709", "-movflags", "+faststart", str(dst)], stdin=subprocess.PIPE)
        at = 0
        for w in ws:
            n = w["f1"] - w["f0"]
            src = _decode(aroll, w["f0"], n, fps, (SRC_W, SRC_H))
            for k in range(n):
                t = time.perf_counter()
                img = blur_frame(np.ascontiguousarray(src[k]), w["frames"][k], view)
                t_warp += time.perf_counter() - t
                samples += len(w["frames"][k])
                enc.stdin.write(np.ascontiguousarray(img.transpose(2, 0, 1)).tobytes())
            out.append({"f0": w["f0"], "f1": w["f1"], "at": at, "src": dst.name, "view": list(view), "top": w.get("top", 0)})
            at += n
            frames += n
        enc.stdin.close()
        if enc.wait():
            raise SystemExit(f"ffmpeg failed writing {dst}")
    stats = {"frames": frames, "samples": samples, "warp_ms_per_frame": round(1000 * t_warp / max(1, frames), 1),
             "warp_ms_per_sample": round(1000 * t_warp / max(1, samples), 2)}
    return {"windows": out, "stats": stats}


def for_page(P: dict, blur: dict | None, assets_prefix: str = "assets") -> dict:
    """The plan as the page needs it: no sub-frame matrices, plus where the baked frames are."""
    page = {k: v for k, v in P.items() if k != "windows"}
    if blur and blur["windows"]:
        page["blur"] = {"windows": [dict(w, src=f"{assets_prefix}/{w['src']}") for w in blur["windows"]]}
    return page


def main(argv: list[str]) -> None:
    if len(argv) < 3:
        raise SystemExit(__doc__)
    inp, aroll, prefix = json.loads(Path(argv[0]).read_text()), argv[1], argv[2]
    P = plan(inp)
    blur = bake(aroll, P, prefix)
    page = for_page(P, blur, str(Path(prefix).parent.name))
    if len(argv) > 3:
        Path(argv[3]).write_text(json.dumps(page))
    print("\n".join(P["log"]))
    print(f"blur: {len(blur['windows'])} windows, {blur['stats']}")


if __name__ == "__main__":
    main(sys.argv[1:])
