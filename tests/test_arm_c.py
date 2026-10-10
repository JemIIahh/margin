import sys
from pathlib import Path

import pytest

from fakes import FakeGraph, ScriptedClient, reply, text, tool_use
from margin.ledger import Ledger
from margin.quote import Features
from margin.run import execute_run
from test_ledger import rec
from test_tasks import make_task, settings_for


class StubGraph(FakeGraph):
    def __init__(self, root):
        self.root = root

    def impact_size(self, issue):
        return 3


def seed_ledger(settings, cost):
    ledger = Ledger(settings.ledger_path)
    for k in range(6):
        features = Features(20 + k, 3, 2, 0.5 + k / 100).to_dict()
        ledger.append(rec(run_id=f"b{k}", task=f"seed{k}", arm="B", cost=cost, features=features))


def solving_client():
    return ScriptedClient(
        [
            reply([tool_use("t1", "edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})], stop="tool_use"),
            reply([tool_use("t2", "run_tests", {})], stop="tool_use"),
            reply([text("fixed")]),
        ]
    )


def test_arm_c_quotes_prices_and_solves(tmp_path, monkeypatch):
    monkeypatch.setattr("margin.context.GraphContext", StubGraph)
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    seed_ledger(settings, cost=5.0)
    result = execute_run(
        task, "C", settings, tasks_root=tmp_path, client=solving_client(), run_id="c1", venv_python=Path(sys.executable)
    )
    assert result.solved
    assert result.quote["lo"] < result.quote["p50"] < result.quote["hi"]
    assert result.price_usd == pytest.approx(result.quote["hi"] * 1.5)
    assert result.features["impact_files"] == 3
    assert result.margin_usd == pytest.approx(result.price_usd - result.cost_usd)


def test_arm_c_aborts_cleanly_when_the_cap_is_below_one_call(tmp_path, monkeypatch):
    monkeypatch.setattr("margin.context.GraphContext", StubGraph)
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    seed_ledger(settings, cost=0.001)
    client = ScriptedClient([])
    result = execute_run(
        task, "C", settings, tasks_root=tmp_path, client=client, run_id="c2", venv_python=Path(sys.executable)
    )
    assert not result.solved and "cap" in result.abort_reason
    assert client.calls == [] and result.cost_usd == 0.0 and result.margin_usd == 0.0
    assert [e["rung"] for e in result.rung_events] == ["ABORT"]


def test_arm_c_with_an_empty_ledger_uses_the_prior_band(tmp_path, monkeypatch):
    monkeypatch.setattr("margin.context.GraphContext", StubGraph)
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    result = execute_run(
        task, "C", settings, tasks_root=tmp_path, client=solving_client(), run_id="c3", venv_python=Path(sys.executable)
    )
    assert result.quote["p50"] == pytest.approx(settings.default_cost_usd)
    assert result.quote["lo"] < result.quote["hi"]
