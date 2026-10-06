import pytest

from shorts.decide.questions import build, duplicate_groups, load_templates, sentence_notes
from shorts.errors import ShortsError
from shorts.schemas import Brief, TimeRange, VisualNote
from tests.factories import make_analysis

# Words: So(0) today(1) I(2) am(3) testing(4) a(5) new(6) app.(7) Uh(8) basically(9) it(10) is(11) amazing.(12)
#        It(13) edits(14) videos(15) by(16) itself.(17)
TEXT = "So today I am testing a new app. Uh basically it is amazing. It edits videos by itself."


def test_templates_load():
    tpl = load_templates()
    assert tpl["false_start"]["criteria"]["if_true"] and "highlight_word" not in tpl


def test_missing_template_is_an_error(tmp_path):
    (tmp_path / "x.yaml").write_text("punch_in:\n  instructions: hi\n")
    with pytest.raises(ShortsError) as e:
        load_templates(tmp_path)
    assert e.value.code == "E_QUESTIONS"


def test_build_asks_the_expected_questions():
    a = make_analysis(TEXT, pauses_after={7: 0.5})
    state, specs, auto = build(a, Brief(topic="app demo"), load_templates())
    got = {s.id for s in specs}
    assert {"false_start:s1", "false_start:s2"} <= got and "false_start:s3" not in got
    assert {"punch_in:s1", "punch_in:s2", "punch_in:s3"} <= got
    assert {"filler:0", "filler:9", "pause:7"} <= got and not any(g.startswith("highlight") for g in got)
    assert auto == [8]                                   # "Uh" is removed by rule, never asked
    assert state["topic"] == "app demo" and [s["id"] for s in state["sentences"]] == ["s1", "s2", "s3"]


def test_notes_reach_jev_as_sentence_ids_not_timecodes():
    a = make_analysis(TEXT)
    a.picture.no_face = [TimeRange(start=3.4, end=4.0)]
    notes = sentence_notes(a, Brief(visual_notes=[VisualNote(start=0.6, end=1.0, note="looks off camera")]))
    assert notes == ["s1: looks off camera", "s2: face not visible"]


def test_payloads_match_the_jev_wire_format():
    _, specs, _ = build(make_analysis(TEXT), Brief(), load_templates())
    by = {s.id: s for s in specs}
    fs = by["false_start:s1"].payload
    assert fs["type"] == "noul" and set(fs["criteria"]) == {"true", "false"}
    assert "So today I am testing a new app." in fs["instructions"]
    assert by["punch_in:s2"].policy == "cosmetic" and by["false_start:s1"].policy == "destructive"
    assert "[basically]" in by["filler:9"].payload["instructions"]


def test_duplicate_takes_grouped_and_default_is_the_last_take():
    a = make_analysis("So today I want to show you. So today I want to show you this app. Here it is.")
    assert duplicate_groups(a) == [["s1", "s2"]]
    _, specs, _ = build(a, Brief(), load_templates())
    dup = next(s for s in specs if s.group == "duplicate_take")
    assert dup.id == "dup:s1+s2" and dup.default == "s2" and set(dup.payload["criteria"]) == {"s1", "s2"}


def test_questions_read_the_caption_overrides():
    a = make_analysis("So today I am testing a new app. Uh basically it is amazing. It edits videos by itself.")
    _, specs, _ = build(a, Brief(caption_overrides={4: "try", 5: "kar", 6: "raha"}), load_templates())
    by = {s.id: s for s in specs}
    assert "So today I am try kar raha app." in by["false_start:s1"].payload["instructions"]
