import sys
from pathlib import Path

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
