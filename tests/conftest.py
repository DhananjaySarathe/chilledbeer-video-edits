import pytest

from shorts import config


@pytest.fixture(autouse=True)
def output_root(tmp_path, monkeypatch):
    """Every test gets its own output/ (jobs, temp, final, cache) and legacy jobs/ folder: the real ones are never touched."""
    out = tmp_path / "output"
    for name, path in {"OUTPUT": out, "JOBS": out / "jobs", "TEMP": out / "temp", "FINAL": out / "final",
                       "CACHE": out / "temp" / "cache", "LEGACY_JOBS": tmp_path / "legacy_jobs"}.items():
        monkeypatch.setattr(config, name, path)
    return out


@pytest.fixture
def jobs_root(output_root):
    return config.JOBS


@pytest.fixture(scope="session")
def truth_speech(tmp_path_factory):
    """Speech with known word times, generated once per test run (27 `say` calls take a few seconds)."""
    from tests.media import make_truth_speech

    return make_truth_speech(tmp_path_factory.mktemp("truth"))
