"""The agent's tools. Arms A, B and C share one executor; only the backends differ."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any

from margin.context import GraphError, grep_search
from margin.sandbox import EditError, PathEscape, Sandbox, SuiteTimeout, is_test_path
from margin.telemetry import record_failure, trace
from margin.verify import Baseline, NoJunit, new_failures, run_suite

MAX_OUTPUT_CHARS = 12_000


@dataclass(frozen=True)
class ToolOutput:
    text: str
    is_error: bool = False


class ProgressTracker:
    """Counts progress events the governor can see: a first applied edit, or fewer failing targets.

    `initial_failing` is the number of target tests (validation guarantees they all fail at the base commit), so the
    first test run is compared with "everything failing". Once the targets pass, every further green run still counts:
    a finished fix must not be mistaken for a stalled one.
    """

    def __init__(self, initial_failing: int | None = None) -> None:
        self.events = 0
        self.best_failing: int | None = initial_failing
        self.patch_applied = False

    def note_edit(self) -> None:
        if not self.patch_applied:
            self.patch_applied = True
            self.events += 1

    def note_tests(self, failing_targets: int) -> None:
        if self.best_failing is None:
            self.best_failing = failing_targets  # without a known starting count the first measurement is a baseline
        elif failing_targets < self.best_failing:
            self.best_failing = failing_targets
            self.events += 1
        elif failing_targets == 0:
            self.events += 1

    def to_dict(self) -> dict:
        return {"events": self.events, "best_failing": self.best_failing, "patch_applied": self.patch_applied}

    def restore(self, d: dict) -> None:
        self.events = d.get("events", 0)
        self.best_failing = d.get("best_failing")
        self.patch_applied = d.get("patch_applied", False)


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object", "properties": properties, "required": required, "additionalProperties": False,
        },
    }


_STR = {"type": "string"}
SCHEMAS = {
    "read_file": _schema(
        "read_file",
        "Read a UTF-8 text file in the repository with numbered lines; optional 1-based inclusive range.",
        {"path": _STR, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
        ["path"],
    ),
    "search_code": _schema(
        "search_code", "Find code relevant to a plain-language query or an identifier.", {"query": _STR}, ["query"]
    ),
    "graph_impact": _schema(
        "graph_impact",
        "Show callers, callees and co-changing files for a symbol before changing it.",
        {"symbol": _STR},
        ["symbol"],
    ),
    "edit_file": _schema(
        "edit_file",
        "Replace exactly one occurrence of `old` with `new` in a file. `old` must match exactly once.",
        {"path": _STR, "old": _STR, "new": _STR},
        ["path", "old", "new"],
    ),
    "write_file": _schema(
        "write_file", "Create or overwrite a file with the given content.", {"path": _STR, "content": _STR}, ["path", "content"]
    ),
    "run_tests": _schema("run_tests", "Run the tests and report the results.", {}, []),
    "git_diff": _schema("git_diff", "Show the current patch against the starting commit.", {}, []),
}
_BASE = ["read_file", "search_code", "edit_file", "write_file", "run_tests", "git_diff"]
ARM_TOOLS = {"A": list(_BASE), "B": [*_BASE, "graph_impact"], "C": [*_BASE, "graph_impact"]}


def tool_schemas(arm: str) -> list[dict]:
    return [SCHEMAS[name] for name in ARM_TOOLS[arm]]


def _clip(out: ToolOutput) -> ToolOutput:
    if len(out.text) <= MAX_OUTPUT_CHARS:
        return out
    return ToolOutput(out.text[:MAX_OUTPUT_CHARS] + "\n[output truncated]", out.is_error)


def _check_args(name: str, args: dict) -> str | None:
    """Validate a tool call against its own schema, so the model gets a clear message, not a Python TypeError."""
    props, required = SCHEMAS[name]["input_schema"]["properties"], SCHEMAS[name]["input_schema"]["required"]
    problems = []
    unexpected = sorted(set(args) - set(props))
    if unexpected:
        problems.append("unexpected " + ", ".join(unexpected))
    missing = [k for k in required if k not in args]
    if missing:
        problems.append("missing " + ", ".join(missing))
    for key, value in args.items():
        kind = props.get(key, {}).get("type")
        if kind == "string" and not isinstance(value, str):
            problems.append(f"{key} must be a string")
        elif kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            problems.append(f"{key} must be an integer")
    if not problems:
        return None
    return f"error: invalid arguments for {name}: {'; '.join(problems)}. It takes: {', '.join(props) or 'no arguments'}"


class ToolExecutor:
    def __init__(
        self,
        *,
        sandbox: Sandbox,
        arm: str,
        baseline: Baseline,
        target_nodeids: list[str],
        target_junit_ids: list[str],
        test_args: list[str],
        protected_paths: list[str],
        issue_text: str,
        graph: Any = None,
        faults: Any = None,
        state: Any = None,
    ):
        self.sandbox = sandbox
        self.arm = arm
        self.baseline = baseline
        self.target_nodeids = list(target_nodeids)
        self.target_junit_ids = list(target_junit_ids)
        self.test_args = list(test_args)
        self.protected = {sandbox.relpath(p) for p in protected_paths}
        self.issue_text = issue_text
        self.graph = graph
        self.faults = faults
        self.state = state
        self.progress = ProgressTracker(initial_failing=len(self.target_junit_ids))
        self.last_tests_text = ""
        self._test_runs = 0

    # --- dispatch ----------------------------------------------------------------
    def execute(self, name: str, args: Any) -> ToolOutput:
        if self.state is not None:
            self.state.log("tool_call", name=name)
        with trace(name, kind="TOOL", **{"margin.tool": name}):
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None or name not in ARM_TOOLS[self.arm]:
                return ToolOutput(f"error: unknown tool {name!r}", True)
            if not isinstance(args, dict):
                return ToolOutput("error: tool input must be a JSON object", True)
            if (problem := _check_args(name, args)) is not None:
                return ToolOutput(problem, True)
            try:
                return _clip(handler(**args))
            except (
                PathEscape, EditError, GraphError, SuiteTimeout, NoJunit,
                KeyError, TypeError, ValueError, OSError,
            ) as exc:
                return ToolOutput(self._scrub(f"error: {type(exc).__name__}: {exc}"), True)
            except subprocess.CalledProcessError as exc:  # a git command failed inside a tool: the agent can see it
                return ToolOutput(
                    self._scrub(f"error: {' '.join(map(str, exc.cmd[:3]))} failed: {(exc.stderr or '')[:300]}"), True
                )

    def _scrub(self, text: str) -> str:
        """Show repository-relative paths only: the absolute worktree path names the user's home directory."""
        return text.replace(str(self.sandbox.root), ".")

    def digest(self) -> dict:
        return {"diff": self.sandbox.git_diff()[:20_000], "tests": self.last_tests_text or "(tests not run yet)"}

    def _recovery(self, kind: str, detail: str) -> None:
        if self.state is not None:
            self.state.log("recovery", kind=kind, detail=detail)
        record_failure(f"failed:{kind}", detail)
        with trace(f"recovery:{kind}", kind="GUARDRAIL", **{"margin.recovery": kind, "margin.detail": detail}):
            pass

    def _guard_write(self, path: str) -> None:
        rel = self.sandbox.relpath(path)
        if rel in self.protected or is_test_path(rel):
            raise PathEscape(f"{path} is a protected test file or test infrastructure; fix the code, not the tests")

    # --- tools -------------------------------------------------------------------
    def _tool_read_file(self, path, start_line=None, end_line=None) -> ToolOutput:
        # leave room for the sandbox's own 'use start_line/end_line' hint under the clip limit
        return ToolOutput(self.sandbox.read_file(path, start_line, end_line, max_chars=MAX_OUTPUT_CHARS - 100))

    def _tool_search_code(self, query) -> ToolOutput:
        if self.graph is not None:
            return ToolOutput(self.graph.search(query))
        return ToolOutput(grep_search(self.sandbox.root, query))

    def _tool_graph_impact(self, symbol) -> ToolOutput:
        if self.graph is None:
            return ToolOutput("error: the code graph is not available for this run", True)
        return ToolOutput(self.graph.impact(symbol))

    def _tool_edit_file(self, path, old, new) -> ToolOutput:
        self._guard_write(path)
        self.sandbox.edit_file(path, old, new)
        self.progress.note_edit()
        return ToolOutput(f"edited {path}")

    def _tool_write_file(self, path, content) -> ToolOutput:
        self._guard_write(path)
        self.sandbox.write_file(path, content)
        self.progress.note_edit()
        return ToolOutput(f"wrote {path}")

    def _tool_git_diff(self) -> ToolOutput:
        return ToolOutput(self.sandbox.git_diff() or "(no changes)")

    def _tool_run_tests(self) -> ToolOutput:
        full = self.arm in ("B", "C")
        args = list(self.test_args) if full else list(self.target_nodeids)
        junit = self.sandbox.home / f"junit-{self._test_runs}.xml"
        self._test_runs += 1
        try:
            if self.faults is not None:
                self.faults.before_tests()
            run = run_suite(self.sandbox, args, junit)
        except SuiteTimeout:
            self._recovery("tool_timeout", "tests timed out; retrying with the target tests only")
            run = run_suite(self.sandbox, list(self.target_nodeids), junit)
            full = False  # a target-only run cannot say anything about the rest of the suite
        if self.faults is not None:
            run = self.faults.corrupt_run(run, protect=set(self.target_junit_ids))
        failing_targets = [t for t in self.target_junit_ids if t not in run.passed]
        new = new_failures(self.baseline, run, self.target_junit_ids) if full else []
        if new:  # suspicious: re-run once and keep only the regressions that persist
            again = run_suite(self.sandbox, args, junit)
            still = set(new_failures(self.baseline, again, self.target_junit_ids))
            persistent = [n for n in new if n in still]
            if len(persistent) != len(new):
                self._recovery("flaky_rerun", f"{len(new) - len(persistent)} spurious failure(s) cleared on re-run")
            new = persistent
        self.progress.note_tests(len(failing_targets))
        lines = [f"Target tests: {len(failing_targets)} failing of {len(self.target_junit_ids)}"]
        lines += [f"  FAIL {t}" for t in failing_targets]
        if full:
            lines.append("New failures vs baseline: " + ("none" if not new else ""))
            lines += [f"  FAIL {t}" for t in new[:20]]
            lines.append(
                f"Full suite: {len(run.passed)} passed, {len(run.failed)} failed "
                f"({len(self.baseline.failing)} already failing at the base commit)"
            )
        self.last_tests_text = "\n".join(lines)
        return ToolOutput(self.last_tests_text)
