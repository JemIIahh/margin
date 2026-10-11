"""Command line entry point. Subcommands are added task by task."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from margin.bench.tasks import find_task, load_tasks
from margin.config import Settings, load_dotenv
from margin.telemetry import init_telemetry, shutdown_telemetry


def _tasks_path(args: argparse.Namespace, settings: Settings) -> Path:
    return Path(args.tasks_file) if args.tasks_file else settings.root / "bench" / "tasks.toml"


def _variant(variant_id: str, task, settings: Settings):
    from margin.bench.intake_eval import load_variants

    found = {v.id: v for v in load_variants(settings.root / "bench" / "intake" / "variants.toml")}
    variant = found.get(variant_id)
    if variant is None or variant.base_task != task.id:
        raise SystemExit(f"variant {variant_id!r} does not belong to task {task.id!r}")
    return variant, (settings.root / variant.issue_file).read_text(encoding="utf-8")


def cmd_run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    task = find_task(load_tasks(_tasks_path(args, settings)), args.task)
    issue_text = variant_id = gate = None
    if args.variant:
        variant, issue_text = _variant(args.variant, task, settings)
        variant_id = variant.id
    if args.gate or args.arm == "E":  # the intake gate is part of arm E
        from margin.intake import IntakeUnavailable, make_gate

        try:
            gate = make_gate()
        except IntakeUnavailable as exc:
            print(exc)
            return 2
    tags = [f"arm:{args.arm}", f"task:{task.id}", f"split:{task.split}", f"version:{args.version}"]
    init_telemetry("margin", tags)  # must precede the first `import anthropic`
    try:
        from margin.faults import FaultInjector
        from margin.run import execute_run

        faults = FaultInjector(settings.fault) if settings.fault else None
        rec = execute_run(
            task, args.arm, settings, run_id=args.run_id, version=args.version, trace_tags=tags, faults=faults,
            issue_text=issue_text, gate=gate, variant_id=variant_id,
        )
        print(f"{rec.run_id}: solved={rec.solved} cost=${rec.cost_usd:.4f} margin=${rec.margin_usd:.4f}")
        receipt = settings.runs_dir / rec.run_id / "receipt.md"  # shown from the repository: the full path names the user
        print(f"receipt: {receipt.relative_to(settings.root) if receipt.is_relative_to(settings.root) else receipt}")
        return 0 if rec.solved else 1
    finally:
        shutdown_telemetry()


def cmd_intake(args: argparse.Namespace) -> int:
    import json

    from margin.intake import IntakeUnavailable, make_gate

    settings = Settings.from_env()
    task = find_task(load_tasks(_tasks_path(args, settings)), args.task)
    text = _variant(args.variant, task, settings)[1] if args.variant else task.issue_text(settings.root)
    try:
        gate = make_gate()
    except IntakeUnavailable as exc:
        print(exc)
        return 2
    verdict = gate.screen(text)
    print(json.dumps(verdict.to_dict(), indent=2))
    return 0 if verdict.decision == "accept" else 1


def cmd_intake_eval(args: argparse.Namespace) -> int:
    import json

    from margin.bench.intake_eval import (
        collect_items,
        load_variants,
        render_calibration_table,
        render_intake_report,
    )
    from margin.intake import IntakeThresholds, IntakeUnavailable, make_gate
    from margin.ledger import Ledger

    settings = Settings.from_env()
    thresholds = IntakeThresholds()
    try:
        gate = make_gate(thresholds)
    except IntakeUnavailable as exc:
        print(exc)
        return 2
    ledger = Ledger(settings.ledger_path)
    items = collect_items(
        gate=gate, split=args.split, tasks=load_tasks(_tasks_path(args, settings)),
        variants=load_variants(settings.root / "bench" / "intake" / "variants.toml"),
        read_text=lambda rel: (settings.root / rel).read_text(encoding="utf-8"),
        benchmark_c=ledger.latest("C"), variant_rows=ledger.rows("C"), runs_dir=settings.runs_dir,
    )
    out = settings.root / "docs" / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"intake-decisions-{args.split}.jsonl").write_text(
        "".join(json.dumps(i.to_dict(), sort_keys=True) + "\n" for i in items), encoding="utf-8"
    )
    if args.split == "calibration":
        print(render_calibration_table(items))
        return 0
    (out / "intake.md").write_text(render_intake_report(items, thresholds), encoding="utf-8")
    print(f"wrote {out / 'intake.md'}")
    return 0


def cmd_tasks_validate(args: argparse.Namespace) -> int:
    from margin.bench.tasks import validate_task

    settings = Settings.from_env()
    tasks = load_tasks(_tasks_path(args, settings))
    chosen = [find_task(tasks, i) for i in args.ids] if args.ids else tasks
    failures = 0
    for task in chosen:
        result = validate_task(task, settings, max_source_files=args.max_source_files, max_seconds=args.max_seconds)
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
    if meta["arm"] == "E" and not os.environ.get("TYPESAFE_API_KEY"):  # say so before preparing anything
        from margin.jev import NO_KEY

        print(NO_KEY)
        return 2
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
    from margin.bench.report import load_layout

    text = render_results(ledger, flat, load_layout(settings.root / "bench" / "report.toml"))
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


def _console_inputs(args: argparse.Namespace, settings: Settings) -> tuple:
    """The ledger snapshot and flat price both console commands read; the second item is an error message."""
    import json

    from margin.ledger import Ledger

    evidence = settings.root / "docs" / "evidence"
    flat_path = Path(args.flat or settings.root / "bench" / "flat_price.json")
    if not flat_path.exists():
        return None, f"{flat_path} is missing; run `uv run margin calibrate-flat` after the arm A calibration runs"
    ledger = Ledger(Path(args.ledger) if args.ledger else evidence / "ledger.jsonl")
    return (ledger, json.loads(flat_path.read_text()), evidence), None


def cmd_snapshot_replays(args: argparse.Namespace) -> int:
    import json

    from margin.bench.console import console_data, load_replays
    from margin.bench.report import load_layout

    settings = Settings.from_env()
    inputs, error = _console_inputs(args, settings)
    if error:
        print(error)
        return 1
    ledger, flat, evidence = inputs
    runs_dir = Path(args.runs_dir) if args.runs_dir else settings.runs_dir
    replays, _ = load_replays(runs_dir, [row.run_id for row in ledger.rows()])
    used = console_data(ledger, flat, replays, layout=load_layout(Path(args.layout or settings.root / "bench" / "report.toml")))
    wanted = {j["run_id"] for jobs in used["jobs"].values() for j in jobs} | {d["run_id"] for d in used["demos"]}
    missing = sorted(wanted - set(used["replays"]))
    if missing:
        print(f"no event log in {runs_dir} for {len(missing)} run(s), e.g. {missing[0]}; the page needs them")
        return 1
    out = Path(args.out) if args.out else evidence / "replays.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(used["replays"], sort_keys=True, separators=(",", ":")) + "\n")
    print(f"wrote {out} ({len(used['replays'])} runs)")
    return 0


def _console_page_data(args: argparse.Namespace, settings: Settings, *, with_links: bool) -> tuple[dict | None, str]:
    """The data the console and the guide are both drawn from, or None and what to run when an input is missing."""
    import json

    from margin.bench.console import console_data, load_links, load_task_meta
    from margin.bench.report import load_layout

    inputs, error = _console_inputs(args, settings)
    if error:
        return None, error
    ledger, flat, evidence = inputs
    replays_path = Path(args.replays) if args.replays else evidence / "replays.json"
    if not replays_path.exists():
        return None, f"{replays_path} is missing; run `uv run margin snapshot-replays` first"
    links = load_links(Path(args.links) if args.links else evidence / "links.json") if with_links else None
    meta = load_task_meta(_tasks_path(args, settings), settings.root)
    layout = load_layout(Path(args.layout or settings.root / "bench" / "report.toml"))
    return console_data(ledger, flat, json.loads(replays_path.read_text()), links, meta, layout), ""


def _write_or_check(out: Path, text: str, check: bool, command: str) -> int:
    if check:
        if not out.exists() or out.read_text() != text:
            print(f"{out} is stale; run `uv run margin {command}`")
            return 1
        print(f"{out} is up to date")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {out}")
    return 0


def cmd_console(args: argparse.Namespace) -> int:
    from margin.bench.console import render_console

    settings = Settings.from_env()
    data, error = _console_page_data(args, settings, with_links=True)
    if data is None:
        print(error)
        return 1
    return _write_or_check(Path(args.out or settings.root / "docs" / "console.html"), render_console(data), args.check, "console")


def cmd_guide(args: argparse.Namespace) -> int:
    from margin.bench.guide import GuideError, render_guide
    from margin.bench.tasks import load_tasks

    settings = Settings.from_env()
    data, error = _console_page_data(args, settings, with_links=False)
    if data is None:
        print(error)
        return 1
    try:
        text = render_guide(data, load_tasks(_tasks_path(args, settings)), console_href=args.console_href,
                            guide_href=args.guide_href, repo_url=args.repo_url)
    except GuideError as exc:
        print(f"the guide cannot be built: {exc}")
        return 1
    return _write_or_check(Path(args.out or settings.root / "docs" / "guide.html"), text, args.check, "guide")


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


def cmd_lessons_build(args: argparse.Namespace) -> int:
    import json

    from margin.ledger import Ledger
    from margin.lessons import build_lessons, save_lessons, select_runs
    from margin.model import make_model_client
    from margin.pricing import PriceTable

    settings = Settings.from_env()
    tasks = {t.id: t for t in load_tasks(_tasks_path(args, settings))}
    runs = select_runs(Ledger(settings.ledger_path).rows())
    model = args.model or settings.coach_model or settings.main_model
    lessons, cost = build_lessons(
        runs, settings.runs_dir, {k: t.repo for k, t in tasks.items()}, client=make_model_client(settings), model=model,
        prices=PriceTable.load(settings.pricing_path), issue_of=lambda task_id: tasks[task_id].issue_text(settings.root),
    )
    out = Path(args.out or settings.lessons_path)
    save_lessons(out, lessons)
    meta = {"model": model, "runs": len(runs), "lessons": len(lessons), "cost_usd": round(cost, 6)}
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{len(lessons)} lessons from {len(runs)} runs -> {out} (model {model}, cost ${cost:.4f})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="margin")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one task with one arm")
    run.add_argument("--task", required=True)
    run.add_argument("--arm", required=True, choices=["A", "B", "C", "D", "E"])
    run.add_argument("--tasks-file", default=None)
    run.add_argument("--run-id", default=None)
    run.add_argument("--version", default="v1")
    run.add_argument("--gate", action="store_true", help="screen the issue with the TypeSafe intake gate first")
    run.add_argument("--variant", default=None, help="run an intake variant of this task (needs --version demo-*)")
    run.set_defaults(func=cmd_run)

    intake = sub.add_parser("intake", help="screen one issue with the intake gate and print the verdict")
    intake.add_argument("--task", required=True)
    intake.add_argument("--variant", default=None)
    intake.add_argument("--tasks-file", default=None)
    intake.set_defaults(func=cmd_intake)

    intake_eval = sub.add_parser("intake-eval", help="score the intake gate on clean issues and variants")
    intake_eval.add_argument("--split", required=True, choices=["calibration", "evaluation"])
    intake_eval.add_argument("--tasks-file", default=None)
    intake_eval.set_defaults(func=cmd_intake_eval)

    tasks = sub.add_parser("tasks", help="inspect and validate the benchmark tasks")
    tasks_sub = tasks.add_subparsers(dest="tasks_command", required=True)
    validate = tasks_sub.add_parser("validate", help="check tasks are usable")
    validate.add_argument("--ids", nargs="*", default=None)
    validate.add_argument("--tasks-file", default=None)
    validate.add_argument("--max-source-files", type=int, default=3, help="curation limit on files the fix touches (default 3)")
    validate.add_argument("--max-seconds", type=float, default=60.0, help="curation limit on the baseline suite run (default 60)")
    validate.set_defaults(func=cmd_tasks_validate)
    bench = sub.add_parser("bench", help="run one arm over many tasks")
    bench.add_argument("--arm", required=True, choices=["A", "B", "C", "D", "E"])
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
    lessons = sub.add_parser("lessons", help="build arm D's lessons from the recorded runs")
    lessons_sub = lessons.add_subparsers(dest="lessons_command", required=True)
    build = lessons_sub.add_parser("build", help="post-mortems of recorded runs into bench/lessons.jsonl (model calls)")
    build.add_argument("--model", default=None, help="model for the post-mortems (default: the coach model)")
    build.add_argument("--out", default=None)
    build.add_argument("--tasks-file", default=None)
    build.set_defaults(func=cmd_lessons_build)
    replays = sub.add_parser("snapshot-replays", help="build docs/evidence/replays.json from the run event logs")
    replays.add_argument("--ledger", default=None)
    replays.add_argument("--flat", default=None)
    replays.add_argument("--runs-dir", default=None)
    replays.add_argument("--layout", default=None, help="bench/report.toml: which version of each arm is its headline")
    replays.add_argument("--out", default=None)
    replays.set_defaults(func=cmd_snapshot_replays)
    console = sub.add_parser("console", help="regenerate docs/console.html from the committed ledger and replays")
    console.add_argument("--ledger", default=None)
    console.add_argument("--flat", default=None)
    console.add_argument("--replays", default=None)
    console.add_argument("--links", default=None)
    console.add_argument("--layout", default=None, help="bench/report.toml: which version of each arm is its headline")
    console.add_argument("--tasks-file", default=None, help="manifest with the repo, issue link and issue file per task")
    console.add_argument("--out", default=None)
    console.add_argument("--check", action="store_true", help="fail if the page is out of date")
    console.set_defaults(func=cmd_console)
    guide = sub.add_parser("guide", help="regenerate docs/guide.html, the illustrated tour of how a job works")
    guide.add_argument("--ledger", default=None)
    guide.add_argument("--flat", default=None)
    guide.add_argument("--replays", default=None)
    guide.add_argument("--layout", default=None, help="bench/report.toml: which version of each arm is its headline")
    guide.add_argument("--tasks-file", default=None, help="manifest with the repo, issue link and issue file per task")
    guide.add_argument("--out", default=None)
    guide.add_argument("--console-href", default="console.html", help="where the console page is, relative to the guide")
    guide.add_argument("--guide-href", default="guide.html", help="where the guide page is, relative to itself")
    guide.add_argument("--repo-url", default="https://github.com/JemIIahh/margin")
    guide.add_argument("--check", action="store_true", help="fail if the page is out of date")
    guide.set_defaults(func=cmd_guide)
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
