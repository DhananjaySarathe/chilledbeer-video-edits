import pytest
from pydantic import ValidationError

from shorts import cli
from shorts.brief import init_brief, load_brief, load_style
from shorts.errors import ShortsError
from shorts.job import Job
from shorts.schemas import Brief, Style


def test_defaults_are_valid():
    assert Brief().target.max == 60.0
    assert Style().caption_template == "bold_pop"


def test_bad_color_rejected():
    with pytest.raises(ValidationError):
        Style(text_color="white")


def test_words_per_page_bounds():
    with pytest.raises(ValidationError):
        Style(words_per_page=4)


def test_caption_override_keys_become_ints():
    assert Brief.model_validate({"caption_overrides": {"12": "yeh"}}).caption_overrides == {12: "yeh"}


def test_cut_words_are_inclusive_ranges():
    assert Brief.model_validate({"cut_words": [[156, 160]]}).cut_words == [(156, 160)]


def test_init_brief_writes_once(jobs_root):
    Job.create("demo")
    out = init_brief("demo")
    assert set(out["written"]) == {"brief.json", "style.json"}
    assert init_brief("demo")["written"] == []
    assert load_brief(Job.open("demo")).topic == ""


def test_load_style_rejects_missing_font(jobs_root):
    job = Job.create("demo")
    job.write("style.json", Style(font="Nope.ttf").model_dump())
    with pytest.raises(ShortsError) as e:
        load_style(job)
    assert e.value.code == "E_FONT"


def test_invalid_brief_is_a_clear_error(jobs_root):
    job = Job.create("demo")
    job.write("brief.json", {"target": {"min": "soon"}})
    with pytest.raises(ShortsError) as e:
        load_brief(job)
    assert e.value.code == "E_BRIEF_INVALID"


def test_schema_command(capsys):
    assert cli.main(["schema", "style"]) == 0
    assert '"caption_template"' in capsys.readouterr().out
