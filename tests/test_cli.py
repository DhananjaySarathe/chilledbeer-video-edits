from shorts import cli


def test_status_unknown_job_is_a_json_error(capsys, jobs_root):
    assert cli.main(["status", "does-not-exist"]) == 2
    assert "E_NO_JOB" in capsys.readouterr().err


def test_status_existing_job(capsys, jobs_root):
    (jobs_root / "demo").mkdir(parents=True)
    assert cli.main(["status", "demo"]) == 0
    assert '"next": "probe"' in capsys.readouterr().out
