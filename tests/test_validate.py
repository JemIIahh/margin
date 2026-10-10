import sys
from pathlib import Path

from margin.bench.tasks import Task, validate_task
from test_tasks import make_task, settings_for


def test_validate_accepts_a_good_task(tmp_path):
    result = validate_task(make_task(tmp_path), settings_for(tmp_path), venv_python=Path(sys.executable))
    assert result["ok"], result["problems"]
    assert result["source_files"] == ["pkg/mathy.py"]
    assert result["target_failing_before"] == 1


def test_validate_flags_a_target_that_never_failed(tmp_path):
    task = make_task(tmp_path)
    bad = Task(**{**task.__dict__, "target_tests": ["tests/test_mathy.py::test_nonexistent"]})
    result = validate_task(bad, settings_for(tmp_path), venv_python=Path(sys.executable))
    assert not result["ok"]
    assert any("do not fail before the fix" in p for p in result["problems"])


def test_validate_flags_slow_suites(tmp_path):
    result = validate_task(
        make_task(tmp_path), settings_for(tmp_path), venv_python=Path(sys.executable), max_seconds=0.0001
    )
    assert not result["ok"] and any("seconds" in p for p in result["problems"])
