"""Task manifest, repo preparation (bare clone, worktree, venv) and the cached baseline snapshot."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from margin.config import Settings
from margin.procenv import setup_env
from margin.sandbox import DEFAULT_EXCLUDES, Sandbox
from margin.verify import Baseline, final_verdict, make_baseline, nodeid_to_junit, run_suite


@dataclass(frozen=True)
class Task:
    id: str
    split: str
    repo: str
    base_commit: str
    fix_commit: str
    issue_url: str
    issue_file: str
    target_tests: list
    test_files: list
    test_args: list = field(default_factory=lambda: ["tests"])
    deps: list = field(default_factory=lambda: ["pytest"])
    pythonpath: list = field(default_factory=lambda: ["."])

    def issue_text(self, root: Path) -> str:
        return (Path(root) / self.issue_file).read_text(encoding="utf-8")[:20_000]

    @property
    def target_junit_ids(self) -> list[str]:
        return [nodeid_to_junit(n) for n in self.target_tests]


def load_tasks(path: Path) -> list[Task]:
    data = tomllib.loads(Path(path).read_text())
    return [Task(**t) for t in data.get("task", [])]


def find_task(tasks: list[Task], task_id: str) -> Task:
    for task in tasks:
        if task.id == task_id:
            return task
    raise KeyError(f"no task with id {task_id!r}")


@dataclass
class Prepared:
    sandbox: Sandbox
    baseline: Baseline
    baseline_seconds: float
    bare: Path


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, env=setup_env())


def ensure_bare_clone(task: Task, cache_dir: Path) -> Path:
    bare = Path(cache_dir) / "repos" / f"{task.id}.git"
    if not bare.exists():
        bare.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--bare", "--quiet", task.repo, str(bare)])
    return bare


def ensure_venv(task: Task, cache_dir: Path) -> Path:
    venv = Path(cache_dir) / "venvs" / task.id
    python = venv / "bin" / "python"
    if not python.exists():
        venv.parent.mkdir(parents=True, exist_ok=True)
        _run(["uv", "venv", "--python", "3.12", "--quiet", str(venv)])
        _run(["uv", "pip", "install", "--quiet", "--python", str(python), *task.deps])
    return python


def make_worktree(bare: Path, run_dir: Path, base_commit: str) -> tuple[Path, bool]:
    work = Path(run_dir) / "work"
    if work.exists():
        return work, False
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    _run(["git", "-C", str(bare), "worktree", "add", "--detach", "--quiet", str(work), base_commit])
    return work, True


def apply_test_patch(bare: Path, work: Path, task: Task, run_dir: Path) -> None:
    patch = _run(
        ["git", "-C", str(bare), "diff", "--binary", task.base_commit, task.fix_commit, "--", *task.test_files]
    ).stdout
    if not patch.strip():
        raise ValueError(f"{task.id}: the fix commit changes none of test_files {task.test_files}")
    patch_file = Path(run_dir) / "test.patch"
    patch_file.write_text(patch)
    _run(["git", "-C", str(work), "apply", str(patch_file)])
    _run(["git", "-C", str(work), "add", "-A"])
    _run(
        ["git", "-C", str(work), "-c", "user.name=margin", "-c", "user.email=margin@local",
         "commit", "--quiet", "-m", "apply test patch"]
    )


def snapshot_baseline(
    task: Task, sandbox: Sandbox, cache_dir: Path, run_dir: Path, *, use_cache: bool = True
) -> tuple[Baseline, float]:
    cache = Path(cache_dir) / "baselines" / f"{task.id}.json"
    if use_cache and cache.exists():
        data = json.loads(cache.read_text())
        return Baseline.from_dict(data["baseline"]), data["seconds"]
    started = time.time()
    first = run_suite(sandbox, task.test_args, Path(run_dir) / "baseline-1.xml")
    second = run_suite(sandbox, task.test_args, Path(run_dir) / "baseline-2.xml")
    seconds = max((time.time() - started) / 2, 0.001)
    baseline = make_baseline(first, second)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"baseline": baseline.to_dict(), "seconds": seconds}))
    return baseline, seconds


def prepare_run(
    task: Task, run_dir: Path, settings: Settings, *, venv_python: Path | None = None, use_baseline_cache: bool = True
) -> Prepared:
    bare = ensure_bare_clone(task, settings.cache_dir)
    work, created = make_worktree(bare, run_dir, task.base_commit)
    if created:
        apply_test_patch(bare, work, task, run_dir)
    python = venv_python or ensure_venv(task, settings.cache_dir)
    sandbox = Sandbox(work, python, task.pythonpath, Path(run_dir) / "home", settings.test_timeout_s)
    sandbox.exclude(DEFAULT_EXCLUDES)
    baseline, seconds = snapshot_baseline(task, sandbox, settings.cache_dir, run_dir, use_cache=use_baseline_cache)
    return Prepared(sandbox, baseline, seconds, bare)


def remove_worktree(bare: Path, work: Path) -> None:
    subprocess.run(
        ["git", "-C", str(bare), "worktree", "remove", "--force", str(work)],
        capture_output=True, check=False, env=setup_env(),
    )
    shutil.rmtree(work, ignore_errors=True)
    subprocess.run(["git", "-C", str(bare), "worktree", "prune"], capture_output=True, check=False, env=setup_env())


def validate_task(
    task: Task,
    settings: Settings,
    *,
    venv_python: Path | None = None,
    max_seconds: float = 60,
    max_source_files: int = 3,
) -> dict:
    """Prove a task is usable: its tests fail before the real fix, pass after it, and it is small and fast."""
    run_dir = Path(settings.cache_dir) / "validation" / task.id
    bare = ensure_bare_clone(task, settings.cache_dir)
    remove_worktree(bare, run_dir / "work")
    shutil.rmtree(run_dir, ignore_errors=True)

    problems: list[str] = []
    prep = prepare_run(task, run_dir, settings, venv_python=venv_python, use_baseline_cache=False)
    missing = [t for t in task.target_junit_ids if t not in prep.baseline.failing]
    if missing:
        problems.append(f"target tests do not fail before the fix: {missing}")

    changed = _run(["git", "-C", str(bare), "diff", "--name-only", task.base_commit, task.fix_commit]).stdout.split()
    source_files = [f for f in changed if f not in task.test_files]
    if not source_files:
        problems.append("the fix commit changes no source files")
    if len(source_files) > max_source_files:
        problems.append(f"the fix touches {len(source_files)} source files (limit {max_source_files})")
    if prep.baseline_seconds > max_seconds:
        problems.append(f"the suite takes {prep.baseline_seconds:.1f} seconds (limit {max_seconds})")

    excludes = [f":(exclude){f}" for f in task.test_files]
    fix = _run(
        ["git", "-C", str(bare), "diff", "--binary", task.base_commit, task.fix_commit, "--", ".", *excludes]
    ).stdout
    fix_file = run_dir / "fix.patch"
    fix_file.write_text(fix)
    _run(["git", "-C", str(prep.sandbox.root), "apply", str(fix_file)])
    verdict = final_verdict(prep.sandbox, prep.baseline, task.target_junit_ids, task.test_args, run_dir / "after.xml")
    if not verdict.solved:
        problems.append(f"the real fix does not satisfy the verifier: {verdict.reason}")

    result = {
        "id": task.id,
        "ok": not problems,
        "problems": problems,
        "baseline_seconds": round(prep.baseline_seconds, 2),
        "source_files": source_files,
        "target_failing_before": len(prep.baseline.failing),
    }
    out = Path(settings.cache_dir) / "validation" / f"{task.id}.json"
    out.write_text(json.dumps(result, indent=2))
    remove_worktree(bare, prep.sandbox.root)
    return result
