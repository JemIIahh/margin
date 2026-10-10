import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from fakes import ScriptedClient, reply, text, tool_use
from margin.ledger import Ledger
from margin.run import execute_run
from test_tasks import make_task, settings_for


def test_execute_run_arm_a_solves_the_fixture_task(tmp_path):
    task = make_task(tmp_path)
    settings = settings_for(tmp_path)
    client = ScriptedClient(
        [
            reply([tool_use("t1", "edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})], stop="tool_use"),
            reply([tool_use("t2", "run_tests", {})], stop="tool_use"),
            reply([text("fixed add")]),
        ]
    )
    rec = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=client, run_id="r-a", venv_python=Path(sys.executable)
    )
    assert rec.solved and rec.arm == "A" and rec.task_id == "t-add"
    assert rec.cost_usd > 0 and rec.price_usd == 0.0     # flat price is applied at report time
    assert rec.margin_usd == -rec.cost_usd
    rows = Ledger(settings.ledger_path).rows()
    assert [r.run_id for r in rows] == ["r-a"]
    receipt = (settings.runs_dir / "r-a" / "receipt.md").read_text()
    assert "arm A" in receipt and "verified" in receipt


def test_a_failing_run_is_recorded_not_raised(tmp_path):
    task = make_task(tmp_path)
    settings = settings_for(tmp_path)
    client = ScriptedClient([reply([text("I give up")])])
    rec = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=client, run_id="r-fail", venv_python=Path(sys.executable)
    )
    assert not rec.solved
    assert "target tests still failing" in rec.verdict_reason


def test_cheating_by_editing_the_test_is_undone_before_judging(tmp_path):
    task = make_task(tmp_path)
    settings = settings_for(tmp_path)
    client = ScriptedClient(
        [
            reply([tool_use("t1", "edit_file", {"path": "tests/test_mathy.py", "old": "== 3", "new": "== -1"})], stop="tool_use"),
            reply([text("done")]),
        ]
    )
    rec = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=client, run_id="r-cheat", venv_python=Path(sys.executable)
    )
    assert not rec.solved


def test_tampering_ends_the_run_as_unsolved_without_crashing(tmp_path, monkeypatch):
    from margin.sandbox import GitTampered, Sandbox

    def tampered(self):
        raise GitTampered("config changed")

    monkeypatch.setattr(Sandbox, "git_diff", tampered)
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    client = ScriptedClient([reply([tool_use("t1", "git_diff", {})], stop="tool_use")])
    result = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=client, run_id="r-tamper", venv_python=Path(sys.executable)
    )
    assert not result.solved
    assert "tampering" in result.verdict_reason and "tampering" in result.abort_reason


def test_run_ids_do_not_collide_within_one_second():
    from margin.run import new_run_id

    ids = {new_run_id("t", "A") for _ in range(50)}
    assert len(ids) == 50


def test_a_failing_graph_falls_back_to_plain_context_and_is_logged(tmp_path):
    from margin.config import Settings
    from margin.context import GraphError
    from margin.run import _initial_context
    from margin.state import RunState

    class Broken:
        def search(self, query):
            raise GraphError("index unavailable")

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n")
    state = RunState(tmp_path / "run")
    context = _initial_context(Broken(), "an issue", tmp_path, Settings(), state)
    assert "### pkg/mod.py" in context                       # plain whole-file context, not an empty prompt
    assert state.events("graph_error")[0]["error"] == "index unavailable"


@pytest.mark.skipif(shutil.which("entire") is None, reason="entire CLI is not installed")
def test_arm_b_end_to_end_with_the_real_entire_graph(tmp_path):
    """Everything but the model is real: the bare clone, the worktree, the entire graph binary, the verifier."""
    task = make_task(tmp_path)
    settings = settings_for(tmp_path)
    client = ScriptedClient(
        [
            reply([tool_use("t1", "edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})], stop="tool_use"),
            reply([tool_use("t2", "run_tests", {})], stop="tool_use"),
            reply([text("fixed add")]),
        ]
    )
    rec = execute_run(
        task, "B", settings, tasks_root=tmp_path, client=client, run_id="r-b", venv_python=Path(sys.executable)
    )
    assert rec.solved and rec.arm == "B"
    assert set(rec.features) == {"issue_tokens", "impact_files", "repo_loc", "baseline_seconds"}
    first_prompt = client.calls[0]["messages"][0]["content"]
    assert "Repository context" in first_prompt
    work = settings.runs_dir / "r-b" / "work"
    status = subprocess.run(
        ["git", "-C", str(work), "status", "--short"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert [line[3:] for line in status] == ["pkg/mathy.py"]  # only the fix; the graph left no artifacts behind


CHEAT_CONFTEST = (
    "import pytest\n\n\n@pytest.hookimpl(hookwrapper=True)\ndef pytest_runtest_makereport(item, call):\n"
    "    outcome = yield\n    outcome.get_result().outcome = 'passed'\n"
)


def test_a_conftest_that_turns_every_failure_into_a_pass_cannot_make_a_run_solved(tmp_path):
    """The agent never fixes the bug. A cheating conftest appears (written around the tools). Judging ignores it."""
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    work = settings.runs_dir / "r-cheat2" / "work"

    def plant(turn):
        (work / "tests" / "conftest.py").write_text(CHEAT_CONFTEST)

    client = ScriptedClient(
        [reply([tool_use("t1", "read_file", {"path": "pkg/mathy.py"})], stop="tool_use"), reply([text("fixed")])]
    )
    rec = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=client, run_id="r-cheat2",
        venv_python=Path(sys.executable), after_turn_hook=plant,
    )
    assert not rec.solved and "target tests still failing" in rec.verdict_reason
    assert rec.tests_touched == ["tests/conftest.py"]


def test_a_stray_test_file_does_not_stop_a_real_fix_and_is_recorded(tmp_path):
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    work = settings.runs_dir / "r-stray" / "work"

    def stray(turn):
        (work / "tests" / "test_scratch.py").write_text("def test_scratch():\n    assert False\n")

    rec = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=solving_script(), run_id="r-stray",
        venv_python=Path(sys.executable), after_turn_hook=stray,
    )
    assert rec.solved and rec.tests_touched == ["tests/test_scratch.py"]


def solving_script():
    return ScriptedClient(
        [
            reply([tool_use("t1", "edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})], stop="tool_use"),
            reply([tool_use("t2", "run_tests", {})], stop="tool_use"),
            reply([text("fixed")]),
        ]
    )
