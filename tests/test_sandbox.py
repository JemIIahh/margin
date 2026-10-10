import subprocess
import sys

import pytest

from margin.sandbox import EditError, PathEscape, Sandbox, SuiteTimeout


def test_read_file_numbers_lines_and_honours_ranges(sandbox):
    assert sandbox.read_file("pkg/mathy.py").splitlines()[0] == "1\tdef add(a, b):"
    assert sandbox.read_file("pkg/mathy.py", start_line=2, end_line=2) == "2\t    return a - b"


@pytest.mark.parametrize("bad", ["../outside.txt", "/etc/passwd", ".git/config", "pkg/../../x", ""])
def test_paths_outside_or_in_git_are_rejected(sandbox, bad):
    with pytest.raises(PathEscape):
        sandbox.resolve(bad)


def test_symlink_escape_is_rejected(sandbox, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    (sandbox.root / "link").symlink_to(outside)
    with pytest.raises(PathEscape):
        sandbox.resolve("link")


def test_edit_requires_exactly_one_match(sandbox):
    sandbox.edit_file("pkg/mathy.py", "a - b", "a + b")
    assert "a + b" in sandbox.read_file("pkg/mathy.py")
    with pytest.raises(EditError, match="not found"):
        sandbox.edit_file("pkg/mathy.py", "zzz", "q")
    sandbox.write_file("dup.txt", "x\nx\n")
    with pytest.raises(EditError, match="2 places"):
        sandbox.edit_file("dup.txt", "x", "y")
    with pytest.raises(EditError, match="empty"):
        sandbox.edit_file("dup.txt", "", "y")


def test_write_file_creates_parent_directories(sandbox):
    sandbox.write_file("pkg/sub/new.py", "X = 1\n")
    assert (sandbox.root / "pkg" / "sub" / "new.py").read_text() == "X = 1\n"


def test_git_diff_includes_new_and_changed_files(sandbox):
    sandbox.edit_file("pkg/mathy.py", "a - b", "a + b")
    sandbox.write_file("pkg/new.py", "X = 1\n")
    diff = sandbox.git_diff()
    assert "-    return a - b" in diff and "+    return a + b" in diff
    assert "pkg/new.py" in diff


def test_restore_paths_resets_protected_files(sandbox):
    sandbox.write_file("tests/test_mathy.py", "broken")
    sandbox.restore_paths(["tests/test_mathy.py"])
    assert "def test_add" in sandbox.read_file("tests/test_mathy.py")


def test_scrubbed_env_contains_no_secrets(sandbox, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("NEATLOGS_API_KEY", "nl-secret")
    env = sandbox.scrubbed_env()
    assert "ANTHROPIC_API_KEY" not in env and "NEATLOGS_API_KEY" not in env
    out = subprocess.run(
        [sys.executable, "-c", "import os; print(sorted(k for k in os.environ if 'KEY' in k))"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert out.stdout.strip() == "[]"


def test_run_pytest_writes_junit_and_reports_failure(sandbox, tmp_path):
    junit = tmp_path / "j.xml"
    proc = sandbox.run_pytest(["tests"], junit)
    assert junit.exists()
    assert proc.returncode == 1  # test_add fails on the buggy base


def test_run_pytest_times_out(sandbox, tmp_path):
    sandbox.write_file("tests/test_slow.py", "import time\n\n\ndef test_slow():\n    time.sleep(5)\n")
    with pytest.raises(SuiteTimeout):
        sandbox.run_pytest(["tests/test_slow.py"], tmp_path / "j.xml", timeout_s=1)


def test_exclude_keeps_artifacts_out_of_the_diff(sandbox):
    sandbox.exclude([".entire/"])
    sandbox.write_file(".entire/cache", "1")
    assert ".entire" not in sandbox.git_diff()


def test_sandbox_root_is_resolved(repo, tmp_path):
    sb = Sandbox(repo / ".." / "repo", sys.executable, ["."], tmp_path / "h")
    assert sb.root == repo.resolve()
