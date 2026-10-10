"""Batch runner: one subprocess per (task, arm) so neatlogs tags are per run, with a global spend guard."""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable

from margin.bench.tasks import Task
from margin.config import Settings
from margin.ledger import Ledger
from margin.run import new_run_id


class BudgetExceeded(RuntimeError):
    pass


class InfrastructureFailure(RuntimeError):
    """Consecutive runs failed for harness or API reasons, so more runs would only repeat the failure."""


INFRA_FAILURES_BEFORE_STOP = 2


def run_batch(
    tasks: list[Task],
    arm: str,
    settings: Settings,
    *,
    version: str,
    tasks_file: str | None = None,
    runner: Callable = subprocess.run,
    python: str = sys.executable,
    only_missing: bool = False,
) -> list[str]:
    ledger = Ledger(settings.ledger_path)
    spent = sum(r.cost_usd for r in ledger.rows())
    # "done" means a real benchmark row: infrastructure failures, fault runs and demo runs do not count
    done = set(ledger.latest(arm)) if only_missing else set()
    run_ids: list[str] = []
    infra_streak = 0
    for task in tasks:
        if task.id in done:
            continue
        if spent >= settings.bench_budget_usd:
            raise BudgetExceeded(
                f"spent ${spent:.2f} of the ${settings.bench_budget_usd:.2f} budget before {task.id}"
            )
        run_id = new_run_id(task.id, arm)
        cmd = [python, "-m", "margin", "run", "--task", task.id, "--arm", arm, "--run-id", run_id, "--version", version]
        if tasks_file:
            cmd += ["--tasks-file", tasks_file]
        try:
            proc = runner(
                cmd, cwd=settings.root, capture_output=True, text=True, check=False, timeout=settings.run_timeout_s
            )
        except subprocess.TimeoutExpired:
            print(
                f"{task.id}: timed out after {settings.run_timeout_s}s and was killed; money already spent on it is in "
                f"runs/{run_id}/events.jsonl. Continue it with `uv run margin resume --run-id {run_id}`.",
                file=sys.stderr,
            )
            continue
        row = next((r for r in ledger.rows() if r.run_id == run_id), None)
        if row is None:
            print(f"{task.id}: no ledger row (exit {proc.returncode}): {proc.stderr[-500:]}", file=sys.stderr)
            continue
        spent += row.cost_usd
        run_ids.append(run_id)
        infra_streak = infra_streak + 1 if row.infra_error else 0
        if infra_streak >= INFRA_FAILURES_BEFORE_STOP:
            raise InfrastructureFailure(
                f"{infra_streak} consecutive runs failed for infrastructure reasons (last: {row.abort_reason}); "
                "fix the cause (key, credits, network), then re-run with --only-missing"
            )
    return run_ids
