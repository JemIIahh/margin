import pytest

from fakes import FakeGraph
from margin.agent.tools import ARM_TOOLS, ToolExecutor, tool_schemas
from margin.verify import make_baseline, run_suite

TARGET_NODEID = "tests/test_mathy.py::test_add"
TARGET_JUNIT = "tests.test_mathy::test_add"


def make_executor(sandbox, tmp_path, arm="B", graph=None, **extra):
    base = make_baseline(
        run_suite(sandbox, ["tests"], tmp_path / "b1.xml"), run_suite(sandbox, ["tests"], tmp_path / "b2.xml")
    )
    return ToolExecutor(
        sandbox=sandbox, arm=arm, baseline=base, target_nodeids=[TARGET_NODEID],
        target_junit_ids=[TARGET_JUNIT], test_args=["tests"], protected_paths=["tests/test_mathy.py"],
        issue_text="add subtracts", graph=graph, **extra,
    )


def test_tool_schemas_per_arm():
    assert [t["name"] for t in tool_schemas("A")] == ARM_TOOLS["A"]
    assert "graph_impact" in ARM_TOOLS["B"] and "graph_impact" in ARM_TOOLS["C"]
    assert "graph_impact" not in ARM_TOOLS["A"]
    for tool in tool_schemas("B"):
        assert tool["input_schema"]["additionalProperties"] is False


def test_read_edit_and_run_tests_flow(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path)
    assert "return a - b" in ex.execute("read_file", {"path": "pkg/mathy.py"}).text
    first = ex.execute("run_tests", {})
    assert "Target tests: 1 failing of 1" in first.text
    assert not first.is_error
    assert ex.execute("edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"}).text == "edited pkg/mathy.py"
    second = ex.execute("run_tests", {})
    assert "Target tests: 0 failing of 1" in second.text
    assert "New failures vs baseline: none" in second.text
    assert ex.progress.events >= 2  # first edit + target failures dropped


def test_run_tests_shows_why_a_target_test_fails_without_the_worktree_path(sandbox, tmp_path):
    out = make_executor(sandbox, tmp_path).execute("run_tests", {})
    assert "FAIL tests.test_mathy::test_add" in out.text
    assert "assert -1 == 3" in out.text
    assert str(sandbox.root) not in out.text


def test_arm_a_runs_only_the_target_tests(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path, arm="A")
    out = ex.execute("run_tests", {})
    assert "Target tests" in out.text and "New failures" not in out.text


def test_protected_test_files_cannot_be_edited(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path)
    out = ex.execute("edit_file", {"path": "tests/test_mathy.py", "old": "assert", "new": "pass"})
    assert out.is_error and "protected" in out.text
    out = ex.execute("write_file", {"path": "./tests/test_mathy.py", "content": ""})
    assert out.is_error and "protected" in out.text


@pytest.mark.parametrize("path", ["../x.py", "/etc/passwd", ".git/config"])
def test_paths_outside_the_worktree_are_errors_not_crashes(sandbox, tmp_path, path):
    out = make_executor(sandbox, tmp_path).execute("read_file", {"path": path})
    assert out.is_error


def test_bad_tool_calls_become_error_results(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path)
    assert ex.execute("nope", {}).is_error
    assert ex.execute("read_file", {}).is_error                      # missing argument
    assert ex.execute("read_file", {"path": "x", "bogus": 1}).is_error  # unexpected argument
    assert ex.execute("read_file", {"path": "pkg/mathy.py", "start_line": "a"}).is_error  # wrong type
    assert ex.execute("read_file", "not-a-dict").is_error
    assert ex.execute("edit_file", {"path": "pkg/mathy.py", "old": "zzz", "new": "q"}).is_error


def test_search_uses_the_graph_only_when_one_is_attached(sandbox, tmp_path):
    assert "pkg/mathy.py" in make_executor(sandbox, tmp_path, arm="A").execute("search_code", {"query": "add"}).text
    ex = make_executor(sandbox, tmp_path, arm="B", graph=FakeGraph())
    assert ex.execute("search_code", {"query": "add"}).text == "GRAPH-SEARCH:add"
    assert ex.execute("graph_impact", {"symbol": "add"}).text == "GRAPH-IMPACT:add"
    assert make_executor(sandbox, tmp_path, arm="A").execute("graph_impact", {"symbol": "add"}).is_error


