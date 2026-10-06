"""Re-listen to joins in the exported audio: re-transcribe t-8 s .. t+4 s around each join with whisper.cpp (one call
for all windows), compare with the words the edit meant to keep, and ask whether a sentence boundary is heard there.

    from kit.cut.relisten import relisten
    res = relisten("final.mp4", [{"t": 12.3, "words": [...intended words in the window...]}, ...], hinglish=False)

Per join it returns: wer (jiwer, whole window), missing (intended words within +/-1.2 s of the join that the fresh
transcript does not have), heard (the fresh text around the join, '|' at the join), boundary_sat (SaT probability of a
sentence boundary at the join in the fresh text, which carries whisper's own punctuation from the spliced audio) and
mark (whisper's punctuation on the word before the join).
"""
from __future__ import annotations

import difflib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from kit.cut.common import CACHE as CACHE_ROOT, ROOT, norm

WIN_BEFORE, WIN_AFTER = 8.0, 4.0
NEAR = 1.2


def _whisper_cfg():
    import sys
    sys.path.insert(0, str(ROOT))
    from shorts import config
    return config


def _extract(media: Path, t0: float, dur: float, out: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t0):.3f}", "-t", f"{dur:.3f}", "-i", str(media), "-vn",
                    "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)], check=True)


def _parse(path: Path) -> list[dict]:
    from shorts.analyze.transcribe import parse_whisper
    if not path.exists():
        return []
    _, words = parse_whisper(json.loads(path.read_text(errors="replace")))
    return [{"text": w.text, "start": w.start, "end": w.end} for w in words]


CACHE = CACHE_ROOT / "relisten"                              # output/temp/cache; keyed by the window's audio + prompt


def transcribe_many(wavs: list[Path], hinglish: bool) -> list[list[dict]]:
    import hashlib
    cfg = _whisper_cfg()
    prompt = cfg.HINGLISH_PROMPT if hinglish else cfg.WHISPER_PROMPT
    keys = [hashlib.sha1(w.read_bytes() + prompt.encode() + cfg.WHISPER_MODEL.name.encode()).hexdigest() for w in wavs]
    todo = [w for w, k in zip(wavs, keys) if not (CACHE / f"{k}.json").exists()]
    if todo:
        # full 30 s encoder context on purpose: a reduced -ac (12 s) was 2x faster but split words ("ultra code") and
        # lost Hinglish words, which made the re-listen noisier (measured on the ExpenseWaale Short)
        cmd = [shutil.which("whisper-cli") or "whisper-cli", "-m", str(cfg.WHISPER_MODEL), "-t", "8", "-l", "en", "-ojf", "-np",
               "--prompt", prompt]
        for w in todo:
            cmd += ["-f", str(w)]
        subprocess.run(cmd, capture_output=True, text=True)
        CACHE.mkdir(parents=True, exist_ok=True)
        for w, k in zip(wavs, keys):
            if w in todo:
                (CACHE / f"{k}.json").write_text(json.dumps(_parse(Path(str(w) + ".json"))))
    return [json.loads((CACHE / f"{k}.json").read_text()) if (CACHE / f"{k}.json").exists() else [] for k in keys]


_CONTRACT = {"i'll": "i will", "i'm": "i am", "i've": "i have", "i'd": "i would", "it's": "it is", "that's": "that is",
             "let's": "let us", "don't": "do not", "won't": "will not", "can't": "can not", "you're": "you are",
             "we're": "we are", "they're": "they are", "there's": "there is", "what's": "what is", "gonna": "going to",
             "wanna": "want to", "isn't": "is not", "doesn't": "does not", "didn't": "did not"}


def _tokens(words: list[dict]) -> tuple[list[str], list[int]]:
    """Comparable tokens (contractions expanded, plural s dropped) and, per token, the index of its word."""
    toks, owner = [], []
    for i, w in enumerate(words):
        t = norm(w["text"])
        for x in _CONTRACT.get(t, t).split():
            x = x.replace("'", "")
            x = x[:-1] if len(x) > 3 and x.endswith("s") else x
            if x:
                toks.append(x)
                owner.append(i)
    return toks, owner


