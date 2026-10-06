"""Sentence map of a take: for every word gap, how likely a sentence (a complete thought) ends there.

    uv run python -m kit.cut.sentmap ew2 [ew1 ...] [--force] [--model=sat-3l-sm]
    -> jobs/<job>/sentmap.json, and a short summary on stdout

Each gap k (after word k, before word k+1; the last word's gap is the end of the take) gets:
  features  sat      SaT (wtpsplit, segment-any-text) boundary probability on the bare text (lowercase, no punctuation:
                     whisper's punctuation is unreliable, it turns into all commas in long takes)
            sat_p    the same on whisper's own text with its punctuation
            punct    whisper's mark on word k: 2 = . ? !, 1 = , ; :, 0 = none
            turn     Smart Turn v3 (pipecat) end-of-turn probability on the audio up to word k's end (last 8 s)
            pause    silence between the words (energy-refined word times), vad_pause = Silero VAD's silence there
            f0_slope semitones/s over the last 300 ms of voiced speech of word k; f0_end = its last 50 ms vs the
                     speaker's median (st); f0_reset = the next word's first 150 ms minus f0_end (new sentences restart high)
            lexicon  left_hard/left_soft (word k is a connector/article/postposition), right_hard/right_soft (word k+1
                     is a postposition/aux/relative), hindi_final (word k is a Hindi verb/aux), tag (right?, na),
                     starter (word k+1 is so/but/now/first...)
  p         p_boundary, a logistic model of the features (weights calibrated on the ExpenseWaale takes, see WEIGHTS)
  label     sentence_end (p >= P_SENT), clause_end (p >= P_CLAUSE), continuation
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

if __package__ in (None, ""):                      # run as a script path: make `kit.cut` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kit.cut.common import (FILLERS, HINDI_FINAL, job_source, job_temp, LEFT_HARD, LEFT_SOFT, MODELS, RIGHT_HARD, RIGHT_SOFT,  # noqa: E402
                            STARTERS, TAGS, job_language, load_words, norm)

SR = 16000
VERSION = 1
SAT_MODEL = "sat-3l-sm"
TURN_MODEL = MODELS / "smart-turn-v3.2-cpu.onnx"
VAD_MODEL = MODELS / "silero_vad.onnx"
TURN_TAIL = 0.20          # Smart Turn hears the speech plus up to 200 ms of what follows (never the next word)

# Logistic weights over the features (fit with kit/cut/calibrate.py on the hand-labelled gaps of both takes, then
# rounded; see README). x = bias + sum(w * f(feature)).
WEIGHTS = {
    "bias": -0.8,
    "sat": 0.6,            # logit(sat), clipped to +/-6: the strongest single cue (AUC 0.95 alone)
    "sat_p": 0.5,          # logit(sat_p)
    "punct2": 0.2,         # whisper's . ? ! (mostly already inside sat_p)
    "punct1": 1.3,         # whisper's comma: in long run-on takes whisper writes commas where sentences end
    "turn": 0.2,           # logit(turn)
    "pause": 2.4,          # min(pause, 1.0) s
    "f0_fall": 0.4,        # final lowering (f0_slope <= -2 st/s or f0_end <= -1 st)
    "f0_rise": 0.0,        # measured: no signal for this speaker (kept as a feature, weight 0)
    "f0_reset": 0.0,       # measured: no signal
    "left_hard": -1.0,     # prior only; cutcheck hard-fails these words anyway
    "left_soft": -0.5,
    "right_hard": -0.5,
    "right_soft": -0.9,
    "hindi_final": 0.3,
    "tag": 0.3,
    "starter": 1.3,        # the next word is so/but/now/first/by/if/when/toh...
}
P_SENT, P_CLAUSE = 0.5, 0.05     # calibrated: 97 % of hand-labelled sentence ends >= 0.05, 89 % of mid-sentence pauses below


# ---------------------------------------------------------------- audio
def load_audio(job: str) -> np.ndarray:
    # the analyze step's 16 kHz extract, else the DeepFilterNet input, else the kept footage itself (temp was deleted)
    wav = next((p for p in (job_temp(job) / "audio16k.wav", job_temp(job) / "voice_raw.wav") if p.exists()), job_source(job))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def vad_probs(x: np.ndarray) -> np.ndarray:
    """Silero VAD v5 (ONNX, no torch): speech probability per 32 ms frame (512 samples at 16 kHz)."""
    import onnxruntime as ort
    sess = ort.InferenceSession(str(VAD_MODEL), providers=["CPUExecutionProvider"])
    state = np.zeros((2, 1, 128), np.float32)
    ctx = np.zeros((1, 64), np.float32)
    sr = np.array(SR, dtype=np.int64)
    n = len(x) // 512
    out = np.zeros(n, np.float32)
    for k in range(n):
        inp = np.concatenate([ctx, x[k * 512:(k + 1) * 512][None, :]], axis=1)
        p, state = sess.run(None, {"input": inp, "state": state, "sr": sr})
        out[k] = p[0, 0]
        ctx = inp[:, -64:]
    return out


def vad_silence(vp: np.ndarray, a: float, b: float, mid_a: float, mid_b: float) -> float:
    """Longest VAD silence (p < 0.5) whose run overlaps [a, b] and stays between the two words' middles."""
    hop = 512 / SR
    lo, hi = max(0, int(mid_a / hop)), min(len(vp), int(math.ceil(mid_b / hop)))
    best, k = 0.0, lo
    while k < hi:
        if vp[k] >= 0.5:
            k += 1
            continue
        j = k
        while j < hi and vp[j] < 0.5:
            j += 1
        s, e = k * hop, j * hop
        if e >= a - 0.05 and s <= b + 0.05:
            best = max(best, e - s)
        k = j
    return round(best, 3)


