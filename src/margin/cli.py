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
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)
