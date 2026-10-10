import sys
from pathlib import Path

import pytest

from fakes import ScriptedClient, reply, text, tool_use
from margin.errors import SimulatedCrash
from margin.ledger import Ledger
from margin.run import execute_run
from test_tasks import make_task, settings_for


def script():
    return [
        reply([tool_use("t1", "edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})], stop="tool_use"),
        reply([tool_use("t2", "run_tests", {})], stop="tool_use"),
        reply([text("fixed")]),
    ]


def test_a_crashed_run_resumes_to_the_same_verified_result(tmp_path):
    task, settings = make_task(tmp_path), settings_for(tmp_path)

    def crash(turn):
        if turn == 1:
            raise SimulatedCrash()

    common = {"tasks_root": tmp_path, "run_id": "rz", "venv_python": Path(sys.executable)}
    with pytest.raises(SimulatedCrash):
        execute_run(task, "A", settings, client=ScriptedClient(script()), after_turn_hook=crash, **common)
    assert Ledger(settings.ledger_path).rows() == []  # a crashed run records nothing
    result = execute_run(task, "A", settings, client=ScriptedClient(script()[1:]), resume=True, **common)
    assert result.solved
    assert len(Ledger(settings.ledger_path).rows()) == 1
    assert result.cost_usd == pytest.approx(3 * (100 * 2.0 + 50 * 10.0) / 1e6)  # all three model calls are paid for


def test_a_run_killed_before_its_first_checkpoint_still_pays_for_the_call_already_made(tmp_path, monkeypatch):
    from margin.agent.tools import ToolExecutor

    task, settings = make_task(tmp_path), settings_for(tmp_path)
    real_execute, calls = ToolExecutor.execute, {"n": 0}

    def killed_once(self, name, args):
        if calls["n"] == 0:
            calls["n"] += 1
            raise SimulatedCrash()                      # the process dies while running turn 0's tool
        return real_execute(self, name, args)

    monkeypatch.setattr(ToolExecutor, "execute", killed_once)
    common = {"tasks_root": tmp_path, "run_id": "rq", "venv_python": Path(sys.executable)}
    with pytest.raises(SimulatedCrash):
        execute_run(task, "A", settings, client=ScriptedClient(script()), **common)
    assert not (settings.runs_dir / "rq" / "checkpoint.json").exists()   # no checkpoint yet, but one call was paid
    result = execute_run(task, "A", settings, client=ScriptedClient(script()), resume=True, **common)
    assert result.solved
    assert result.cost_usd == pytest.approx(4 * (100 * 2.0 + 50 * 10.0) / 1e6)   # 1 lost-then-redone call + 3 more