def relisten(media: str | Path, joins: list[dict], hinglish: bool = False, keep_dir: Path | None = None) -> list[dict]:
    """joins: [{"t": join time on the media timeline, "left": index of the join's left word in "words",
    "words": [{"text", "t"}] the intended words around it (output timeline)}]."""
    from jiwer import wer as jwer
    from kit.cut.sentmap import sat_word_probs
    media = Path(media)
    tmp = Path(tempfile.mkdtemp(prefix="relisten_", dir=keep_dir))
    wavs, starts = [], []
    for k, j in enumerate(joins):
        t0 = max(0.0, j["t"] - WIN_BEFORE)
        p = tmp / f"j{k:03d}.wav"
        _extract(media, t0, WIN_BEFORE + WIN_AFTER, p)
        wavs.append(p)
        starts.append(t0)
    heard_all = transcribe_many(wavs, hinglish) if wavs else []
    out = []
    for j, t0, heard in zip(joins, starts, heard_all):
        want = j["words"]
        res = {"t": j["t"]}
        ref = " ".join(norm(w["text"]) for w in want if norm(w["text"]))
        hyp = " ".join(norm(w["text"]) for w in heard if norm(w["text"]))
        res["wer"] = round(float(jwer(ref, hyp)), 3) if ref and hyp else None
        if not heard:
            out.append(res)
            continue
        # anchor the join in the fresh transcript by text (whisper's own word times drift by a few hundred ms)
        a, ao = _tokens(want)
        b, bo = _tokens(heard)
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        heard_of = {}                                   # intended word index -> heard word index
        for blk in sm.get_matching_blocks():
            for q in range(blk.size):
                heard_of.setdefault(ao[blk.a + q], bo[blk.b + q])
        L = j["left"]
        ia = next((heard_of[q] for q in range(L, max(-1, L - 4), -1) if q in heard_of), None)
        ib = next((heard_of[q] for q in range(L + 1, min(len(want), L + 5)) if q in heard_of), None)
        res["missing"] = [want[q]["text"] for q in range(max(0, L - 1), min(len(want), L + 3)) if q not in heard_of and norm(want[q]["text"])]
        res["left_heard"], res["right_heard"] = L in heard_of, (L + 1) in heard_of
        if ia is None or ib is None or ib <= ia:
            res["anchored"] = False
            out.append(res)
            continue
        res["anchored"] = True
        res["extra"] = [heard[q]["text"] for q in range(ia + 1, ib)]
        probs = sat_word_probs([norm(w["text"]) or "-" for w in heard])
        res["boundary_sat"] = probs[ia]
        last = heard[ia]["text"].rstrip("\"')")
        res["mark"] = last[-1] if last[-1:] in ".?!,;:" else ""
        res["heard"] = " ".join(w["text"] for w in heard[max(0, ia - 7):ia + 1]) + " | " + " ".join(w["text"] for w in heard[ia + 1:ia + 7])
        out.append(res)
    if keep_dir is None:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def load_mono(media: str | Path, sr: int = 16000) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(media), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def voice_band_db(x: np.ndarray, sr: int = 16000) -> np.ndarray:
    """Level of the voice band (250-4000 Hz) per 10 ms frame, in dB."""
    hop, nfft = sr // 100, 512
    n = max(0, (len(x) - nfft) // hop)
    out = np.empty(n, np.float32)
    win = np.hanning(nfft).astype(np.float32)
    f = np.fft.rfftfreq(nfft, 1 / sr)
    band = (f >= 250) & (f <= 4000)
    for a in range(0, n, 4096):                       # in blocks: a 5-minute mix is 30k frames
        b = min(n, a + 4096)
        idx = np.arange(nfft)[None, :] + hop * np.arange(a, b)[:, None]
        spec = np.abs(np.fft.rfft(x[idx] * win, axis=1)) ** 2
        out[a:b] = 10 * np.log10(spec[:, band].sum(1) + 1e-10)
    return out


def gaps_at(media: str | Path, times: list[float], dip_db: float = 10.0) -> list[float]:
    """The pause the viewer hears at each time (s): the longest run of 10 ms frames whose voice-band level sits
    `dip_db` under the local speech level (80th percentile of +/-1 s), within +/-150 ms of the time. Works on a final
    mix with a music bed under the voice (an absolute silence floor does not). Measured: the sliver pauses of the
    ExpenseWaale cut read 0.13-0.33 s; a glued join reads under 0.06 s."""
    db = voice_band_db(load_mono(media))
    n = len(db)
    out = []
    for t in times:
        k = int(t * 100)
        if not 0 <= k < n:
            out.append(0.0)
            continue
        lvl = np.percentile(db[max(0, k - 100):k + 100], 80)
        quiet = db < lvl - dip_db
        best = 0
        c = max(0, k - 15)
        while c < min(n, k + 16):
            if quiet[c]:
                a = c
                while a > 0 and quiet[a - 1]:
                    a -= 1
                b = c
                while b + 1 < n and quiet[b + 1]:
                    b += 1
                best = max(best, b - a + 1)
                c = b + 1
            else:
                c += 1
        out.append(round(best / 100, 3))
    return out
