"""Speech to text with whisper.cpp. Word text comes from here; exact word times come from the aligner.

Hindi and Hinglish speech needs care (measured on video2 and video3, 2026-09-27):
- whisper's "hi" output is Devanagari, and it skipped 15 s of video3;
- whole-clip English decoding translates mixed speech into invented English ("you can make a roti" on loop);
- English decoding of SHORT chunks, primed with romanized Hinglish, writes what was said in Latin script.
So Hinglish is transcribed chunk by chunk (cut at pauses), with a second prompt for chunks that come back
suspiciously short, and whisper's loops and prompt echoes are removed.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from shorts import config
from shorts.analyze.audio import HOP_S, energy_db, levels, read_wav
from shorts.proc import run

_BRACKETED = re.compile(r"^[\[(].*[\])]$")
HINGLISH_VERSION = 2          # bump to invalidate cached Hinglish transcripts when the method changes
CHUNK_TARGET_S, CHUNK_MAX_S, CHUNK_MIN_S = 6.0, 8.0, 2.0
MIN_WORDS_PER_SPEECH_S = 1.4  # Hinglish runs ~2.5-3.5 words/s; far fewer means whisper skipped speech
MAX_WORDS_PER_SPEECH_S = 5.5


@dataclass
class RawWord:
    text: str
    start: float
    end: float
    p: float


def whisper_cmd(whisper: str, wav: Path, out_base: Path, language: str = "auto",
                prompt: str = config.WHISPER_PROMPT, threads: int = 8) -> list[str]:
    if language == "hinglish":                    # romanized Hindi: English decoding primed with Hinglish
        language, prompt = "en", config.HINGLISH_PROMPT
    return [whisper, "-m", str(config.WHISPER_MODEL), "-f", str(wav), "-l", language, "-ojf", "-of", str(out_base),
            "-t", str(threads), "-np", "--prompt", prompt]


def parse_whisper(data: dict) -> tuple[str, list[RawWord]]:
    language = (data.get("result") or {}).get("language") or "en"
    words: list[RawWord] = []
    for seg in data.get("transcription") or []:
        for tok in seg.get("tokens") or []:
            text = tok.get("text", "")
            if text.startswith("[_"):
                continue
            start, end = tok["offsets"]["from"] / 1000.0, tok["offsets"]["to"] / 1000.0
            p = float(tok.get("p", 1.0))
            if text.startswith(" ") or not words:
                words.append(RawWord(text.strip(), start, end, p))
            else:
                last = words[-1]
                last.text += text
                last.end = max(last.end, end)
                last.p = min(last.p, p)
    words = [w for w in words if w.text and re.search(r"\w", w.text) and not _BRACKETED.match(w.text)]
    return language, collapse_loops(words)


def _norm(text: str) -> str:
    return re.sub(r"[^\w']", "", text.lower())


def collapse_loops(words: list[RawWord]) -> list[RawWord]:
    """Remove whisper's decoding loops: a phrase of 2-5 words repeated 3+ times in a row, or one word 4+ times,
    keeps its first occurrence ("uske baad, uske baad, uske baad, uske baad" -> "uske baad"). Twice is kept:
    people do say "baar baar"."""
    out = list(words)
    changed = True
    while changed:
        changed = False
        keys = [_norm(w.text) for w in out]
        for n in (1, 2, 3, 4, 5):
            need = 4 if n == 1 else 3
            i = 0
            while i + n * need <= len(out):
                gram = keys[i:i + n]
                reps = 1
                while keys[i + reps * n: i + (reps + 1) * n] == gram:
                    reps += 1
                if reps >= need and any(gram):
                    del out[i + n: i + reps * n]
                    del keys[i + n: i + reps * n]
                    changed = True
                i += 1
    return out


def drop_prompt_echo(words: list[RawWord], prompt: str, run_len: int = 5) -> list[RawWord]:
    """Whisper sometimes 'hears' the prompt in quiet audio: drop any run of run_len+ words copied from it."""
    p = [_norm(w) for w in prompt.split()]
    grams = {tuple(p[i:i + run_len]) for i in range(len(p) - run_len + 1)}
    keys = [_norm(w.text) for w in words]
    kill = set()
    for i in range(len(words) - run_len + 1):
        if tuple(keys[i:i + run_len]) in grams:
            kill.update(range(i, i + run_len))
    return [w for i, w in enumerate(words) if i not in kill]


def speech_chunks(db: np.ndarray, hop: float = HOP_S, target: float = CHUNK_TARGET_S, max_s: float = CHUNK_MAX_S,
                  min_s: float = CHUNK_MIN_S) -> list[tuple[float, float]]:
    """Cut the clip into ~target-second pieces at its quietest moments (never inside a word if a pause exists)."""
    total = len(db) * hop
    if total <= max_s:
        return [(0.0, round(total, 3))]
    k = max(1, int(0.2 / hop))
    smooth = np.convolve(db, np.ones(k) / k, mode="same")
    out, t0 = [], 0.0
    while total - t0 > max_s:
        a, b = int((t0 + min_s) / hop), int((t0 + max_s) / hop)
        t = np.arange(a, b) * hop
        idx = int(np.argmin(smooth[a:b] + 1.5 * np.abs(t - (t0 + target))))   # quiet first, near the target second
        cut = round((a + idx) * hop, 3)
        out.append((round(t0, 3), cut))
        t0 = cut
    out.append((round(t0, 3), round(total, 3)))
    return out


def transcribe(whisper: str, wav: Path, work: Path, language: str = "auto", force: bool = False) -> dict:
    """Run whisper.cpp once per unique (audio, model, prompt, language); reuse the cached JSON otherwise.
    With "auto", Hindi speech, or 'English' whose chunks sound Hindi, is transcribed as romanized Hinglish."""
    # the chunk check runs first (~3 s): for Hinglish it saves the whole-clip pass (~6 s) that would be thrown away
    if language == "hinglish" or (language == "auto" and _sounds_hindi(whisper, wav, work, force)):
        return _hinglish(whisper, wav, work, force)
    data = _whisper(whisper, wav, work, language, force)
    if language == "auto" and (data.get("result") or {}).get("language") in config.HINDI_LANGS:
        return _hinglish(whisper, wav, work, force)
    return data


def _whisper(whisper: str, wav: Path, work: Path, language: str, force: bool) -> dict:
    key = hashlib.sha1(wav.read_bytes() + f"{config.WHISPER_MODEL.name}|{config.WHISPER_PROMPT}|{language}".encode()).hexdigest()
    out_base = work / "whisper"
    key_file, out_json = out_base.with_suffix(".key"), out_base.with_suffix(".json")
    if force or not (key_file.exists() and key_file.read_text() == key and out_json.exists()):
        run(whisper_cmd(whisper, wav, out_base, language), code="E_WHISPER", what="Transcribing with whisper.cpp",
            log=work / "whisper.log")
        key_file.write_text(key)
    return json.loads(out_json.read_text(errors="replace"))


def _chunk_files(wav: Path, work: Path) -> tuple[list[tuple[float, float, Path, float]], np.ndarray]:
    """Write the speech chunks as wav files: [(start, end, path, speech seconds)]."""
    samples, sr = read_wav(wav)
    db = energy_db(samples, sr)
    quiet = levels(db)[2]
    folder = work / "chunks"
    folder.mkdir(parents=True, exist_ok=True)
    import wave
    out = []
    for k, (a, b) in enumerate(speech_chunks(db)):
        p = folder / f"c{k:03d}.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((samples[int(a * sr): int(b * sr)] * 32767).astype(np.int16).tobytes())
        speech = float(np.sum(db[int(a / HOP_S): int(b / HOP_S)] > quiet) * HOP_S)
        out.append((a, b, p, speech))
    return out, db


def _run_many(whisper: str, files: list[Path], args: list[str], log: Path) -> str:
    cmd = [whisper, "-m", str(config.WHISPER_MODEL), "-t", "8", *args]
    for f in files:
        cmd += ["-f", str(f)]
    return run(cmd, code="E_WHISPER", what="Transcribing with whisper.cpp", log=log).stderr or ""


def _sounds_hindi(whisper: str, wav: Path, work: Path, force: bool) -> bool:
    """Whisper calls mixed Hinglish 'en': ask it about a few chunks; any chunk heard as Hindi counts."""
    key = hashlib.sha1(wav.read_bytes() + config.WHISPER_MODEL.name.encode()).hexdigest()
    cache = work / "langcheck.json"
    if not force and cache.exists():
        known = json.loads(cache.read_text())
        if known.get("key") == key:
            return bool(known["hindi"])
    chunks, _ = _chunk_files(wav, work)
    pick = sorted(chunks, key=lambda c: -c[3])[:4]
    err = _run_many(whisper, [c[2] for c in pick], ["-dl", "-l", "auto"], work / "langcheck.log")
    langs = re.findall(r"auto-detected language: (\w+)", err)
    hindi = any(lang in config.HINDI_LANGS for lang in langs)
    cache.write_text(json.dumps({"key": key, "languages": langs, "hindi": hindi}))
    return hindi


def _decode(whisper: str, chunks: list, prompt: str, log: Path) -> dict[Path, dict]:
    for c in chunks:
        c[2].with_suffix(".wav.json").unlink(missing_ok=True)
    _run_many(whisper, [c[2] for c in chunks], ["-l", "en", "-ojf", "-np", "--prompt", prompt], log)
    out = {}
    for c in chunks:
        j = Path(str(c[2]) + ".json")
        out[c[2]] = json.loads(j.read_text(errors="replace")) if j.exists() else {"transcription": []}
    return out


def _words_in(data: dict, prompt: str) -> list[RawWord]:
    return drop_prompt_echo(parse_whisper(data)[1], prompt)


def _hinglish(whisper: str, wav: Path, work: Path, force: bool) -> dict:
    prompts = (config.HINGLISH_PROMPT, config.HINGLISH_PROMPT_ALT)
    key = hashlib.sha1(wav.read_bytes() + f"{config.WHISPER_MODEL.name}|{prompts}|{HINGLISH_VERSION}".encode()).hexdigest()
    out_json, key_file = work / "whisper-hinglish.json", work / "whisper-hinglish.key"
    if not force and key_file.exists() and key_file.read_text() == key and out_json.exists():
        return json.loads(out_json.read_text(errors="replace"))
    chunks, _ = _chunk_files(wav, work)
    first = _decode(whisper, chunks, prompts[0], work / "whisper-hinglish.log")
    best = {c[2]: _words_in(first[c[2]], prompts[0]) for c in chunks}
    # a chunk with far fewer words than its speech needs was partly skipped: decode it again, other prompt
    short = [c for c in chunks if c[3] > 1.0 and len(best[c[2]]) < MIN_WORDS_PER_SPEECH_S * c[3]]
    retried = []
    if short:
        second = _decode(whisper, short, prompts[1], work / "whisper-hinglish-retry.log")
        for c in short:
            alt = _words_in(second[c[2]], prompts[1])
            if len(best[c[2]]) < len(alt) <= MAX_WORDS_PER_SPEECH_S * c[3]:
                best[c[2]] = alt
                retried.append(c[2].name)
    # one merged whisper-style document, times shifted to the clip, one token per word
    segs = []
    for a, b, path, _ in chunks:
        toks = [{"text": " " + w.text, "p": w.p,
                 "offsets": {"from": int(round((a + w.start) * 1000)), "to": int(round((a + w.end) * 1000))}}
                for w in best[path]]
        if toks:
            segs.append({"offsets": {"from": int(a * 1000), "to": int(b * 1000)},
                         "text": " ".join(w.text for w in best[path]), "tokens": toks})
    data = {"result": {"language": "hinglish"}, "transcription": segs,
            "chunks": [{"start": a, "end": b, "speech_s": round(s, 2), "words": len(best[p])} for a, b, p, s in chunks],
            "retried": retried}
    out_json.write_text(json.dumps(data, ensure_ascii=False))
    key_file.write_text(key)
    return data
