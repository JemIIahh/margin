import sys
from pathlib import Path

import pytest

from conftest import git
from margin.bench.tasks import Task, find_task, load_tasks, prepare_run
from margin.config import Settings


def make_source_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A repo whose fix commit repairs pkg/mathy.py and adds the failing test."""
    src = tmp_path / "src_repo"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "__init__.py").write_text("")
    (src / "pkg" / "mathy.py").write_text("def add(a, b):\n    return a - b\n")
    git(src, "init", "-q", "-b", "main")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "base")
    base = git(src, "rev-parse", "HEAD")
    (src / "pkg" / "mathy.py").write_text("def add(a, b):\n    return a + b\n")
    (src / "tests").mkdir()
    (src / "tests" / "test_mathy.py").write_text(
        "from pkg.mathy import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "fix add")
    return src, base, git(src, "rev-parse", "HEAD")


def make_task(tmp_path: Path) -> Task:
    src, base, fix = make_source_repo(tmp_path)
    issue = tmp_path / "issue.md"
    issue.write_text("add(1, 2) returns -1")
    return Task(
        id="t-add", split="calibration", repo=str(src), base_commit=base, fix_commit=fix, issue_url="local",
        issue_file=str(issue), target_tests=["tests/test_mathy.py::test_add"], test_files=["tests/test_mathy.py"],
    )


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        root=tmp_path, runs_dir=tmp_path / "runs", ledger_path=tmp_path / "runs" / "ledger.jsonl",
        cache_dir=tmp_path / "cache",
    )


def test_load_tasks_and_find(tmp_path):
    manifest = tmp_path / "tasks.toml"
    manifest.write_text(
        '[[task]]\nid = "x"\nsplit = "evaluation"\nrepo = "r"\nbase_commit = "b"\nfix_commit = "f"\n'
        'issue_url = "u"\nissue_file = "i.md"\ntarget_tests = ["tests/t.py::test_a"]\ntest_files = ["tests/t.py"]\n'
    )
    tasks = load_tasks(manifest)
    assert tasks[0].test_args == ["tests"] and tasks[0].pythonpath == ["."]
    assert tasks[0].target_junit_ids == ["tests.t::test_a"]
    assert find_task(tasks, "x") is tasks[0]
    with pytest.raises(KeyError):
        find_task(tasks, "nope")


def test_prepare_run_builds_a_worktree_with_the_test_patch_and_baseline(tmp_path):
    task = make_task(tmp_path)
    prep = prepare_run(task, tmp_path / "run1", settings_for(tmp_path), venv_python=Path(sys.executable))
    sb = prep.sandbox
    assert "def test_add" in sb.read_file("tests/test_mathy.py")          # visible failing test
    assert "return a - b" in sb.read_file("pkg/mathy.py")                 # still the buggy base
    assert prep.baseline.failing == frozenset({"tests.test_mathy::test_add"})
    assert sb.git_diff() == ""                                            # test patch is committed, diff is empty
    assert prep.baseline_seconds > 0
    again = prepare_run(task, tmp_path / "run2", settings_for(tmp_path), venv_python=Path(sys.executable))
    assert again.baseline == prep.baseline                                # served from the baseline cache
    assert (tmp_path / "cache" / "baselines" / "t-add.json").exists()


def test_prepare_run_rejects_a_fix_commit_without_test_changes(tmp_path):
    task = make_task(tmp_path)
    bad = Task(**{**task.__dict__, "test_files": ["pkg/__init__.py"]})
    with pytest.raises(ValueError, match="changes none of test_files"):
        prepare_run(bad, tmp_path / "run3", settings_for(tmp_path), venv_python=Path(sys.executable))


def test_setup_commands_run_without_api_keys(monkeypatch):
    from margin.bench.tasks import _run

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("NEATLOGS_API_KEY", "nl-secret")
    env = dict(line.split("=", 1) for line in _run(["env"]).stdout.splitlines() if "=" in line)
    assert "ANTHROPIC_API_KEY" not in env and "NEATLOGS_API_KEY" not in env
    assert env["PATH"] and env["HOME"]