def pitch_track(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    import parselmouth
    snd = parselmouth.Sound(x.astype(np.float64), sampling_frequency=SR)
    pitch = snd.to_pitch(time_step=0.01, pitch_floor=60.0, pitch_ceiling=400.0)
    f0 = pitch.selected_array["frequency"]
    t = pitch.xs()
    voiced = f0[f0 > 0]
    med = float(np.median(voiced)) if len(voiced) else 120.0
    st = np.where(f0 > 0, 12 * np.log2(np.maximum(f0, 1) / med), np.nan)
    return t, st, med


def pitch_feats(t: np.ndarray, st: np.ndarray, w: dict, nxt: dict | None) -> tuple[float, float, float]:
    """(slope st/s over the last 300 ms voiced, final level st, reset of the next word's start in st)."""
    m = (t >= w["end"] - 0.8) & (t <= w["end"] + 0.03) & ~np.isnan(st)
    slope, end = 0.0, 0.0
    if m.sum() >= 4:
        tv, sv = t[m], st[m]
        keep = tv >= tv[-1] - 0.30
        tv, sv = tv[keep], sv[keep]
        if len(tv) >= 4 and tv[-1] - tv[0] > 0.05:
            slope = float(np.polyfit(tv, sv, 1)[0])
        end = float(np.nanmean(sv[-5:]))
    reset = 0.0
    if nxt is not None:
        m2 = (t >= nxt["start"] - 0.02) & (t <= nxt["start"] + 0.25) & ~np.isnan(st)
        if m2.sum() >= 3:
            reset = float(np.nanmean(st[m2][:15])) - end
    return round(float(np.clip(slope, -40, 40)), 2), round(end, 2), round(float(np.clip(reset, -12, 12)), 2)


def smart_turn(x: np.ndarray, ends: list[float], batch: int = 32) -> list[float]:
    """Smart Turn v3.2 (BSD-2): P(the speaker has finished the turn) for audio ending at each time."""
    import onnxruntime as ort
    from transformers import WhisperFeatureExtractor
    fe = WhisperFeatureExtractor(chunk_length=8)
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 4
    sess = ort.InferenceSession(str(TURN_MODEL), sess_options=opts, providers=["CPUExecutionProvider"])
    n8 = 8 * SR
    out = []
    for k in range(0, len(ends), batch):
        clips = []
        for e in ends[k:k + batch]:
            b = int(min(len(x), max(0, e) * SR))
            seg = x[max(0, b - n8):b]
            if len(seg) < n8:
                seg = np.pad(seg, (n8 - len(seg), 0))
            clips.append(seg)
        feats = fe(clips, sampling_rate=SR, return_tensors="np", padding="max_length", max_length=n8, truncation=True,
                   do_normalize=True).input_features.astype(np.float32)
        p = sess.run(None, {"input_features": feats})[0].reshape(-1)
        out.extend(float(v) for v in p)
    return out


# ---------------------------------------------------------------- text
_SAT = {}


def sat_model(name: str = SAT_MODEL):
    if name not in _SAT:
        import warnings
        warnings.filterwarnings("ignore")
        from wtpsplit import SaT
        _SAT[name] = SaT(name, ort_providers=["CPUExecutionProvider"])
    return _SAT[name]


def sat_word_probs(texts: list[str], model: str = SAT_MODEL) -> list[float]:
    """SaT boundary probability after each word: the max over the word's last character and the space after it."""
    text, ends = "", []
    for t in texts:
        text += (" " if text else "") + (t or "-")
        ends.append(len(text) - 1)
    p = sat_model(model).predict_proba(text)
    return [round(float(max(p[e], p[e + 1] if e + 1 < len(p) else 0.0)), 4) for e in ends]


def punct_class(text: str) -> int:
    t = text.rstrip("\"')]")
    return 2 if t.endswith((".", "?", "!")) else 1 if t.endswith((",", ";", ":")) else 0


# ---------------------------------------------------------------- the model
def logit(p: float, clip: float = 6.0) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return max(-clip, min(clip, math.log(p / (1 - p))))


def design(f: dict) -> dict:
    """The model's inputs from a gap's raw features."""
    fall = 1.0 if (f["f0_slope"] <= -2.0 or f["f0_end"] <= -1.0) else 0.0
    rise = 1.0 if (f["f0_end"] >= 2.0 or f["f0_slope"] >= 6.0) and not f["left_q"] else 0.0
    return {
        "sat": logit(f["sat"]), "sat_p": logit(f["sat_p"]), "punct2": float(f["punct"] == 2), "punct1": float(f["punct"] == 1),
        "turn": logit(f["turn"]), "pause": min(f["pause"], 1.0), "f0_fall": fall, "f0_rise": rise,
        "f0_reset": max(-6.0, min(6.0, f["f0_reset"])),
        "left_hard": float(f["left_hard"]), "left_soft": float(f["left_soft"]), "right_hard": float(f["right_hard"]),
        "right_soft": float(f["right_soft"]), "hindi_final": float(f["hindi_final"]), "tag": float(f["tag"]),
        "starter": float(f["starter"]),
    }


def p_boundary(f: dict, weights: dict = WEIGHTS) -> float:
    x = weights["bias"] + sum(weights[k] * v for k, v in design(f).items())
    return 1 / (1 + math.exp(-x))


def label_of(p: float) -> str:
    return "sentence_end" if p >= P_SENT else "clause_end" if p >= P_CLAUSE else "continuation"


# ---------------------------------------------------------------- build
def features(job: str, model: str = SAT_MODEL, log=print) -> tuple[list[dict], dict]:
    words = load_words(job)
    n = len(words)
    timing = {}
    t0 = time.time()
    bare = [norm(w["text"]) or "-" for w in words]
    sat = sat_word_probs(bare, model)
    sat_p = sat_word_probs([w["text"] for w in words], model)
    timing["sat"] = round(time.time() - t0, 2)
    t0 = time.time()
    x = load_audio(job)
    dur = len(x) / SR
    vp = vad_probs(x)
    timing["vad"] = round(time.time() - t0, 2)
    t0 = time.time()
    pt, pst, med = pitch_track(x)
    timing["pitch"] = round(time.time() - t0, 2)
    t0 = time.time()
    ends = []
    for k, w in enumerate(words):
        nxt_start = words[k + 1]["start"] if k + 1 < n else dur
        ends.append(min(w["end"] + TURN_TAIL, max(w["end"], nxt_start - 0.02)))
    turn = smart_turn(x, ends)
    timing["turn"] = round(time.time() - t0, 2)
    gaps = []
    for k, w in enumerate(words):
        nxt = words[k + 1] if k + 1 < n else None
        a, b = w["end"], (nxt["start"] if nxt else dur)
        left, right = bare[k], (bare[k + 1] if nxt else "")
        slope, f0_end, reset = pitch_feats(pt, pst, w, nxt)
        gaps.append({
            "after": w["i"], "left": w["text"], "right": nxt["text"] if nxt else None,
            "t": round(a, 3), "pause": round(max(0.0, b - a), 3),
            "vad_pause": vad_silence(vp, a, b, (w["start"] + w["end"]) / 2, ((nxt["start"] + nxt["end"]) / 2) if nxt else dur),
            "sat": sat[k], "sat_p": sat_p[k], "punct": punct_class(w["text"]), "left_q": w["text"].rstrip().endswith("?"),
            "turn": round(turn[k], 4), "f0_slope": slope, "f0_end": f0_end, "f0_reset": reset,
            "left_hard": left in LEFT_HARD, "left_soft": left in LEFT_SOFT and left not in LEFT_HARD,
            "right_hard": right in RIGHT_HARD, "right_soft": right in RIGHT_SOFT,
            "hindi_final": left in HINDI_FINAL, "tag": left in TAGS, "starter": right in STARTERS,
            "filler_left": left in FILLERS, "filler_right": right in FILLERS,
        })
    return gaps, {"duration": round(dur, 2), "f0_median_hz": round(med, 1), "timing": timing}


def build(job: str, force: bool = False, model: str = SAT_MODEL, log=print) -> dict:
    """The sentence map of a take (cached in output/temp/jobs/<job>/sentmap.json; rebuilt when the words or the
    version change, or when temp was deleted)."""
    path = job_temp(job) / "sentmap.json"
    words = load_words(job)
    import hashlib
    key = hashlib.sha1(f"{VERSION}|{model}|{json.dumps(words)}".encode()).hexdigest()    # any change to the words rebuilds
    if path.exists() and not force:
        old = json.loads(path.read_text())
        if old.get("key") == key:
            rescore(old)
            return old
    t0 = time.time()
    gaps, info = features(job, model, log)
    sm = {"job": job, "key": key, "version": VERSION, "model": model, "language": job_language(job), **info,
          "runtime_s": None, "gaps": gaps}
    rescore(sm)
    sm["runtime_s"] = round(time.time() - t0, 2)
    sm["runtime_per_min"] = round(sm["runtime_s"] / max(info["duration"] / 60, 1e-6), 2)
    path.write_text(json.dumps(sm, indent=0, ensure_ascii=False))
    return sm


def rescore(sm: dict, weights: dict = WEIGHTS) -> dict:
    """(Re)apply the model: p and label per gap. Cheap; the features stay cached."""
    for g in sm["gaps"]:
        g["p"] = round(p_boundary(g, weights), 4)
        g["label"] = label_of(g["p"])
    sm["weights"] = weights
    sm["thresholds"] = {"sentence_end": P_SENT, "clause_end": P_CLAUSE}
    return sm


class SentMap:
    """Lookup over a take's gaps: p_end(k) = boundary after word k; p_start(k) = boundary before word k."""

    def __init__(self, sm: dict):
        self.sm = sm
        self.gaps = {g["after"]: g for g in sm["gaps"]}
        self.n = len(sm["gaps"])

    @classmethod
    def load(cls, job: str, force: bool = False) -> "SentMap":
        return cls(build(job, force=force))

    def p_end(self, k: int) -> float:
        return self.gaps[k]["p"] if k in self.gaps else 1.0

    def p_start(self, k: int) -> float:
        return 1.0 if k <= 0 else self.p_end(k - 1)

    def label_end(self, k: int) -> str:
        return label_of(self.p_end(k))

    def label_start(self, k: int) -> str:
        return label_of(self.p_start(k))


def main(argv: list[str]) -> int:
    jobs = [a for a in argv if not a.startswith("--")]
    force = "--force" in argv
    model = next((a.split("=", 1)[1] for a in argv if a.startswith("--model=")), SAT_MODEL)
    if not jobs:
        print(__doc__)
        return 1
    for job in jobs:
        sm = build(job, force=force, model=model)
        labels = [g["label"] for g in sm["gaps"]]
        print(f"{job}: {len(labels)} gaps, {labels.count('sentence_end')} sentence ends, {labels.count('clause_end')} clause ends, "
              f"{sm['duration']:.0f} s audio, built in {sm['runtime_s']} s ({sm['runtime_per_min']} s per audio minute) "
              f"-> {job_temp(job) / 'sentmap.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
