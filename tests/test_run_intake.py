import sys
from pathlib import Path

import pytest

from fakes import ScriptedClient, reply, text, tool_use
from margin.intake import IntakeVerdict
from margin.ledger import Ledger
from margin.run import execute_run
from test_tasks import make_task, settings_for


class FakeGate:
    def __init__(self, decision, cost=0.0001, reasons=None):
        self.decision, self.cost, self.reasons = decision, cost, reasons or []
        self.seen = []

    def screen(self, issue):
        self.seen.append(issue)
        return IntakeVerdict(self.decision, 0.9, 0.8, self.reasons, 500, self.cost, 0.2, "req-1")


def solving_client():
    return ScriptedClient(
        [
            reply([tool_use("t1", "edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})], stop="tool_use"),
            reply([tool_use("t2", "run_tests", {})], stop="tool_use"),
            reply([text("fixed")]),
        ]
    )


def test_a_declined_issue_never_reaches_the_agent_or_the_filesystem(tmp_path):
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    client = ScriptedClient([])
    gate = FakeGate("decline", reasons=["injection 0.95 >= 0.70"])
    result = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=client, gate=gate, run_id="r-decl",
        version="demo-intake", venv_python=Path(sys.executable),
    )
    assert not result.solved and client.calls == []
    assert result.abort_reason == "declined at intake: injection 0.95 >= 0.70"
    assert result.cost_usd == pytest.approx(0.0001) and result.margin_usd == pytest.approx(-0.0001)
    assert "intake:declined" in result.trace_tags
    assert not (settings.runs_dir / "r-decl" / "work").exists()  # nothing was cloned
    assert [r.run_id for r in Ledger(settings.ledger_path).rows()] == ["r-decl"]


def test_an_accepted_issue_runs_normally_and_pays_for_the_gate(tmp_path):
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    plain = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=solving_client(), run_id="r-plain",
        venv_python=Path(sys.executable),
    )
    gated = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=solving_client(), gate=FakeGate("accept", cost=0.002),
        run_id="r-gated", version="demo-intake", venv_python=Path(sys.executable),
    )
    assert gated.solved
    assert gated.cost_usd == pytest.approx(plain.cost_usd + 0.002)
    assert "intake:accepted" in gated.trace_tags


def test_a_review_decision_is_not_an_accept(tmp_path):
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    client = ScriptedClient([])
    result = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=client, gate=FakeGate("review", reasons=["gate unavailable"]),
        run_id="r-rev", version="demo-intake", venv_python=Path(sys.executable),
    )
    assert client.calls == [] and "gate unavailable" in result.abort_reason


def test_an_issue_override_replaces_the_task_issue_and_the_variant_is_tagged(tmp_path):
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    client = solving_client()
    gate = FakeGate("accept")
    result = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=client, gate=gate, issue_text="OVERRIDDEN ISSUE TEXT",
        variant_id="inj-1", run_id="r-var", version="demo-intake", venv_python=Path(sys.executable),
    )
    assert gate.seen == ["OVERRIDDEN ISSUE TEXT"]
    assert "OVERRIDDEN ISSUE TEXT" in client.calls[0]["messages"][0]["content"]
    assert "variant:inj-1" in result.trace_tags


def test_gated_and_variant_runs_cannot_masquerade_as_benchmark_rows(tmp_path):
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    with pytest.raises(ValueError, match="not benchmark runs"):
        execute_run(task, "A", settings, tasks_root=tmp_path, client=ScriptedClient([]), gate=FakeGate("accept"),
                    run_id="r-bad", version="v2", venv_python=Path(sys.executable))
    with pytest.raises(ValueError, match="not benchmark runs"):
        execute_run(task, "A", settings, tasks_root=tmp_path, client=ScriptedClient([]), variant_id="inj-1",
                    run_id="r-bad2", version="v2", venv_python=Path(sys.executable))


def test_demo_rows_never_replace_benchmark_rows(tmp_path):
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    execute_run(task, "A", settings, tasks_root=tmp_path, client=solving_client(), run_id="r-real",
                trace_tags=["version:v1"], venv_python=Path(sys.executable))
    execute_run(task, "A", settings, tasks_root=tmp_path, client=ScriptedClient([]), gate=FakeGate("decline"),
                run_id="r-demo", version="demo-intake", trace_tags=["version:demo-intake"],
                venv_python=Path(sys.executable))
    assert Ledger(settings.ledger_path).latest("A")[task.id].run_id == "r-real"
