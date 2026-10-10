from types import SimpleNamespace

import pytest

from margin.bench.runner import BudgetExceeded, run_batch
from margin.bench.tasks import Task
from margin.config import Settings
from margin.ledger import Ledger
from test_ledger import rec


def task(i):
    return Task(
        id=f"t{i}", split="evaluation", repo="r", base_commit="b", fix_commit="f", issue_url="u",
        issue_file="i.md", target_tests=["tests/t.py::test_a"], test_files=["tests/t.py"],
    )


def fake_runner(ledger, cost):
    def run(cmd, **kwargs):
        value = lambda flag: cmd[cmd.index(flag) + 1]
        ledger.append(rec(run_id=value("--run-id"), task=value("--task"), arm=value("--arm"), cost=cost))
        return SimpleNamespace(returncode=0, stderr="")

    return run


def test_batch_launches_one_subprocess_per_task(tmp_path):
    settings = Settings(ledger_path=tmp_path / "ledger.jsonl", bench_budget_usd=100.0, root=tmp_path)
    ledger = Ledger(settings.ledger_path)
    ids = run_batch([task(1), task(2)], "A", settings, version="v1", runner=fake_runner(ledger, 0.5))
    assert len(ids) == 2
    assert [r.task_id for r in ledger.rows()] == ["t1", "t2"]


def test_batch_stops_before_the_next_run_once_the_budget_is_spent(tmp_path):
    settings = Settings(ledger_path=tmp_path / "ledger.jsonl", bench_budget_usd=1.0, root=tmp_path)
    ledger = Ledger(settings.ledger_path)
    with pytest.raises(BudgetExceeded, match="t4"):
        run_batch([task(i) for i in range(1, 6)], "A", settings, version="v1", runner=fake_runner(ledger, 0.4))
    assert len(ledger.rows()) == 3


def test_only_missing_skips_tasks_that_already_have_a_row(tmp_path):
    settings = Settings(ledger_path=tmp_path / "ledger.jsonl", bench_budget_usd=100.0, root=tmp_path)
    ledger = Ledger(settings.ledger_path)
    ledger.append(rec(run_id="old", task="t1", arm="A", trace_tags=["version:v1"]))
    ids = run_batch([task(1), task(2)], "A", settings, version="v1", runner=fake_runner(ledger, 0.1), only_missing=True)
    assert len(ids) == 1


def test_only_missing_looks_at_the_requested_version_not_at_older_ones(tmp_path):
    settings = Settings(ledger_path=tmp_path / "ledger.jsonl", bench_budget_usd=100.0, root=tmp_path)
    ledger = Ledger(settings.ledger_path)
    ledger.append(rec(run_id="old", task="t1", arm="A", trace_tags=["version:v1"]))
    ids = run_batch([task(1)], "A", settings, version="v2", runner=fake_runner(ledger, 0.1), only_missing=True)
    assert len(ids) == 1                                  # a v1 row does not mean t1 is done for v2


def test_the_spend_of_a_run_killed_on_timeout_still_counts_against_the_budget(tmp_path, capsys):
    import json
    import subprocess

    settings = Settings(
        ledger_path=tmp_path / "ledger.jsonl", runs_dir=tmp_path / "runs", bench_budget_usd=0.05, root=tmp_path
    )
    launched = []

    def killed(cmd, **kwargs):
        run_id = cmd[cmd.index("--run-id") + 1]
        launched.append(run_id)
        run_dir = settings.runs_dir / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "events.jsonl").write_text(json.dumps({"type": "model_usage", "cost": 0.06}) + "\n")
        raise subprocess.TimeoutExpired(cmd, 1)

    with pytest.raises(BudgetExceeded):
        run_batch([task(1), task(2)], "A", settings, version="v1", runner=killed)
    assert len(launched) == 1                             # the second task never started


def test_a_subprocess_that_writes_no_row_is_skipped_not_fatal(tmp_path, capsys):
    settings = Settings(ledger_path=tmp_path / "ledger.jsonl", bench_budget_usd=100.0, root=tmp_path)
    crashed = lambda cmd, **kw: SimpleNamespace(returncode=2, stderr="boom")
    assert run_batch([task(1)], "A", settings, version="v1", runner=crashed) == []
    assert "no ledger row" in capsys.readouterr().err


def failing_runner(ledger):
    def run(cmd, **kwargs):
        value = lambda flag: cmd[cmd.index(flag) + 1]
        ledger.append(
            rec(run_id=value("--run-id"), task=value("--task"), arm=value("--arm"), cost=0.0, solved=False, infra_error=True)
        )
        return SimpleNamespace(returncode=1, stderr="")

    return run


def test_only_missing_retries_tasks_whose_only_row_was_an_infrastructure_failure(tmp_path):
    settings = Settings(ledger_path=tmp_path / "ledger.jsonl", bench_budget_usd=100.0, root=tmp_path)
    ledger = Ledger(settings.ledger_path)
    ledger.append(rec(run_id="old", task="t1", arm="A", solved=False, infra_error=True, cost=0.0))
    ids = run_batch([task(1)], "A", settings, version="v1", runner=fake_runner(ledger, 0.1), only_missing=True)
    assert len(ids) == 1


def test_the_batch_stops_after_two_consecutive_infrastructure_failures(tmp_path):
    from margin.bench.runner import InfrastructureFailure

    settings = Settings(ledger_path=tmp_path / "ledger.jsonl", bench_budget_usd=100.0, root=tmp_path)
    ledger = Ledger(settings.ledger_path)
    with pytest.raises(InfrastructureFailure, match="2 consecutive"):
        run_batch([task(i) for i in range(1, 6)], "A", settings, version="v1", runner=failing_runner(ledger))
    assert len(ledger.rows()) == 2                 # it did not burn through the rest of the batch


def test_a_hung_run_is_killed_and_reported_with_a_resume_hint(tmp_path, capsys):
    import subprocess

    settings = Settings(ledger_path=tmp_path / "ledger.jsonl", bench_budget_usd=100.0, root=tmp_path)

    def hung(cmd, **kwargs):
        assert kwargs["timeout"] == settings.run_timeout_s       # every run has a deadline
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    assert run_batch([task(1)], "A", settings, version="v1", runner=hung) == []
    err = capsys.readouterr().err
    assert "timed out" in err and "margin resume --run-id" in err
