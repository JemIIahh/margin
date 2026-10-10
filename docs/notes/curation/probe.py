# Curation script kept for provenance. It was run from a session scratch directory, so its HARDCODED PATHS ARE
# SPECIFIC TO THAT SESSION; adjust HERE/H/ROOT before reusing. See docs/notes/task-curation.md.
"""Stage 2: probe mined candidates with the project's own machinery. Read-only against GitHub (clones only).

Usage: uv run python probe.py <repo-name> [max_candidates]   (run from /Users/ram/Desktop/margin)
Writes probe/<name>.jsonl, one line per candidate.
"""
import json
import subprocess
import sys
from pathlib import Path

from margin.bench.tasks import Task, prepare_run, remove_worktree
from margin.config import Settings
from margin.verify import final_verdict, run_suite

HERE = Path("/private/tmp/claude-501/-Users-ram-Desktop-margin/428afbc1-7d7e-4b07-bb5a-0e6802f57e73/scratchpad")
MINE, PROBE, CACHE = HERE / "mine", HERE / "probe", HERE / "probe-cache"
PROBE.mkdir(exist_ok=True)

# name: (github slug, src prefixes, test prefixes, pythonpath, deps, since)
CFG = {
    "more-itertools": ("more-itertools/more-itertools", ["more_itertools/"], ["tests/"], ["."], ["pytest"], "2021-01-01"),
    "boltons": ("mahmoud/boltons", ["boltons/"], ["tests/"], ["."], ["pytest"], "2021-01-01"),
    "cachetools": ("tkem/cachetools", ["src/cachetools/"], ["tests/"], ["src"], ["pytest"], "2021-01-01"),
    "python-tabulate": ("astanin/python-tabulate", ["tabulate/", "tabulate.py"], ["test/"], ["."], ["pytest"], "2021-01-01"),
    "humanize": ("python-humanize/humanize", ["src/humanize/"], ["tests/"], ["src"], ["pytest", "freezegun"], "2021-01-01"),
    "pyjwt": ("jpadilla/pyjwt", ["jwt/"], ["tests/"], ["."], ["pytest"], "2021-01-01"),
    "marshmallow": ("marshmallow-code/marshmallow", ["src/marshmallow/"], ["tests/"], ["src"], ["pytest", "simplejson"], "2021-01-01"),
    "toolz": ("pytoolz/toolz", ["toolz/"], ["toolz/tests/"], ["."], ["pytest"], "2019-01-01"),
    "python-sortedcontainers": ("grantjenks/python-sortedcontainers", ["src/sortedcontainers/"], ["tests/"], ["src"], ["pytest"], "2019-01-01"),
    "pyparsing": ("pyparsing/pyparsing", ["pyparsing/"], ["tests/"], ["."], ["pytest"], "2021-01-01"),
    "sqlparse": ("andialbrecht/sqlparse", ["sqlparse/"], ["tests/"], ["."], ["pytest"], "2021-01-01"),
    "tomlkit": ("python-poetry/tomlkit", ["tomlkit/"], ["tests/"], ["."], ["pytest", "pyyaml"], "2021-01-01"),
    "packaging": ("pypa/packaging", ["src/packaging/"], ["tests/"], ["src"], ["pytest", "pretend", "hypothesis", "tomli_w"], "2022-01-01"),
    "mistune": ("lepture/mistune", ["src/mistune/"], ["tests/"], ["src"], ["pytest"], "2021-01-01"),
    "tomli": ("hukkin/tomli", ["src/tomli/"], ["tests/"], ["src"], ["pytest"], "2021-01-01"),
    "jmespath.py": ("jmespath/jmespath.py", ["jmespath/"], ["tests/"], ["."], ["pytest"], "2015-01-01"),
}


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def junit_to_nodeid(work: Path, junit_id: str) -> str | None:
    classname, _, name = junit_id.partition("::")
    parts = classname.split(".")
    for i in range(len(parts), 0, -1):
        rel = "/".join(parts[:i]) + ".py"
        if (work / rel).exists():
            return "::".join([rel, *parts[i:], name])
    return None


