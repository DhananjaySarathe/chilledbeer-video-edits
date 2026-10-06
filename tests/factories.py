"""Build analyses and job folders for tests without running real media tools."""
from __future__ import annotations

import numpy as np

from shorts.analyze.words import find_pauses, group_sentences
from shorts.job import Job
from shorts.schemas import Analysis, Brief, FaceBox, Loudness, Picture, SourceInfo, Style, Word

HOP = 0.01


def make_analysis(text: str, word_s: float = 0.3, gap_s: float = 0.05, pauses_after: dict[int, float] | None = None,
                  fps: int = 30, lead_s: float = 0.5) -> Analysis:
    """Evenly timed words separated by clean silences. pauses_after = {word index: gap in seconds after it}."""
    pauses_after = pauses_after or {}
    words, t = [], lead_s
    for i, tok in enumerate(text.split()):
        words.append(Word(i=i, text=tok, start=round(t, 3), end=round(t + word_s, 3), start_gap=True, end_gap=True))
        t += word_s + pauses_after.get(i, gap_s)
    duration = round(words[-1].end + 0.5, 3)
    return Analysis(
        source=SourceInfo(path="in.mp4", working_path="in.mp4", duration=duration, fps=fps,
                          frames=int(round(duration * fps)), width=1080, height=1920, normalized=False),
        language="en", words=words, sentences=group_sentences(words), pauses=find_pauses(words),
        speech_db=-20.0, floor_db=-60.0, quiet_db=-46.0, dip_db=-38.0,
        loudness=Loudness(integrated=-18.0, lra=5.0, true_peak=-2.0),
        picture=Picture(fps=2.0, face_presence=1.0, face_box=FaceBox(x=390, y=500, w=300, h=360),
                        face_track=[[390.0, 500.0, 300.0, 360.0]] * int(duration * 2 + 1)),
        contact_sheet="contact.png")


def make_energy(analysis: Analysis) -> np.ndarray:
    """dB per 10 ms: speech level inside words, the noise floor between them."""
    db = np.full(int(np.ceil(analysis.source.duration / HOP)) + 1, analysis.floor_db, np.float32)
    for w in analysis.words:
        db[int(round(w.start / HOP)): int(round(w.end / HOP))] = analysis.speech_db
    return db


def make_job(name: str, analysis: Analysis, brief: Brief | None = None, style: Style | None = None) -> Job:
    """A job folder as if probe, analyze and init-brief had run (uses config.JOBS, so pair with jobs_root)."""
    job = Job.create(name)
    job.write("analysis.json", analysis.model_dump())
    job.write("brief.json", (brief or Brief()).model_dump())
    job.write("style.json", (style or Style()).model_dump())
    np.save(job.work / "energy.npy", make_energy(analysis))
    return job


from shorts.decide.jev import Answer  # noqa: E402  (factories grows task by task)


class FakeAsker:
    """Stands in for Jev: returns canned answers for the question ids it was given."""

    def __init__(self, answers: dict[str, Answer] | None = None):
        self.answers = answers or {}
        self.state: dict = {}
        self.questions: dict = {}

    def ask(self, state: dict, questions: dict[str, dict]):
        self.state, self.questions = state, questions
        return {k: v for k, v in self.answers.items() if k in questions}, {"model": "fake-jev", "input_tokens": 1234}


def noul(p: float) -> Answer:
    return Answer("noul", p, max(p, 1 - p), {"true": p, "false": 1 - p})


def choice(label: str, probs: dict[str, float]) -> Answer:
    return Answer("choice", label, probs[label], probs)


from pathlib import Path  # noqa: E402

from shorts.schemas import AudioSpec, CaptionPage, Captions, CaptionWord, EditFile, OutputSpec, Segment  # noqa: E402
from tests.media import make_clip  # noqa: E402


def make_captions(pages: list[CaptionPage]) -> Captions:
    return Captions(template="bold_pop", font="Montserrat-800.ttf", font_size=88, text_color="#FFFFFF",
                    highlight_color="#FFD400", outline_color="#000000", outline_px=6, shadow_px=0, spacing=0.0,
                    uppercase=True, center_x=507.6, center_y=1152.0, max_width=853.6, pages=pages)


def make_edit_job(name: str, folder: Path, seconds: float = 4.0) -> Job:
    """A job with a real 1080x1920 test clip and a hand-made edit: two segments (the second zoomed) and captions."""
    src = make_clip(folder / f"{name}.mp4", seconds=seconds)
    job = Job.create(name)
    cap = make_captions([
        CaptionPage(start=0.1, end=0.9, words=[CaptionWord(text="HELLO", start=0.1, end=0.5),
                                               CaptionWord(text="THERE", start=0.5, end=0.9, highlight=True)]),
        CaptionPage(start=1.0, end=1.9, words=[CaptionWord(text="SECOND", start=1.0, end=1.9)])])
    edit = EditFile(source=str(src.resolve()), source_frames=int(seconds * 30), output=OutputSpec(fps=30),
                    segments=[Segment(in_frame=0, out_frame=30, first_word=0, last_word=1),
                              Segment(in_frame=60, out_frame=90, first_word=2, last_word=2, zoom=1.08,
                                      crop=[1000, 1778, 40, 22])],
                    captions=cap, audio=AudioSpec(source_integrated=-20.0), duration=2.0)
    job.write("edit.json", edit.model_dump())
    job.write("analysis.json", make_analysis("hello there second").model_dump())
    return job