def test_git_diff_and_digest(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path)
    assert ex.execute("git_diff", {}).text == "(no changes)"
    ex.execute("edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})
    ex.execute("run_tests", {})
    digest = ex.digest()
    assert "+    return a + b" in digest["diff"]
    assert "Target tests: 0 failing" in digest["tests"]


def test_long_output_is_clipped(sandbox, tmp_path):
    sandbox.write_file("big.txt", "x" * 50_000)
    out = make_executor(sandbox, tmp_path).execute("read_file", {"path": "big.txt"})
    assert len(out.text) < 13_000


@pytest.mark.parametrize(
    "path", ["tests/conftest.py", "tests/test_new.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml",
             "sitecustomize.py", "pkg/extra.pth", "TESTS/new.py", "Conftest.PY"],
)
def test_test_files_and_test_infrastructure_are_read_only(sandbox, tmp_path, path):
    ex = make_executor(sandbox, tmp_path)
    out = ex.execute("write_file", {"path": path, "content": "x"})
    assert out.is_error and "protected" in out.text
    assert not (sandbox.root / path).exists()


def test_run_tests_reports_a_test_that_passed_at_baseline_and_has_gone_missing(sandbox, tmp_path):
    from margin.verify import Baseline

    ex = make_executor(sandbox, tmp_path)
    ex.baseline = Baseline(ex.baseline.failing, ex.baseline.flaky, passing=frozenset({"tests.test_mathy::test_ghost"}))
    out = ex.execute("run_tests", {})
    assert "FAIL tests.test_mathy::test_ghost" in out.text      # a missing test is a regression, not a pass


def test_the_timeout_fallback_does_not_flag_every_untested_test_as_missing(sandbox, tmp_path):
    from margin.faults import FaultInjector
    from margin.verify import Baseline

    ex = make_executor(sandbox, tmp_path, faults=FaultInjector("tool_timeout"))
    ex.baseline = Baseline(ex.baseline.failing, ex.baseline.flaky, passing=frozenset({"tests.test_mathy::test_other"}))
    out = ex.execute("run_tests", {})                          # falls back to the target tests only
    assert "test_other" not in out.text and "Target tests: 1 failing of 1" in out.text


def test_progress_is_measured_against_all_targets_failing_and_green_runs_keep_counting():
    from margin.agent.tools import ProgressTracker

    t = ProgressTracker(initial_failing=2)       # validation guarantees every target fails at the base commit
    t.note_tests(2)
    assert t.events == 0                          # nothing improved
    t.note_tests(1)
    assert t.events == 1
    t.note_tests(0)
    assert t.events == 2
    t.note_tests(0)
    assert t.events == 3                          # still green: a finished fix is not "no progress"
    legacy = ProgressTracker()                    # without the target count the first run is a baseline
    legacy.note_tests(1)
    assert legacy.events == 0


def test_a_first_run_that_already_passes_counts_as_progress(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path)
    ex.execute("edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})
    before = ex.progress.events
    ex.execute("run_tests", {})
    assert ex.progress.events == before + 1


def test_read_file_keeps_its_hint_to_use_line_ranges_after_clipping(sandbox, tmp_path):
    sandbox.write_file("big.txt", "line of text\n" * 6000)
    out = make_executor(sandbox, tmp_path).execute("read_file", {"path": "big.txt"})
    assert "start_line" in out.text and "[output truncated]" not in out.text


def test_a_failing_git_command_becomes_an_error_result_not_a_crash(sandbox, tmp_path, monkeypatch):
    import subprocess

    ex = make_executor(sandbox, tmp_path)

    def broken():
        raise subprocess.CalledProcessError(128, ["git", "add"], stderr="fatal: unable to read tree")

    monkeypatch.setattr(sandbox, "git_diff", broken)
    out = ex.execute("git_diff", {})
    assert out.is_error and "git" in out.text


def test_a_case_variant_of_a_protected_file_is_refused_and_leaves_it_unchanged(sandbox, tmp_path):
    """macOS is case-insensitive: tests/TEST_MATHY.py is the same file as tests/test_mathy.py."""
    ex = make_executor(sandbox, tmp_path)
    before = (sandbox.root / "tests" / "test_mathy.py").read_text()
    out = ex.execute("edit_file", {"path": "tests/TEST_MATHY.py", "old": "== 3", "new": "== -1"})
    assert out.is_error and "protected" in out.text
    assert (sandbox.root / "tests" / "test_mathy.py").read_text() == before


def test_a_tool_error_never_shows_the_absolute_worktree_path(sandbox, tmp_path):
    """Seen live: reading a directory returned IsADirectoryError with '/Users/<name>/.../work/...' in the model's context."""
    out = make_executor(sandbox, tmp_path).execute("read_file", {"path": "pkg"})
    assert out.is_error and str(sandbox.root) not in out.text
    assert "directory" in out.text.lower() and "pkg" in out.text


def test_wrong_arguments_get_a_clear_message_without_python_internals(sandbox, tmp_path):
    """Seen live: the model sent an extra argument to edit_file and read 'ToolExecutor._tool_edit_file() got an unexpected keyword'."""
    ex = make_executor(sandbox, tmp_path)
    extra = ex.execute("edit_file", {"path": "pkg/mathy.py", "old": "a", "new": "b", "replace_all": True})
    assert extra.is_error and "unexpected" in extra.text and "replace_all" in extra.text
    assert "ToolExecutor" not in extra.text and "_tool_" not in extra.text
    assert "path, old, new" in extra.text                          # it says what the tool does take
    missing = ex.execute("edit_file", {"path": "pkg/mathy.py"})
    assert missing.is_error and "missing" in missing.text and "old" in missing.text and "new" in missing.text
    wrong = ex.execute("read_file", {"path": "pkg/mathy.py", "start_line": "a"})
    assert wrong.is_error and "start_line" in wrong.text and "integer" in wrong.text
    bool_as_int = ex.execute("read_file", {"path": "pkg/mathy.py", "start_line": True})
    assert bool_as_int.is_error                                     # True is an int in Python, not a line number
