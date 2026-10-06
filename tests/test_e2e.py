import pytest

from shorts import config
from shorts.analyze.run import analyze
from shorts.analyze.words import bare
from shorts.brief import init_brief
from shorts.check.run import check
from shorts.decide.run import decide
from shorts.job import Job
from shorts.media.run import probe
from shorts.plan.run import plan
from shorts.render.run import preview, render
from shorts.schemas import Analysis, EditFile
from tests.factories import FakeAsker
from tests.media import make_speech_clip

models_ready = all(p.exists() for p in (config.WHISPER_MODEL, config.ALIGN_MODEL, config.FACE_MODEL))


@pytest.mark.slow
@pytest.mark.skipif(not models_ready, reason="run `uv run shorts setup` first")
def test_full_pipeline_on_generated_speech(tmp_path, jobs_root):
    src = make_speech_clip(tmp_path / "talk.mp4", "Hi everyone. So, uh, today I am testing a brand new app. "
                                                   "It can edit your videos by itself. Let's see what it can do.")
    probe(str(src), "e2e")
    job = Job.open("e2e")
    analyze(job, language="en")
    init_brief("e2e")
    decide(job, FakeAsker())            # no answers: cosmetic items take defaults, the rest stay pending
    plan(job)
    preview(job)
    render(job)
    result = check(job)
    assert result["passed"], result["checks"]
    analysis = Analysis.model_validate(job.read("analysis.json"))
    edit = EditFile.model_validate(job.read("edit.json"))
    kept = [analysis.words[i].text for s in edit.segments for i in range(s.first_word, s.last_word + 1)]
    assert "uh" not in [bare(t) for t in kept] and len(kept) >= 15
