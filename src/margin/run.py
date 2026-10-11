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
from margin.ledger import Ledger, RunRecord, history_ledger, render_receipt, settle
from margin.model import make_model_client
from margin.pricing import PriceTable, SpendMeter, Usage
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


def _abort_reason(stop: str, reason: str | None) -> str | None:
    """A run that finished on its own, or that arm D ended because its fix had verified, did not stop early."""
    return None if stop in ("end_turn", "verified") else (reason or stop)


def _declined(task, arm, run_id, run_dir, started, intake, ledger, tags) -> RunRecord:
    """A run the gate stopped: only the gate's own spend is lost, and nothing was cloned or run."""
    record = RunRecord(
        run_id=run_id, task_id=task.id, arm=arm, split=task.split, solved=False, cost_usd=intake.cost_usd,
        price_usd=0.0, revenue_usd=0.0, margin_usd=-intake.cost_usd, tokens_total=intake.input_tokens,
        abort_reason="declined at intake: " + ("; ".join(intake.reasons) or intake.decision),
        duration_s=round(time.time() - started, 1),
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        trace_tags=[*tags, "intake:declined"], verdict_reason=f"declined at intake ({intake.decision})",
    )
    ledger.append(record)
    (run_dir / "receipt.md").write_text(render_receipt(record))
    return record


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
    issue_text: str | None = None,
    gate: Any = None,
    variant_id: str | None = None,
    jev: Any = None,
) -> RunRecord:
    if arm not in ("A", "B", "C", "D", "E"):
        raise ValueError(f"unknown arm {arm!r}")
    # The gate is part of arm E; on any other arm a gated run is a demo, as is any run on an intake variant.
    if ((gate is not None and arm != "E") or variant_id) and not version.startswith("demo"):
        raise ValueError("gated and variant runs are not benchmark runs: use a version starting with 'demo'")
    prices = PriceTable.load(settings.pricing_path)
    ledger = Ledger(settings.ledger_path)
    run_id = run_id or new_run_id(task.id, arm)
    run_dir = settings.runs_dir / run_id
    state = RunState(run_dir)
    (run_dir / "meta.json").write_text(json.dumps({"task_id": task.id, "arm": arm, "version": version}))
    started = time.time()
    tags = [*(trace_tags or []), *([f"variant:{variant_id}"] if variant_id else [])]

    issue = issue_text if issue_text is not None else task.issue_text(tasks_root or settings.root)
    intake_cost = 0.0
    if gate is not None:  # screen untrusted issue text before cloning anything or spending anything
        intake = gate.screen(issue)
        state.log("intake", **intake.to_dict())
        intake_cost = intake.cost_usd
        if intake.decision != "accept":
            return _declined(task, arm, run_id, run_dir, started, intake, ledger, tags)
        tags.append("intake:accepted")

    try:
        prep = prepare_run(task, run_dir, settings, venv_python=venv_python)
    except Exception as exc:  # noqa: BLE001 - a baseline that hangs or cannot run must leave a row, not a traceback
        reason = f"harness error: {type(exc).__name__}: {exc}"
        state.log("harness_error", error=reason)
        failed = RunRecord(
            run_id=run_id, task_id=task.id, arm=arm, split=task.split, solved=False, cost_usd=0.0, price_usd=0.0,
            revenue_usd=0.0, margin_usd=0.0, tokens_total=0, abort_reason=reason,
            duration_s=round(time.time() - started, 1), fault=settings.fault,
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
            trace_tags=tags, verdict_reason=reason, infra_error=True,
        )
        ledger.append(failed)
        (run_dir / "receipt.md").write_text(render_receipt(failed))
        return failed
    sandbox = prep.sandbox

    graph = None
    features: dict = {}
    quote: dict | None = None
    price = 0.0  # arms A and B are priced at report time (flat price)
    governor: Any = NullGovernor()
    if arm in ("B", "C", "D", "E"):
        from margin.context import GraphContext  # added in Task 15
        from margin.quote import extract_features  # added in Task 14

        graph = GraphContext(sandbox.root)
        feats = extract_features(issue, sandbox.root, prep.baseline_seconds, graph)
        features = feats.to_dict()
        state.log("features", **features)
        if arm in ("C", "D", "E"):
            from margin.quote import Quoter, training_rows  # added in Task 14

            saved = state.events("quote") if resume else []
            if saved:  # a resumed run keeps its original quote, even if the ledger has grown since
                quote = {k: saved[-1][k] for k in ("p50", "lo", "hi")}
                price = saved[-1]["price"]
            else:
                history = history_ledger(settings.root, settings.ledger_path)
                quoted = Quoter(training_rows(history, exclude=task.id), prior_cost=settings.default_cost_usd).quote(feats)
                quote = {"p50": quoted.p50, "lo": quoted.lo, "hi": quoted.hi}
                price = quoted.price(settings.target_markup)
                state.log("quote", price=price, **quote)
            governor = Governor(quote["hi"], settings.downgrade_at, settings.narrow_at)

    meter = SpendMeter(prices)
    executor = ToolExecutor(
        sandbox=sandbox, arm=arm, baseline=prep.baseline, target_nodeids=task.target_tests,
        target_junit_ids=task.target_junit_ids, test_args=task.test_args, protected_paths=task.test_files,
        issue_text=issue, graph=graph, faults=faults, state=state, python_timeout_s=settings.python_timeout_s,
    )
    context = _initial_context(graph, issue, sandbox.root, settings, state)
    lessons = None
    judge = None
    if arm in ("D", "E"):  # what earlier jobs in this repository taught, never a lesson about this task itself
        from margin.lessons import lessons_for, load_lessons

        if arm == "D":
            lessons = lessons_for(task.id, task.repo, load_lessons(settings.lessons_path), settings.lessons_max)
        else:  # arm E: Jev picks the lessons that fit this issue from every eligible one, and judges progress
            from margin.jev import JEV_MODEL, ProgressJudge, make_jev, pick_lessons

            jev = jev or make_jev()
            judge = ProgressJudge(jev)
            eligible = lessons_for(task.id, task.repo, load_lessons(settings.lessons_path), 50)
            used_before = jev.input_tokens
            lessons = pick_lessons(issue, eligible, jev, settings.lessons_max)
            picked = Usage(input_tokens=jev.input_tokens - used_before)  # what Jev reported, metered like any call
            if picked.input_tokens:
                cost = meter.record(JEV_MODEL, picked)
                state.log("model_usage", model=JEV_MODEL, usage=picked.to_dict(), cost=round(cost, 8), stop="lessons", role="judge")
            state.log("lessons_picked", eligible=len(eligible), chosen=len(lessons))
        state.log("lessons", count=len(lessons))
    checkpoint = state.load_checkpoint() if resume else None
    if resume:  # even with no checkpoint yet: calls made before the kill were paid for and are in the event log
        state.restore_meter(meter)
    tampered: str | None = None
    harness_error: str | None = None
    model_client = None
    try:
        model_client = client or make_model_client(settings)
        result = run_agent(
            first_prompt=first_prompt(issue, context, task.target_tests, lessons), arm=arm,
            client=model_client, meter=meter, governor=governor, executor=executor,
            state=state, prices=prices, settings=settings, faults=faults, resume=checkpoint,
            after_turn_hook=after_turn_hook, judge=judge,
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
        abort_reason = _abort_reason(result.stop, result.abort_reason)
    total_cost = meter.total_usd + intake_cost  # the gate's own spend counts against the run
    revenue, margin = settle(price, verdict.solved, total_cost)
    record = RunRecord(
        run_id=run_id, task_id=task.id, arm=arm, split=task.split, solved=verdict.solved,
        cost_usd=total_cost, price_usd=price, revenue_usd=revenue, margin_usd=margin,
        tokens_total=meter.total_tokens, features=features, quote=quote, rung_events=result.rung_events,
        abort_reason=abort_reason,
        duration_s=round(time.time() - started, 1), fault=settings.fault,
        recoveries=len(state.events("recovery")) + len(state.events("retry")),
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        trace_tags=tags, verdict_reason=verdict.reason, tests_touched=tests_touched,
        infra_error=harness_error is not None or result.stop == "error",
        api_timeouts=sum(1 for e in state.events("retry") if e.get("error") == "APITimeoutError")
        + (1 if (harness_error or "").startswith("APITimeoutError") else 0),
    )
    ledger.append(record)
    (run_dir / "receipt.md").write_text(render_receipt(record))
    return record
