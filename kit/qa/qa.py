"""QA gate for any rendered video: severity-graded findings with stable IDs, and an exit code.

    python3 kit/qa/qa.py final.mp4 [--expect-duration=147.1] [--expect-size=1920x1080] [--fps=30]
                         [--cuts=cuts.json] [--voice=vo.wav] [--allow-freeze=144.8-147.2,...] [--allow-black=...] [--json=report.json]

Severities (the verdict is FAIL if anything CRITICAL or HIGH is found, WARN if only MEDIUM, else PASS):
  CRITICAL  unreadable file, missing stream, clipping (sample peak >= -0.1 dBFS), duration more than 1 s off,
            black of 0.5 s or more
  HIGH      true peak above -1.0 dBTP, shorter black frames, a freeze longer than 1.5 s, more than 1 s of frozen time
            per 30 s in total, flash (single-frame) frames, duration 0.15-1 s off, wrong size/fps/pixel format,
            dead air of 1.2 s or more
  MEDIUM    loudness outside -14 +/-1 LUFS, a freeze of 0.8-1.5 s (a "slideshow" hold), dead air (a near-silent stretch
            of 0.6-1.2 s mid-video), a click at a cut (only when --cuts lists the edit's cut times)
A check that could not run is reported as SKIPPED, never as a pass. Exit code: 0 PASS, 2 WARN, 3 FAIL.
IDs are stable across renders (e.g. freeze@65.7, cut@14.47), so a fix can be confirmed on the next render.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}


def arg(name, default=None):
    return next((a.split("=", 1)[1] for a in sys.argv if a.startswith(f"--{name}=")), default)


def ranges(spec):
    out = []
    for part in (spec or "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.append((float(a), float(b)))
    return out


def inside(t, rs, pad=0.05):
    return any(a - pad <= t <= b + pad for a, b in rs)


def ffprobe(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate,pix_fmt:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout else None


def loudness(path):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true+sample", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    tail = err[err.rfind("Summary:"):]
    get = lambda k: float(re.search(rf"{k}:\s*(-?[\d.]+|-inf)", tail).group(1).replace("-inf", "-200")) if re.search(rf"{k}:", tail) else None
    peaks = re.findall(r"Peak:\s*(-?[\d.]+|-inf)", tail)
    return {"I": get("I"), "true_peak": float(peaks[0]) if peaks else None, "sample_peak": float(peaks[1]) if len(peaks) > 1 else None}


def detect(path, expr):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf", f"scale=270:-2:flags=fast_bilinear,{expr}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return err


def spans(err, kind, total):
    starts = [float(x) for x in re.findall(rf"{kind}_start:\s*([\d.]+)", err)]
    ends = [float(x) for x in re.findall(rf"{kind}_end:\s*([\d.]+)", err)]
    return [(s, ends[i] if i < len(ends) else total) for i, s in enumerate(starts)]      # no end: it runs to the last frame


def flash_frames(path, fps):
    """Single frames that differ strongly from both neighbours while the neighbours match each other."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=64:36,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, 36, 64).astype(np.float32)
    if len(f) < 3:
        return []
    a = np.abs(f[1:-1] - f[:-2]).mean((1, 2))
    b = np.abs(f[1:-1] - f[2:]).mean((1, 2))
    c = np.abs(f[2:] - f[:-2]).mean((1, 2))
    hit = np.where((a > 28) & (b > 28) & (c < 9))[0] + 1
    return [round(k / fps, 3) for k in hit]


def audio_mono(path, sr=16000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.float32)


def dead_air(x, sr, total, floor_db=-45, min_len=0.6):
    """Near-silent stretches mid-video (the music bed normally fills gaps, so real silence is a mistake)."""
    hop = int(0.02 * sr)
    n = len(x) // hop
    rms = 20 * np.log10(np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-9)
    quiet = rms < floor_db
    out, i = [], 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            a, b = i * 0.02, j * 0.02
            if b - a >= min_len and a > 0.5 and b < total - 0.5:
                out.append((round(a, 2), round(b, 2)))
            i = j
        i += 1
    return out


