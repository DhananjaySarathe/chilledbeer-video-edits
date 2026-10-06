"""`shorts analyze`: hear, align, measure and look at the clip, all at once, then write analysis.json."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from shorts import config
from shorts.analyze.align import Aligner, align_words, load_vocab
from shorts.analyze.audio import energy_db, extract_wav, levels, measure_loudness, read_wav
from shorts.analyze.contact import contact_sheet, save_png
from shorts.analyze.picture import picture_pass, summarize
from shorts.analyze.transcribe import parse_whisper, transcribe
from shorts.analyze.words import OBVIOUS_FILLERS, bare, find_pauses, group_sentences, place_fillers, refine_words
from shorts.job import Job
from shorts.schemas import Analysis, Loudness, Picture, SourceInfo, Word


def collect_warnings(language: str, words: list[Word], loudness: dict, picture: dict) -> list[str]:
    out: list[str] = []
    if language == "hinglish":
        out.append("language_hinglish: Hindi speech, written as romanized Hinglish; fix misspelt words with caption_overrides in brief.json.")
    elif language != "en":
        out.append(f"language_{language}: the transcript may be in Hindi script or translated; check captions and use caption_overrides in brief.json.")
    if any(re.search(r"[ऀ-ॿ]", w.text) for w in words):
        out.append("devanagari_text: some words are in Hindi script; respell them in Latin script via caption_overrides.")
    if words and sum(w.aligned for w in words) / len(words) < 0.9:
        out.append("alignment_partial: some word times are estimates; cuts next to them will be avoided.")
    li = loudness.get("integrated")
    if li is not None and li < -32:
        out.append(f"quiet_recording: {li:.1f} LUFS; it will be normalised, but background noise will rise too.")
    if picture["face_presence"] < 0.6:
        out.append(f"face_missing: a face is visible in only {picture['face_presence'] * 100:.0f}% of samples.")
    out += [f"blurry: {r['start']}-{r['end']} s" for r in picture["blurry"]]
    out += [f"dark: {r['start']}-{r['end']} s" for r in picture["dark"]]
    if not words:
        out.append("no_speech: no words were transcribed.")
    return out


def analyze(job: Job, language: str = "auto", force: bool = False) -> dict:
    probe = job.read("probe.json")
    src, winfo = probe["working_path"], probe["working"]
    fps = int(probe["plan"]["target_fps"])
    duration = float(winfo["duration"])
    ffmpeg, whisper = config.tool("ffmpeg"), config.tool("whisper-cli")
    with job.timed("analyze"):
        wav = extract_wav(ffmpeg, src, job.work / "audio16k.wav")
        samples, sr = read_wav(wav)
        db = energy_db(samples, sr)
        speech_db, floor_db, quiet_db, dip_db = levels(db)
        with ThreadPoolExecutor(max_workers=4) as pool:
            f_text = pool.submit(transcribe, whisper, wav, job.work, language, force)
            f_emis = pool.submit(lambda: Aligner().emissions(samples, sr))
            f_pic = pool.submit(picture_pass, ffmpeg, src, duration)
            f_loud = pool.submit(measure_loudness, ffmpeg, src)
            lang, raw = parse_whisper(f_text.result())
            logp, frame_s = f_emis.result()
            pic_samples, thumbs = f_pic.result()
            loud = f_loud.result()
        texts = [w.text for w in raw]
        spans = place_fillers(texts, align_words(logp, frame_s, texts, load_vocab(), wildcard=OBVIOUS_FILLERS),
                              db, dip_db)
        words = refine_words(raw, spans, db, quiet_db, gap_db=dip_db)
        sentences = group_sentences(words)
        np.save(job.work / "energy.npy", db)
        save_png(contact_sheet(thumbs), job.work / "contact.png")
        picture = summarize(pic_samples)
        w, h = winfo["display_size"]
        frames = int(winfo.get("nb_frames") or round(duration * fps))
        analysis = Analysis(
            source=SourceInfo(path=probe["input"], working_path=src, duration=duration, fps=fps, frames=frames,
                              width=w, height=h, normalized=probe["plan"]["needed"]),
            language=lang, words=words, sentences=sentences, pauses=find_pauses(words),
            speech_db=speech_db, floor_db=floor_db, quiet_db=quiet_db, dip_db=dip_db,
            loudness=Loudness(**loud), picture=Picture(**picture), contact_sheet="contact.png",
            warnings=collect_warnings(lang, words, loud, picture))
        job.write("analysis.json", analysis.model_dump())
    return {
        "job": job.name, "language": lang, "duration": round(duration, 3), "words": len(words),
        "fillers_seen": [f"{x.text}@{x.start:.2f}s" for x in words if bare(x.text) in OBVIOUS_FILLERS],
        "sentences": [{"id": s.id, "start": s.start, "end": s.end, "text": s.text} for s in sentences],
        "pauses": len(analysis.pauses), "loudness": loud, "face_presence": picture["face_presence"],
        "warnings": analysis.warnings, "contact_sheet": str(job.work / "contact.png"),
        "timing_s": job.read("timings.json").get("analyze"), "next": f"shorts init-brief {job.name}",
    }


def add_command(sub) -> None:
    p = sub.add_parser("analyze", help="Transcribe, align, measure and sample the clip.")
    p.add_argument("job")
    p.add_argument("--language", default="auto", help="whisper language code, hinglish, or auto (default; Hindi becomes hinglish)")
    p.add_argument("--force", action="store_true", help="re-run Whisper even if a cached transcript exists")
    p.set_defaults(func=lambda a: analyze(Job.open(a.job), a.language, a.force))
