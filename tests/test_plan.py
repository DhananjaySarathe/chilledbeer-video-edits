import pytest

from shorts.decide.run import decide
from shorts.errors import ShortsError
from shorts.plan.run import plan
from shorts.plan.validate import validate_edit
from shorts.schemas import Brief, EditFile
from tests.factories import FakeAsker, make_analysis, make_job, noul

# So(0) today(1) I(2) am(3) testing(4) a(5) new(6) app.(7) Uh(8) basically(9) it(10) is(11) amazing.(12)
# It(13) edits(14) videos(15) by(16) itself.(17)
TEXT = "So today I am testing a new app. Uh basically it is amazing. It edits videos by itself."
ALL_NO = {"false_start:s1": noul(0.02), "false_start:s2": noul(0.02), "filler:0": noul(0.02), "filler:9": noul(0.02)}


def planned(answers, resolutions=None, brief=None, **kw):
    job = make_job("p", make_analysis(TEXT, **kw), brief=brief)
    decide(job, FakeAsker(answers))
    if resolutions is not None:
        job.write("resolutions.json", resolutions)
    out = plan(job)
    edit = EditFile.model_validate(job.read("edit.json"))
    kept = {i for s in edit.segments for i in range(s.first_word, s.last_word + 1)}
    return out, edit, kept


def test_plan_removes_the_auto_filler_and_a_filler_claude_cut(jobs_root):
    out, edit, kept = planned(ALL_NO, resolutions={"filler:9": True})
    assert 8 not in kept and 9 not in kept and 0 in kept
    assert validate_edit(edit) == []
    assert edit.captions.pages[0].start < 0.1 and out["next"] == "shorts preview p"
    assert edit.duration == pytest.approx(sum(s.out_frame - s.in_frame for s in edit.segments) / 30)


def test_a_false_start_claude_cut_removes_its_sentence(jobs_root):
    _, _, kept = planned(ALL_NO, resolutions={"false_start:s1": True})
    assert not kept & set(range(0, 8))


def test_resolutions_override_pending_items(jobs_root):
    answers = ALL_NO | {"false_start:s2": noul(0.5)}
    _, _, kept = planned(answers, resolutions={"false_start:s2": True})
    assert not kept & set(range(8, 13)) and 13 in kept


def test_unknown_resolution_ids_are_refused(jobs_root):
    with pytest.raises(ShortsError) as e:
        planned(ALL_NO, resolutions={"nope:1": True})
    assert e.value.code == "E_RESOLUTION"


def test_pauses_are_tightened_and_zoom_changes_at_the_cut(jobs_root):
    _, edit, _ = planned(ALL_NO, pauses_after={7: 0.8})
    assert len(edit.segments) >= 2
    assert edit.segments[0].zoom == 1.0 and edit.segments[1].zoom > 1.0 and edit.segments[1].crop is not None


def test_brief_cut_words_remove_a_restart_inside_a_sentence(jobs_root):
    _, _, kept = planned(ALL_NO, brief=Brief(cut_words=[(9, 11)]))      # "basically it is"
    assert not kept & {8, 9, 10, 11} and 12 in kept


def test_brief_cut_words_must_exist(jobs_root):
    with pytest.raises(ShortsError) as e:
        planned(ALL_NO, brief=Brief(cut_words=[(15, 40)]))
    assert e.value.code == "E_BRIEF_INVALID"