def voice_clicks(x, sr, cuts, limit=0.35):
    """On a clean voice stem the level around a cut is near silence, so use an absolute test: a sample-to-sample
    jump above `limit` within +/-40 ms of the join (a hard edge with no fade)."""
    d = np.abs(np.diff(x, prepend=x[:1]))
    out = []
    for t in cuts:
        i = int(t * sr)
        w = d[max(0, i - int(0.04 * sr)): i + int(0.04 * sr)]
        if len(w) and w.max() > limit:
            out.append((round(t, 3), round(float(w.max()), 2)))
    return out


def cut_clicks(x, sr, cuts):
    """A click is a burst of high-frequency energy right at a cut, well above the surrounding level."""
    d = np.diff(x, prepend=x[:1])                                   # crude high-pass: clicks are broadband transients
    hop = int(0.005 * sr)
    out = []
    for t in cuts:
        i = int(t * sr)
        win = d[max(0, i - int(0.1 * sr)): i + int(0.1 * sr)]
        at = d[max(0, i - hop * 2): i + hop * 2]
        if len(win) < hop * 10 or not len(at):
            continue
        ref = np.median(np.abs(win)) + 1e-6
        ratio = np.max(np.abs(at)) / ref
        if ratio > 10:                                              # measured: clean speech cuts <= 5.5x, a click ~16x
            out.append((round(t, 3), round(float(ratio), 1)))
    return out


