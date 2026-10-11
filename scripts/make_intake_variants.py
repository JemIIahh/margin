"""Generate bench/intake/*.md and bench/intake/variants.toml from bench/tasks.toml.

Deterministic, so re-running it is safe. Calibration variants come from calibration tasks and
evaluation variants from evaluation tasks, so thresholds are never tuned on evaluation data.
"""
from margin.bench.intake_eval import build_variants, write_variants
from margin.bench.tasks import load_tasks
from margin.config import ROOT


def main() -> None:
    tasks = load_tasks(ROOT / "bench" / "tasks.toml")
    items = build_variants(tasks, lambda task: task.issue_text(ROOT))
    print(f"wrote {write_variants(ROOT, items)} ({len(items)} variants)")


if __name__ == "__main__":
    main()
