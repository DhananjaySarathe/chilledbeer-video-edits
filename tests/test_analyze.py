import pytest

from shorts import config
from shorts.analyze.run import analyze, collect_warnings
from shorts.job import Job
from shorts.media.run import probe
from shorts.schemas import Analysis, Word
from tests.media import make_speech_clip

models_ready = all(p.exists() for p in (config.WHISPER_MODEL, config.ALIGN_MODEL, config.FACE_MODEL))


def test_collect_warnings():
    words = [Word(i=0, text="नमस्ते", start=0.1, end=0.5, aligned=False)]
    pic = {"face_presence": 0.2, "blurry": [{"start": 1.0, "end": 2.5}], "dark": []}
    w = collect_warnings("hi", words, {"integrated": -35.0}, pic)
    joined = " ".join(w)
    for key in ("language_hi", "devanagari_text", "alignment_partial", "quiet_recording", "face_missing", "blurry"):
        assert key in joined


def test_no_warnings_for_clean_input():
    words = [Word(i=0, text="hello", start=0.1, end=0.5)]
    assert collect_warnings("en", words, {"integrated": -18.0}, {"face_presence": 1.0, "blurry": [], "dark": []}) == []


@pytest.mark.slow
@pytest.mark.skipif(not models_ready, reason="run `uv run shorts setup` first")
def test_analyze_speech_clip(tmp_path, jobs_root):
    src = make_speech_clip(tmp_path / "talk.mp4", "Hi everyone. So, uh, today I am testing a new app. Let's see what it can do.")
    probe(str(src), "talk")
    out = analyze(Job.open("talk"), language="en")
    job = Job.open("talk")
    a = Analysis.model_validate(job.read("analysis.json"))
    assert a.language == "en" and len(a.words) >= 10 and len(a.sentences) >= 2
    assert all(w.aligned for w in a.words)
    assert (job.work / "contact.png").exists() and (job.work / "energy.npy").exists()
    assert "analyze" in job.read("timings.json")
    assert out["sentences"][0]["id"] == "s1"
