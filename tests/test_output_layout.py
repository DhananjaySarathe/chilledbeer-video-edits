import importlib.util
from pathlib import Path

import pytest

from shorts import cli, config
from shorts.clean import clean
from shorts.errors import ShortsError
from shorts.job import Job


def test_a_new_take_splits_kept_temp_and_final(output_root):
    job = Job.create("take1")
    assert job.dir == output_root / "jobs" / "take1"
    assert job.work == output_root / "temp" / "jobs" / "take1"
    assert job.final == output_root / "final" / "take1" / "final.mp4"
    assert job.source == job.dir / "source.mp4"           # footage is kept: deleting temp never loses it
    assert job.preview.parent == job.work


def test_an_old_take_keeps_its_one_folder_layout(output_root):
    old = config.LEGACY_JOBS / "ew1"
    (old / "work").mkdir(parents=True)
    job = Job.open("ew1")
    assert job.legacy and job.dir == old and job.work == old / "work"
    assert job.source == old / "work" / "source.mp4" and job.final == old / "final.mp4"


def test_open_recreates_a_deleted_temp_folder(output_root):
    job = Job.create("take1")
    job.work.rmdir()
    assert Job.open("take1").work.is_dir()


def _fill(output_root):
    for rel in ["jobs/a/analysis.json", "final/a/final.mp4", "temp/jobs/a/audio16k.wav", "temp/jobs/b/x.wav",
                "temp/films/f/work/aroll.mp4", "temp/cache/graphics/x.mp4"]:
        p = output_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 1000)


def test_clean_deletes_only_temp(output_root):
    _fill(output_root)
    out = clean([])
    assert not any((output_root / "temp").iterdir())
    assert (output_root / "jobs/a/analysis.json").exists() and (output_root / "final/a/final.mp4").exists()
    assert {r["path"] for r in out["deleted"]} == {"output/temp/cache", "output/temp/films", "output/temp/jobs"}


def test_clean_one_take_or_film_and_dry_run(output_root):
    _fill(output_root)
    assert clean(["a"], dry_run=True)["would_delete"][0]["path"] == "output/temp/jobs/a"
    assert (output_root / "temp/jobs/a").exists()
    clean(["a", "f"])
    assert not (output_root / "temp/jobs/a").exists() and not (output_root / "temp/films/f").exists()
    assert (output_root / "temp/jobs/b").exists()


def test_clean_never_leaves_temp(output_root):
    _fill(output_root)
    with pytest.raises(ShortsError) as e:
        clean(["../jobs"])
    assert e.value.code == "E_NOT_TEMP" and (output_root / "jobs/a/analysis.json").exists()
    with pytest.raises(ShortsError):
        clean(["nope"])


def test_clean_via_cli(output_root, capsys):
    _fill(output_root)
    assert cli.main(["clean", "--dry-run"]) == 0 and "would_delete" in capsys.readouterr().out


def test_kit_paths_and_shorts_config_agree():
    """Films use kit/paths.py, the CLI uses shorts/config.py: both must describe the same folders."""
    import kit.paths as kp

    spec = importlib.util.spec_from_file_location("fresh_config", config.__file__)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)                        # the real values (the autouse fixture patches `config`)
    for name in ("OUTPUT", "JOBS", "TEMP", "FINAL", "CACHE", "LEGACY_JOBS"):
        assert getattr(kp, name) == getattr(fresh, name), name


def test_film_names_and_reel_delivers_with_its_film():
    import kit.paths as kp

    assert kp.film_name(kp.FILMS / "demo/build.py") == "demo"
    assert kp.film_name(kp.FILMS / "demo/reel/build_reel.py") == "demo-reel"
    assert kp._film_parts(kp.FILMS / "demo/reel")[0] == "demo"
    assert kp.film_name(kp.ROOT / "kit/hf/showcase/build.py") == "kit-hf-showcase"
    assert isinstance(kp.film_name(Path("films/demo")), str)
