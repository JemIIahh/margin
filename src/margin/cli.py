"""Command line entry point. Subcommands are added task by task."""
from __future__ import annotations

import argparse
from pathlib import Path

from margin.bench.tasks import find_task, load_tasks
from margin.config import Settings, load_dotenv
from margin.telemetry import init_telemetry, shutdown_telemetry


def _tasks_path(args: argparse.Namespace, settings: Settings) -> Path:
    return Path(args.tasks_file) if args.tasks_file else settings.root / "bench" / "tasks.toml"


def cmd_run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    task = find_task(load_tasks(_tasks_path(args, settings)), args.task)
    tags = [f"arm:{args.arm}", f"task:{task.id}", f"split:{task.split}", f"version:{args.version}"]
    init_telemetry("margin", tags)  # must precede the first `import anthropic`
    try:
        from margin.faults import FaultInjector
        from margin.run import execute_run

        faults = FaultInjector(settings.fault) if settings.fault else None
        rec = execute_run(
            task, args.arm, settings, run_id=args.run_id, version=args.version, trace_tags=tags, faults=faults
        )
        print(f"{rec.run_id}: solved={rec.solved} cost=${rec.cost_usd:.4f} margin=${rec.margin_usd:.4f}")
        print(f"receipt: {settings.runs_dir / rec.run_id / 'receipt.md'}")
        return 0 if rec.solved else 1
    finally:
        shutdown_telemetry()


def cmd_tasks_validate(args: argparse.Namespace) -> int:
    from margin.bench.tasks import validate_task

    settings = Settings.from_env()
    tasks = load_tasks(_tasks_path(args, settings))
    chosen = [find_task(tasks, i) for i in args.ids] if args.ids else tasks
    failures = 0
    for task in chosen:
        result = validate_task(task, settings)
        status = "ok  " if result["ok"] else "FAIL"
        print(f"{status} {task.id} ({result['baseline_seconds']}s) {'; '.join(result['problems'])}")
        failures += 0 if result["ok"] else 1
    return 1 if failures else 0


def cmd_bench(args: argparse.Namespace) -> int:
    from margin.bench.runner import BudgetExceeded, InfrastructureFailure, run_batch

    settings = Settings.from_env()
    if settings.fault:
        print(f"MARGIN_FAULT={settings.fault} is set; refusing to run a benchmark with injected faults (unset it)")
        return 2
    tasks = load_tasks(_tasks_path(args, settings))
    chosen = [t for t in tasks if args.split == "all" or t.split == args.split]
    try:
        ids = run_batch(
            chosen, args.arm, settings, version=args.version, tasks_file=args.tasks_file,
            only_missing=args.only_missing,
        )
    except BudgetExceeded as exc:
        print(f"stopped: {exc}")
        return 2
    except InfrastructureFailure as exc:
        print(f"stopped: {exc}")
        return 3
    print(f"{len(ids)} runs recorded in {settings.ledger_path}")
    return 0


def _calibration_ids(settings: Settings, tasks_file: str | None = None) -> set[str]:
    from margin.bench.tasks import load_tasks

    return {t.id for t in load_tasks(Path(tasks_file or settings.root / "bench" / "tasks.toml")) if t.split == "calibration"}


def cmd_calibrate_flat(args: argparse.Namespace) -> int:
    import json

    from margin.bench.report import calibrate_flat_price
    from margin.ledger import Ledger

    settings = Settings.from_env()
    try:
        result = calibrate_flat_price(
            Ledger(settings.ledger_path).latest("A"), settings.target_markup, _calibration_ids(settings)
        )
    except ValueError as exc:
        print(f"cannot calibrate the flat price: {exc}")
        return 1
    path = settings.root / "bench" / "flat_price.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"flat price ${result['flat_price_usd']:.4f} from {result['n']} calibration runs -> {path}")
    return 0


