import pytest

from shorts.errors import ShortsError
from shorts.job import Job


def test_create_write_read_roundtrip(tmp_path):
    job = Job.create("demo", root=tmp_path)
    job.write("a.json", {"x": 1})
    assert job.read("a.json") == {"x": 1}
    assert (tmp_path / "demo").is_dir() and job.work.is_dir()


def test_invalid_name_rejected(tmp_path):
    with pytest.raises(ShortsError) as e:
        Job("Bad Name", root=tmp_path)
    assert e.value.code == "E_JOB_NAME"


def test_open_missing_job(tmp_path):
    with pytest.raises(ShortsError) as e:
        Job.open("nope", root=tmp_path)
    assert e.value.code == "E_NO_JOB"


def test_read_missing_file(tmp_path):
    job = Job.create("demo", root=tmp_path)
    with pytest.raises(ShortsError) as e:
        job.read("analysis.json")
    assert e.value.code == "E_MISSING_FILE"


def test_timed_records_step(tmp_path):
    job = Job.create("demo", root=tmp_path)
    with job.timed("probe"):
        pass
    assert "probe" in job.read("timings.json")


def test_status_reports_next_step(tmp_path):
    job = Job.create("demo", root=tmp_path)
    job.write("probe.json", {})
    st = job.status()
    assert st["done"]["probe"] is True
    assert st["next"] == "analyze"
