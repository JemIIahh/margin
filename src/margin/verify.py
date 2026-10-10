"""Baseline-aware verification from pytest JUnit output.

A fix counts only if every target test passes and no test that was passing at the base commit
(and is not flaky) now fails. Ids are `classname::name`, as written by pytest's junit writer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# JUnit files are written by third-party test code, so parse them with entity expansion disabled.
from defusedxml import ElementTree as ET

from margin.sandbox import Sandbox, SuiteTimeout


class NoJunit(Exception):
    pass


MESSAGE_CHARS = 600  # enough for pytest's assertion rewrite (expected vs got), small enough to repeat every run


@dataclass(frozen=True)
class SuiteRun:
    passed: frozenset
    failed: frozenset
    messages: dict = field(default_factory=dict, compare=False)  # failed test id -> why, bounded


@dataclass(frozen=True)
class Baseline:
    failing: frozenset
    flaky: frozenset
    passing: frozenset = frozenset()  # passed in both baseline runs; later skipped or missing means it got worse

    def to_dict(self) -> dict:
        return {"failing": sorted(self.failing), "flaky": sorted(self.flaky), "passing": sorted(self.passing)}

    @classmethod
    def from_dict(cls, d: dict) -> Baseline:
        return cls(frozenset(d["failing"]), frozenset(d["flaky"]), frozenset(d.get("passing", [])))


@dataclass(frozen=True)
class Verdict:
    solved: bool
    target_failing: list
    new_failures: list
    reason: str


def nodeid_to_junit(nodeid: str) -> str:
    parts = nodeid.split("::")
    if len(parts) < 2:
        raise ValueError(f"not a pytest node id (needs '::test_name'): {nodeid!r}")
    path = parts[0].removesuffix(".py")
    classname = ".".join([path.replace("/", "."), *parts[1:-1]])
    return f"{classname}::{parts[-1]}"


def parse_junit(path: Path) -> SuiteRun:
    path = Path(path)
    if not path.exists():
        raise NoJunit(f"{path} was not written")
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, ValueError) as exc:  # ValueError covers defusedxml's DefusedXmlException
        raise NoJunit(f"unreadable junit xml: {exc}") from exc
    passed: set[str] = set()
    failed: set[str] = set()
    messages: dict[str, str] = {}
    for case in root.iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        problem = case.find("failure") if case.find("failure") is not None else case.find("error")
        if problem is not None:
            failed.add(test_id)
            messages[test_id] = (problem.get("message") or "").strip()[:MESSAGE_CHARS]
        elif case.find("skipped") is None:
            passed.add(test_id)
    return SuiteRun(frozenset(passed), frozenset(failed), messages)


def run_suite(sandbox: Sandbox, args: list[str], junit_path: Path) -> SuiteRun:
    junit_path = Path(junit_path)
    junit_path.parent.mkdir(parents=True, exist_ok=True)
    if junit_path.exists():
        junit_path.unlink()
    proc = sandbox.run_pytest(args, junit_path)
    try:
        return parse_junit(junit_path)
    except NoJunit as exc:
        tail = (proc.stdout[-400:] + proc.stderr[-400:]).strip()
        raise NoJunit(f"{exc}; pytest exit {proc.returncode}: {tail}") from exc


def make_baseline(run1: SuiteRun, run2: SuiteRun) -> Baseline:
    return Baseline(
        failing=frozenset(run1.failed & run2.failed),
        flaky=frozenset(run1.failed ^ run2.failed),
        passing=frozenset(run1.passed & run2.passed),
    )


def new_failures(baseline: Baseline, run: SuiteRun, target_junit_ids: list[str]) -> list[str]:
    """Tests that got worse: failing now, or passing at the baseline and not passing now.

    The second half matters: a test that was skipped or deleted is neither passed nor failed, so judging only
    `run.failed` would let a patch hide a regression by silencing the test that exposes it.
    """
    targets = set(target_junit_ids)
    allowed = baseline.failing | baseline.flaky | targets
    broke = run.failed - allowed
    vanished = baseline.passing - run.passed - targets
    return sorted(broke | vanished)


def judge(baseline: Baseline, after: SuiteRun, target_junit_ids: list[str]) -> Verdict:
    target_failing = [t for t in target_junit_ids if t not in after.passed]
    worse = new_failures(baseline, after, target_junit_ids)
    if target_failing:
        reason = "target tests still failing: " + ", ".join(target_failing[:5])
    elif worse:
        reason = "new failures vs baseline (failed, skipped or missing): " + ", ".join(worse[:5])
    else:
        reason = "solved"
    return Verdict(not target_failing and not worse, target_failing, worse, reason)


def final_verdict(
    sandbox: Sandbox,
    baseline: Baseline,
    target_junit_ids: list[str],
    test_args: list[str],
    junit_path: Path,
) -> Verdict:
    try:
        after = run_suite(sandbox, test_args, junit_path)
    except SuiteTimeout as exc:
        return Verdict(False, list(target_junit_ids), [], f"final test run timed out: {exc}")
    except NoJunit as exc:
        return Verdict(False, list(target_junit_ids), [], f"final test run produced no results: {exc}")
    return judge(baseline, after, target_junit_ids)
