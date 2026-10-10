import subprocess
import sys
from pathlib import Path

import pytest

from conftest import git
from margin.sandbox import EditError, GitTampered, PathEscape, Sandbox, SuiteTimeout


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


# --- host-side git hardening (security review findings 1 and 2) ----------------------------
def worktree_sandbox(repo, tmp_path):
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "--detach", "-q", str(wt))
    return Sandbox(wt, Path(sys.executable), ["."], tmp_path / "wthome")


def evil_hook(tmp_path):
    marker = tmp_path / "PWNED"
    hook = tmp_path / "hook.sh"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nprintf '\\0'\n")
    hook.chmod(0o755)
    return marker, hook


@pytest.mark.parametrize("bad", [".GIT", ".Git/config", ".git ", "pkg/../.GIT", ".git."])
def test_git_paths_are_rejected_whatever_their_case(sandbox, bad):
    with pytest.raises(PathEscape):
        sandbox.resolve(bad)


@pytest.mark.parametrize("name", [".gitattributes", ".gitmodules", "pkg/.gitignore"])
def test_git_metadata_files_are_read_only_for_the_agent(sandbox, name):
    with pytest.raises(PathEscape):
        sandbox.write_file(name, "x")
    with pytest.raises(PathEscape):
        sandbox.edit_file(name, "a", "b")


def test_a_worktree_git_pointer_cannot_be_rewritten_through_the_file_tools(repo, tmp_path):
    sb = worktree_sandbox(repo, tmp_path)
    before = (sb.root / ".git").read_text()
    with pytest.raises(PathEscape):
        sb.write_file(".GIT", "gitdir: /tmp/evil\n")
    assert (sb.root / ".git").read_text() == before


def test_a_rewritten_git_pointer_is_detected_and_never_trusted(repo, tmp_path):
    sb = worktree_sandbox(repo, tmp_path)
    marker, hook = evil_hook(tmp_path)
    evil = tmp_path / "evil"
    evil.mkdir()
    git(evil, "init", "-q")
    git(evil, "config", "core.fsmonitor", str(hook))
    (sb.root / ".git").write_text(f"gitdir: {evil}/.git\n")  # what test code could do, bypassing the tools
    with pytest.raises(GitTampered):
        sb.git_diff()
    assert not marker.exists()


def test_config_injected_into_the_shared_git_dir_is_detected(repo, tmp_path):
    sb = worktree_sandbox(repo, tmp_path)
    marker, hook = evil_hook(tmp_path)
    config = sb.common_dir / "config"
    config.write_text(config.read_text() + f"\n[core]\n\tfsmonitor = {hook}\n")
    with pytest.raises(GitTampered):
        sb.git_diff()
    assert not marker.exists()


def test_a_planted_hook_is_detected(repo, tmp_path):
    sb = worktree_sandbox(repo, tmp_path)
    marker, _hook = evil_hook(tmp_path)
    (sb.common_dir / "hooks").mkdir(exist_ok=True)
    planted = sb.common_dir / "hooks" / "post-checkout"
    planted.write_text(f"#!/bin/sh\ntouch {marker}\n")
    planted.chmod(0o755)
    with pytest.raises(GitTampered):
        sb.restore_paths(["pkg/mathy.py"])
    assert not marker.exists()


def test_host_git_runs_in_a_scrubbed_environment(sandbox, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    env = sandbox._git_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null" and env["GIT_CONFIG_NOSYSTEM"] == "1"


def test_normal_git_operations_work_in_a_worktree(repo, tmp_path):
    sb = worktree_sandbox(repo, tmp_path)
    sb.edit_file("pkg/mathy.py", "a - b", "a + b")
    assert "+    return a + b" in sb.git_diff()
    sb.exclude([".entire/"])
    sb.write_file(".entire/cache", "1")
    assert ".entire" not in sb.git_diff()