def main():
    path = Path(sys.argv[1])
    issues, skipped, info = [], [], {}
    add = lambda sev, iid, check, detail, fix, t=None: issues.append({"severity": sev, "id": iid, "check": check, "t": t, "detail": detail, "fix": fix})
    allow_freeze, allow_black = ranges(arg("allow-freeze")), ranges(arg("allow-black"))

    pr = ffprobe(path)
    if not pr:
        add("CRITICAL", "file", "integrity", "ffprobe cannot read the file", "re-render; check the encoder log")
        return finish(path, issues, skipped, info)
    types = [s["codec_type"] for s in pr.get("streams", [])]
    v = next((s for s in pr["streams"] if s["codec_type"] == "video"), None)
    dur = float(pr["format"]["duration"])
    info.update({"duration": dur, "streams": types})
    if not v:
        add("CRITICAL", "stream:video", "integrity", "no video stream", "re-render")
        return finish(path, issues, skipped, info)
    if "audio" not in types:
        add("CRITICAL", "stream:audio", "integrity", "no audio stream", "mux the mix back in")
    fps = round(eval(v["r_frame_rate"]))
    info.update({"size": f"{v['width']}x{v['height']}", "fps": fps})
    if arg("expect-size") and arg("expect-size") != info["size"]:
        add("HIGH", "size", "format", f"size {info['size']}, expected {arg('expect-size')}", "render at the target size")
    if v.get("pix_fmt") not in ("yuv420p", None):
        add("HIGH", "pixfmt", "format", f"pixel format {v.get('pix_fmt')} (platforms expect yuv420p)", "encode with -pix_fmt yuv420p")
    if arg("fps") and int(arg("fps")) != fps:
        add("HIGH", "fps", "format", f"{fps} fps, expected {arg('fps')}", "render at the target fps")
    if arg("expect-duration"):
        off = abs(dur - float(arg("expect-duration")))
        if off > 1:
            add("CRITICAL", "duration", "format", f"duration {dur:.2f} s is {off:.2f} s off", "check the edit list / render range")
        elif off > 0.15:
            add("HIGH", "duration", "format", f"duration {dur:.2f} s is {off:.2f} s off", "check the tail and -t on the encode")

    if "audio" in types:
        L = loudness(path)
        info["loudness"] = L
        if L["sample_peak"] is not None and L["sample_peak"] >= -0.1:
            add("CRITICAL", "clip", "audio", f"sample peak {L['sample_peak']} dBFS: the mix clips", "lower the mix and re-run the limiter")
        if L["true_peak"] is not None and L["true_peak"] > -1.0:
            add("HIGH", "truepeak", "audio", f"true peak {L['true_peak']} dBTP (limit -1.0)", "limit at -1.5 dBTP")
        if L["I"] is None:
            skipped.append("loudness")
        elif abs(L["I"] + 14) > 1:
            add("MEDIUM", "lufs", "audio", f"integrated {L['I']} LUFS (target -14 +/-1)", "master with two-pass loudnorm to -14")
        x = audio_mono(path)
        for a, b in dead_air(x, 16000, dur):
            add("HIGH" if b - a >= 1.2 else "MEDIUM", f"deadair@{a}", "audio", f"near-silence {a}-{b} s", "extend the bed or tighten the cut", a)
        cuts = json.load(open(arg("cuts"))) if arg("cuts") else None
        if cuts is None:
            skipped.append("cut-clicks (no --cuts)")
        else:
            # clicks live in the voice: with --voice the stem is checked (sound effects placed on cuts are not clicks)
            if arg("voice"):
                xv = audio_mono(Path(arg("voice")), sr=48000)
                for t, r in voice_clicks(xv, 48000, cuts):
                    add("MEDIUM", f"cut@{t}", "audio", f"hard edge at the cut (jump {r})", "add a 20-30 ms fade at both edges", t)
            else:
                for t, r in cut_clicks(x, 16000, cuts):
                    add("MEDIUM", f"cut@{t}", "audio", f"click at the cut ({r}x the local level)", "add a 20-30 ms fade at both edges", t)

    err = detect(path, "blackdetect=d=0.1:pix_th=0.05,freezedetect=n=0.003:d=0.8")
    for a, b in spans(err, "black", dur):
        if not inside(a, allow_black) and not inside(b, allow_black):
            add("CRITICAL" if b - a >= 0.5 else "HIGH", f"black@{round(a, 1)}", "picture", f"black {a:.2f}-{b:.2f} s", "cover the gap or trim it", round(a, 2))
    frozen = 0.0
    for a, b in spans(err, "freeze", dur):
        if inside(a, allow_freeze) and inside(b, allow_freeze):
            continue
        frozen += b - a
        L = b - a
        if L > 1.5:
            add("HIGH", f"freeze@{round(a, 1)}", "picture", f"no motion {a:.2f}-{b:.2f} s ({L:.1f} s)", "add a slow push-in or a new visual", round(a, 2))
        else:
            add("MEDIUM", f"freeze@{round(a, 1)}", "picture", f"static hold {a:.2f}-{b:.2f} s ({L:.1f} s)", "keep holds under ~0.6 s: drift, push or cut", round(a, 2))
    if frozen > max(1.0, dur / 30):
        add("HIGH", "frozen-total", "picture", f"{frozen:.1f} s frozen in total (budget {max(1.0, dur / 30):.1f} s: 1 s per 30 s)",
            "keep everything moving: slow pushes, drift, new visuals")
    first = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1", "-vf", "scale=64:-2,format=gray", "-f", "rawvideo", "-"],
                           capture_output=True).stdout
    if first and np.frombuffer(first, np.uint8).std() < 10:
        add("HIGH", "frame1", "picture", "frame 1 is nearly blank; the first frame must already be a finished composition (the hook)",
            "start the timeline on the settled hook state", 0.0)
    for t in flash_frames(path, fps):
        add("HIGH", f"flash@{t}", "picture", f"single-frame flash at {t:.2f} s", "look at the seam: a frame of the wrong layer/scene", t)
    return finish(path, issues, skipped, info)


def finish(path, issues, skipped, info):
    issues.sort(key=lambda i: (SEV_ORDER[i["severity"]], i["t"] if i["t"] is not None else -1))
    worst = issues[0]["severity"] if issues else None
    verdict = "FAIL" if worst in ("CRITICAL", "HIGH") else "WARN" if worst == "MEDIUM" else "PASS"
    report = {"file": str(path), "verdict": verdict, "info": info, "skipped": skipped, "issues": issues}
    if arg("json"):
        Path(arg("json")).write_text(json.dumps(report, indent=1))
    print(f"{verdict}: {path.name}  {info.get('size', '?')} {info.get('fps', '?')} fps {info.get('duration', 0):.2f} s  "
          f"LUFS {info.get('loudness', {}).get('I')}  TP {info.get('loudness', {}).get('true_peak')}")
    for i in issues:
        print(f"  {i['severity']:8s} {i['id']:18s} {i['detail']}  -> {i['fix']}")
    for s in skipped:
        print(f"  SKIPPED  {s}")
    sys.exit({"PASS": 0, "WARN": 2, "FAIL": 3}[verdict])


if __name__ == "__main__":
    main()
