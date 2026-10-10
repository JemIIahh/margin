"""One task, one arm, start to finish: prepare, (quote), run the agent, verify, settle, record."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from margin.agent.loop import AgentResult, run_agent
from margin.agent.prompts import first_prompt
from margin.agent.tools import ToolExecutor
from margin.bench.tasks import Task, prepare_run
from margin.config import Settings
from margin.context import GraphError, naive_context
from margin.errors import SimulatedCrash
from margin.governor import Governor, NullGovernor
from margin.ledger import Ledger, RunRecord, render_receipt, settle
from margin.model import make_model_client
from margin.pricing import PriceTable, SpendMeter
from margin.sandbox import GitTampered
from margin.state import RunState
from margin.telemetry import span
from margin.verify import Verdict, final_verdict


def new_run_id(task_id: str, arm: str) -> str:
    return f"{task_id}-{arm}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


def _initial_context(graph: Any, issue: str, root: Path, settings: Settings, state: RunState) -> str:
    if graph is not None:
        try:
            return graph.search(issue[:2000])
        except GraphError as exc:
            state.log("graph_error", error=str(exc))  # fall back rather than lose the run
    return naive_context(root, settings.naive_context_chars)


@span(kind="WORKFLOW", name="margin.run")
def execute_run(
    task: Task,
    arm: str,
    settings: Settings,
    *,
    tasks_root: Path | None = None,
    client: Any = None,
    run_id: str | None = None,
    version: str = "v1",
    venv_python: Path | None = None,
    resume: bool = False,
    faults: Any = None,
    after_turn_hook: Any = None,
    trace_tags: list[str] | None = None,
) -> RunRecord:
    if arm not in ("A", "B", "C"):
        raise ValueError(f"unknown arm {arm!r}")
    prices = PriceTable.load(settings.pricing_path)
    ledger = Ledger(settings.ledger_path)
    run_id = run_id or new_run_id(task.id, arm)
    run_dir = settings.runs_dir / run_id
    state = RunState(run_dir)
    (run_dir / "meta.json").write_text(json.dumps({"task_id": task.id, "arm": arm, "version": version}))
    started = time.time()

    prep = prepare_run(task, run_dir, settings, venv_python=venv_python)
    sandbox = prep.sandbox
    issue = task.issue_text(tasks_root or settings.root)

    graph = None
    features: dict = {}
    quote: dict | None = None
    price = 0.0  # arms A and B are priced at report time (flat price)
    governor: Any = NullGovernor()
    if arm in ("B", "C"):
        from margin.context import GraphContext  # added in Task 15
        from margin.quote import extract_features  # added in Task 14

        graph = GraphContext(sandbox.root)
        feats = extract_features(issue, sandbox.root, prep.baseline_seconds, graph)
        features = feats.to_dict()
        state.log("features", **features)
        if arm == "C":
            from margin.quote import Quoter, training_rows  # added in Task 14

            saved = state.events("quote") if resume else []
            if saved:  # a resumed run keeps its original quote, even if the ledger has grown since
                quote = {k: saved[-1][k] for k in ("p50", "lo", "hi")}
                price = saved[-1]["price"]
            else:
                quoted = Quoter(training_rows(ledger, exclude=task.id), prior_cost=settings.default_cost_usd).quote(feats)
                quote = {"p50": quoted.p50, "lo": quoted.lo, "hi": quoted.hi}
                price = quoted.price(settings.target_markup)
                state.log("quote", price=price, **quote)
            governor = Governor(quote["hi"], settings.downgrade_at, settings.narrow_at)

    meter = SpendMeter(prices)
    executor = ToolExecutor(
        sandbox=sandbox, arm=arm, baseline=prep.baseline, target_nodeids=task.target_tests,
        target_junit_ids=task.target_junit_ids, test_args=task.test_args, protected_paths=task.test_files,
        issue_text=issue, graph=graph, faults=faults, state=state,
    )
    context = _initial_context(graph, issue, sandbox.root, settings, state)
    checkpoint = state.load_checkpoint() if resume else None
    if resume:  # even with no checkpoint yet: calls made before the kill were paid for and are in the event log
        state.restore_meter(meter)
    tampered: str | None = None
    harness_error: str | None = None
    model_client = None
    try:
        model_client = client or make_model_client(settings)
        result = run_agent(
            first_prompt=first_prompt(issue, context, task.target_tests), arm=arm,
            client=model_client, meter=meter, governor=governor, executor=executor,
            state=state, prices=prices, settings=settings, faults=faults, resume=checkpoint,
            after_turn_hook=after_turn_hook,
        )
    except SimulatedCrash:  # a killed process records nothing; `margin resume` continues it
        raise
    except GitTampered as exc:  # ends the run as unsolved; every further git call would raise again
        tampered = str(exc)
        state.log("tampering", error=tampered)
        result = AgentResult("abort", 0, f"sandbox tampering detected: {tampered}")
    except Exception as exc:  # noqa: BLE001 - money may already be spent, so whatever broke must still leave a row
        harness_error = f"{type(exc).__name__}: {exc}"
        state.log("harness_error", error=harness_error)
        result = AgentResult("error", 0, f"harness error: {harness_error}")

    proxy_usd = getattr(model_client, "proxy_cost_usd", None)
    if proxy_usd is not None:  # the proxy's own bill for this run, to compare with our metering
        state.log("proxy_cost", proxy_usd=round(proxy_usd, 6), metered_usd=round(meter.total_usd, 6))

    tests_touched: list[str] = []
    no_targets = list(task.target_junit_ids)
    if tampered:
        verdict = Verdict(False, no_targets, [], f"sandbox tampering detected: {tampered}")
    elif harness_error:
        verdict = Verdict(False, no_targets, [], f"harness error: {harness_error}")
    else:
        try:
            # Judge the repository's own tests under its own configuration: undo every change to test files and test
            # infrastructure (conftest.py, pytest config, ...) first, so nothing the agent wrote can change what passing means.
            tests_touched = sandbox.revert_test_changes()
            verdict = final_verdict(sandbox, prep.baseline, task.target_junit_ids, task.test_args, run_dir / "final.xml")
        except GitTampered as exc:  # test code changed the git config during the last run
            tampered = str(exc)
            state.log("tampering", error=tampered)
            verdict = Verdict(False, no_targets, [], f"sandbox tampering detected: {tampered}")
        except Exception as exc:  # noqa: BLE001 - the spend so far must still be recorded
            harness_error = f"{type(exc).__name__}: {exc}"
            state.log("harness_error", error=harness_error)
            verdict = Verdict(False, no_targets, [], f"harness error: {harness_error}")

    if tampered:
        abort_reason: str | None = f"sandbox tampering detected: {tampered}"
    elif harness_error:
        abort_reason = f"harness error: {harness_error}"
    else:
        abort_reason = None if result.stop == "end_turn" else (result.abort_reason or result.stop)
    revenue, margin = settle(price, verdict.solved, meter.total_usd)
    record = RunRecord(
        run_id=run_id, task_id=task.id, arm=arm, split=task.split, solved=verdict.solved,
        cost_usd=meter.total_usd, price_usd=price, revenue_usd=revenue, margin_usd=margin,
        tokens_total=meter.total_tokens, features=features, quote=quote, rung_events=result.rung_events,
        abort_reason=abort_reason,
        duration_s=round(time.time() - started, 1), fault=settings.fault,
        recoveries=len(state.events("recovery")) + len(state.events("retry")),
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        trace_tags=trace_tags or [], verdict_reason=verdict.reason, tests_touched=tests_touched,
        infra_error=harness_error is not None or result.stop == "error",
    )
    ledger.append(record)
    (run_dir / "receipt.md").write_text(render_receipt(record))
    return record