def cmd_quote(args: argparse.Namespace) -> int:
    from margin.bench.tasks import prepare_run, remove_worktree
    from margin.context import GraphContext
    from margin.ledger import history_ledger
    from margin.quote import Quoter, extract_features, training_rows

    settings = Settings.from_env()
    task = find_task(load_tasks(_tasks_path(args, settings)), args.task)
    prep = prepare_run(task, settings.runs_dir / f"quote-{task.id}", settings)
    try:
        features = extract_features(
            task.issue_text(settings.root), prep.sandbox.root, prep.baseline_seconds, GraphContext(prep.sandbox.root)
        )
    finally:  # a quote only needs the features; do not leave a checkout behind for every quote asked
        remove_worktree(prep.bare, prep.sandbox.root)
    rows = training_rows(history_ledger(settings.root, settings.ledger_path), exclude=task.id)
    quote = Quoter(rows, prior_cost=settings.default_cost_usd).quote(features)
    print(
        f"{task.id}: cost band ${quote.lo:.4f} - ${quote.hi:.4f} (p50 ${quote.p50:.4f}) "
        f"from {len(rows)} past runs; price ${quote.price(settings.target_markup):.4f}"
    )
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    import json

    from margin.ledger import Ledger

    settings = Settings.from_env()
    if any(r.run_id == args.run_id for r in Ledger(settings.ledger_path).rows()):
        print(f"{args.run_id} already finished; nothing to resume")
        return 1
    meta = json.loads((settings.runs_dir / args.run_id / "meta.json").read_text())
    task = find_task(load_tasks(_tasks_path(args, settings)), meta["task_id"])
    tags = [
        f"arm:{meta['arm']}", f"task:{task.id}", f"split:{task.split}", f"version:{meta['version']}", "resumed:true"
    ]
    init_telemetry("margin", tags)
    try:
        from margin.faults import FaultInjector
        from margin.run import execute_run

        faults = FaultInjector(settings.fault) if settings.fault else None
        rec = execute_run(
            task, meta["arm"], settings, run_id=args.run_id, version=meta["version"], resume=True,
            faults=faults, trace_tags=tags,
        )
        print(f"{rec.run_id}: resumed, solved={rec.solved} cost=${rec.cost_usd:.4f} margin=${rec.margin_usd:.4f}")
        return 0 if rec.solved else 1
    finally:
        shutdown_telemetry()


def cmd_report(args: argparse.Namespace) -> int:
    import json

    from margin.bench.report import render_receipts_page, render_results
    from margin.ledger import Ledger

    settings = Settings.from_env()
    ledger = Ledger(Path(args.ledger) if args.ledger else settings.root / "docs" / "evidence" / "ledger.jsonl")
    flat_path = Path(args.flat or settings.root / "bench" / "flat_price.json")
    if not flat_path.exists():
        print(f"{flat_path} is missing; run `uv run margin calibrate-flat` after the arm A calibration runs")
        return 1
    flat = json.loads(flat_path.read_text())
    from margin.bench.report import calibrate_flat_price

    try:
        derived = calibrate_flat_price(
            ledger.latest("A"), flat.get("markup", settings.target_markup), _calibration_ids(settings, args.tasks_file)
        )
    except ValueError as exc:
        print(f"cannot check the flat price against {ledger.path}: {exc}")
        return 1
    if abs(derived["flat_price_usd"] - flat["flat_price_usd"]) > 1e-4:
        print(
            f"{flat_path} says ${flat['flat_price_usd']:.4f} but the ledger's arm A calibration runs give "
            f"${derived['flat_price_usd']:.4f}; run `uv run margin calibrate-flat` (after `snapshot-ledger`)"
        )
        return 1
    out = Path(args.out or settings.root / "docs" / "results.md")
    text = render_results(ledger, flat)
    if args.check:
        if not out.exists() or out.read_text() != text:
            print(f"{out} is stale; run `uv run margin report`")
            return 1
        print(f"{out} is up to date")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {out}")
    html = Path(args.html) if args.html else settings.root / "docs" / "receipts.html"
    html.write_text(render_receipts_page(list(ledger.latest("C").values())))
    print(f"wrote {html}")
    return 0


def cmd_snapshot_ledger(args: argparse.Namespace) -> int:
    import shutil

    settings = Settings.from_env()
    dest = settings.root / "docs" / "evidence" / "ledger.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(settings.ledger_path, dest)
    print(f"copied {settings.ledger_path} -> {dest}")
    return 0


