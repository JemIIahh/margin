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
        from margin.run import execute_run

        rec = execute_run(
            task, args.arm, settings, run_id=args.run_id, version=args.version, trace_tags=tags
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
    from margin.bench.runner import BudgetExceeded, run_batch

    settings = Settings.from_env()
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
    print(f"{len(ids)} runs recorded in {settings.ledger_path}")
    return 0


def cmd_calibrate_flat(args: argparse.Namespace) -> int:
    import json

    from margin.bench.report import calibrate_flat_price
    from margin.ledger import Ledger

    settings = Settings.from_env()
    result = calibrate_flat_price(Ledger(settings.ledger_path).latest("A"), settings.target_markup)
    path = settings.root / "bench" / "flat_price.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"flat price ${result['flat_price_usd']:.4f} from {result['n']} calibration runs -> {path}")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)
