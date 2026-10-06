import sys

import pytest

from shorts.errors import ShortsError
from shorts.proc import run


def test_run_success():
    assert run([sys.executable, "-c", "print('ok')"], code="E_X", what="py").stdout.strip() == "ok"


def test_run_failure_raises_with_code_and_log(tmp_path):
    log = tmp_path / "l.log"
    with pytest.raises(ShortsError) as e:
        run([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
            code="E_X", what="py", log=log)
    assert e.value.code == "E_X"
    assert "boom" in e.value.message
    assert log.exists()
