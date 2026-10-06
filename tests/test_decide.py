import pytest
from typesafe_sdk import TypeSafeError

from shorts.decide.jev import JevAsker
from shorts.decide.questions import Spec
from shorts.decide.router import route
from shorts.decide.run import decide
from shorts.schemas import Decisions
from tests.factories import FakeAsker, choice, make_analysis, make_job, noul

TEXT = "So today I am testing a new app. Uh basically it is amazing. It edits videos by itself."


def spec(group, kind="noul", policy="destructive", default=False):
    return Spec(f"{group}:x", group, {}, kind, {}, policy, default)


def test_confident_answers_are_applied():
    assert route(spec("false_start"), noul(0.95)) == ("apply", True)
    assert route(spec("false_start"), noul(0.04)) == ("apply", False)


def test_uncertain_destructive_answer_goes_to_claude_with_the_safe_default():
    assert route(spec("filler_word"), noul(0.6)) == ("claude", False)


def test_missing_answers():
    assert route(spec("punch_in", policy="cosmetic"), None) == ("default", False)
    assert route(spec("false_start"), None) == ("claude", False)


def test_punch_in_uses_the_lower_bar():
    assert route(spec("punch_in", policy="cosmetic"), noul(0.75)) == ("apply", True)
    assert route(spec("punch_in", policy="cosmetic"), noul(0.5)) == ("apply", False)


def test_duplicate_take():
    dup = spec("duplicate_take", kind="choice", default="s4")
    assert route(dup, choice("s4", {"s3": 0.03, "s4": 0.97})) == ("apply", "s4")
    assert route(dup, choice("s3", {"s3": 0.65, "s4": 0.35})) == ("claude", "s3")
    assert route(dup, choice("s3", {"s3": 0.55, "s4": 0.45})) == ("claude", "s4")


def test_jev_only_picks_zoom_ins_and_claude_gets_the_cut_questions(jobs_root):
    job = make_job("d", make_analysis(TEXT))
    fake = FakeAsker({"punch_in:s1": noul(0.9), "punch_in:s2": noul(0.1)})
    out = decide(job, fake)
    d = Decisions.model_validate(job.read("decisions.json"))
    assert d.model == "fake-jev" and d.input_tokens == 1234 and d.auto_fillers == [8]
    by = {x.id: x for x in d.items}
    assert set(fake.questions) == {k for k in by if k.startswith("punch_in:")}         # Jev sees zoom-ins only
    assert by["punch_in:s1"].route == "apply" and by["punch_in:s1"].effective is True
    assert by["punch_in:s3"].route == "default"                                         # unanswered: no zoom
    assert by["false_start:s1"].route == "claude" and by["false_start:s1"].value is None
    assert "filler:0" in d.pending and not any(k.startswith("highlight") for k in by)
    assert out["asked_jev"] == 3 and all("jev_answer" not in p for p in out["pending"])


def test_decide_survives_a_jev_failure(jobs_root):
    class Broken:
        def ask(self, state, questions):
            raise TypeSafeError("no network")

    job = make_job("d", make_analysis(TEXT))
    out = decide(job, Broken())
    d = Decisions.model_validate(job.read("decisions.json"))
    assert "no network" in d.jev_error and out["jev_error"]
    assert all(x.route in ("claude", "default") for x in d.items)


@pytest.mark.live
def test_live_jev_answers_a_noul_and_a_choice():
    answers, meta = JevAsker().ask(
        {"message": "I was charged twice for my order. Please help."},
        {"billing": {"type": "noul", "instructions": "Is this about billing?"},
         "tone": {"type": "choice", "instructions": "What is the tone?", "criteria": {"calm": None, "upset": None}}})
    assert answers["billing"].value > 0.5 and answers["tone"].value in {"calm", "upset"}
    assert meta["model"] and meta["input_tokens"] > 0


def test_without_a_jev_key_claude_gets_the_zoom_ins_too(jobs_root, monkeypatch):
    """Jev is optional: no TYPESAFE_API_KEY -> no network call, and the zoom-in questions join Claude's pending list."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("Jev must not be called without a key")

    monkeypatch.setattr("shorts.decide.run.JevAsker", Boom)
    job = make_job("d", make_analysis(TEXT))
    out = decide(job)
    d = Decisions.model_validate(job.read("decisions.json"))
    zooms = [x for x in d.items if x.group == "punch_in"]
    assert zooms and all(x.route == "claude" for x in zooms) and d.jev_error is None
    assert out["asked_jev"] == 0 and out["jev"].startswith("off") and {z.id for z in zooms} <= set(d.pending)