def cmd_cfo_inputs(args: argparse.Namespace) -> int:
    import json

    from margin.bench.cfo import cfo_inputs, render_ari_prompt, render_inputs_table
    from margin.ledger import Ledger

    settings = Settings.from_env()
    flat_path = Path(args.flat or settings.root / "bench" / "flat_price.json")
    if not flat_path.exists():
        print(f"{flat_path} is missing; run `uv run margin calibrate-flat` after the arm A calibration runs")
        return 1
    flat = json.loads(flat_path.read_text())["flat_price_usd"]
    ledger = Ledger(Path(args.ledger) if args.ledger else settings.root / "docs" / "evidence" / "ledger.jsonl")
    inputs = cfo_inputs(ledger, flat)
    if not inputs:
        print(f"no evaluation runs in {ledger.path}; run the benchmark and `uv run margin snapshot-ledger` first")
        return 1
    out = Path(args.out) if args.out else settings.root / "docs" / "business"
    out.mkdir(parents=True, exist_ok=True)
    (out / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    (out / "inputs.md").write_text(render_inputs_table(inputs) + "\n")
    (out / "ari-prompt.md").write_text(render_ari_prompt(inputs) + "\n")
    print(render_inputs_table(inputs))
    print(f"wrote {out}/inputs.json, inputs.md and ari-prompt.md")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="margin")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one task with one arm")
    run.add_argument("--task", required=True)
    run.add_argument("--arm", required=True, choices=["A", "B", "C"])
    run.add_argument("--tasks-file", default=None)
    run.add_argument("--run-id", default=None)
    run.add_argument("--version", default="v1")
    run.set_defaults(func=cmd_run)

    tasks = sub.add_parser("tasks", help="inspect and validate the benchmark tasks")
    tasks_sub = tasks.add_subparsers(dest="tasks_command", required=True)
    validate = tasks_sub.add_parser("validate", help="check tasks are usable")
    validate.add_argument("--ids", nargs="*", default=None)
    validate.add_argument("--tasks-file", default=None)
    validate.set_defaults(func=cmd_tasks_validate)
    bench = sub.add_parser("bench", help="run one arm over many tasks")
    bench.add_argument("--arm", required=True, choices=["A", "B", "C"])
    bench.add_argument("--split", default="all", choices=["all", "calibration", "evaluation"])
    bench.add_argument("--version", default="v1")
    bench.add_argument("--tasks-file", default=None)
    bench.add_argument("--only-missing", action="store_true")
    bench.set_defaults(func=cmd_bench)

    flat = sub.add_parser("calibrate-flat", help="set the flat price from arm A calibration costs")
    flat.set_defaults(func=cmd_calibrate_flat)
    quote = sub.add_parser("quote", help="print the price band for a task without running it")
    quote.add_argument("--task", required=True)
    quote.add_argument("--tasks-file", default=None)
    quote.set_defaults(func=cmd_quote)
    resume = sub.add_parser("resume", help="continue a killed run from its checkpoint")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--tasks-file", default=None)
    resume.set_defaults(func=cmd_resume)
    report = sub.add_parser("report", help="regenerate docs/results.md and the receipts page from the ledger")
    report.add_argument("--ledger", default=None)
    report.add_argument("--flat", default=None)
    report.add_argument("--out", default=None)
    report.add_argument("--html", default=None)
    report.add_argument("--tasks-file", default=None, help="manifest naming the calibration tasks (default bench/tasks.toml)")
    report.add_argument("--check", action="store_true", help="fail if the results file is out of date")
    report.set_defaults(func=cmd_report)

    snap = sub.add_parser("snapshot-ledger", help="copy runs/ledger.jsonl to docs/evidence/ledger.jsonl")
    snap.set_defaults(func=cmd_snapshot_ledger)
    cfo = sub.add_parser("cfo-inputs", help="write the measured numbers and prompt for the cfo.ai plan")
    cfo.add_argument("--ledger", default=None)
    cfo.add_argument("--flat", default=None)
    cfo.add_argument("--out", default=None)
    cfo.set_defaults(func=cmd_cfo_inputs)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)