def ensure_venv(name: str, deps: list[str]) -> Path:
    venv = HERE / "probe-venvs" / name
    py = venv / "bin" / "python"
    if not py.exists():
        venv.parent.mkdir(exist_ok=True)
        sh("uv", "venv", "--python", "3.12", "--quiet", str(venv))
        sh("uv", "pip", "install", "--quiet", "--python", str(py), *deps)
    return py


def main(name: str, limit: int) -> None:
    slug, src_pre, test_pre, pythonpath, deps, since = CFG[name]
    py = ensure_venv(name, deps)
    shared = CACHE / "shared" / f"{name}.git"
    if not shared.exists():
        shared.parent.mkdir(parents=True, exist_ok=True)
        sh("git", "clone", "--bare", "--quiet", f"https://github.com/{slug}", str(shared))
    cands = json.loads((MINE / f"{name}.json").read_text())
    cands = [
        c for c in cands
        if c["date"] >= since
        and all(f.startswith(tuple(src_pre)) or not f.endswith(".py") for f in c["src"])
        and any(f.startswith(tuple(src_pre)) for f in c["src"])
        and all(f.startswith(tuple(test_pre)) for f in c["tests"])
    ][:limit]
    settings = Settings(cache_dir=CACHE, runs_dir=HERE / "probe-runs", ledger_path=HERE / "probe-runs" / "l.jsonl")
    out = PROBE / f"{name}.jsonl"
    done = {json.loads(line)["sha"] for line in out.read_text().splitlines()} if out.exists() else set()
    for c in cands:
        if c["sha"] in done:
            continue
        tid = f"p-{name}-{c['sha'][:7]}"
        (CACHE / "repos").mkdir(parents=True, exist_ok=True)
        link = CACHE / "repos" / f"{tid}.git"
        if not link.exists():
            link.symlink_to(shared)
        task = Task(
            id=tid, split="evaluation", repo=f"https://github.com/{slug}", base_commit=c["base"], fix_commit=c["sha"],
            issue_url="", issue_file="", target_tests=[], test_files=c["tests"], test_args=c["tests"],
            deps=deps, pythonpath=pythonpath,
        )
        rec = {"sha": c["sha"], "base": c["base"], "date": c["date"], "subject": c["subject"], "tests": c["tests"], "src": c["src"], "ok": False}
        run_dir = HERE / "probe-runs" / tid
        try:
            prep = prepare_run(task, run_dir, settings, venv_python=py, use_baseline_cache=False)
            fix = sh("git", "-C", str(shared), "diff", "--binary", c["base"], c["sha"], "--", ".", *[f":(exclude){t}" for t in c["tests"]])
            (run_dir / "fix.patch").write_text(fix)
            sh("git", "-C", str(prep.sandbox.root), "apply", str(run_dir / "fix.patch"))
            after = run_suite(prep.sandbox, c["tests"], run_dir / "after.xml")
            targets = sorted(prep.baseline.failing & after.passed)
            nodeids = [n for n in (junit_to_nodeid(prep.sandbox.root, t) for t in targets) if n]
            new_fail = sorted(after.failed - prep.baseline.failing - prep.baseline.flaky)
            rec.update(ok=bool(nodeids) and not new_fail, targets=nodeids, new_failures=new_fail[:5],
                       baseline_failing=len(prep.baseline.failing), seconds=round(prep.baseline_seconds, 2))
        except Exception as exc:  # noqa: BLE001 - probe records why a candidate is unusable
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        finally:
            try:
                remove_worktree(shared, run_dir / "work")
            except Exception:  # noqa: BLE001
                pass
        with out.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(name, c["sha"][:7], "OK" if rec["ok"] else "no", rec.get("error", "")[:90], flush=True)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 12)
