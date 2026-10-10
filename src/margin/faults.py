"""Deterministic fault injection for the recovery demo. One kind at a time, each firing a fixed number of times."""
from __future__ import annotations

from margin.errors import TransientModelError
from margin.sandbox import SuiteTimeout
from margin.verify import SuiteRun

FAULTS = ("api_overload", "flaky_tests", "tool_timeout")


class FaultInjector:
    def __init__(self, kind: str | None = None, *, overloads: int = 2):
        if kind is not None and kind not in FAULTS:
            raise ValueError(f"unknown fault {kind!r}; choose from {FAULTS}")
        self.kind = kind
        self._overloads_left = overloads if kind == "api_overload" else 0
        self._timeout_pending = kind == "tool_timeout"
        self._flaky_pending = kind == "flaky_tests"

    def before_model_call(self) -> None:
        if self._overloads_left > 0:
            self._overloads_left -= 1
            raise TransientModelError("injected 529: the API is overloaded")

    def before_tests(self) -> None:
        if self._timeout_pending:
            self._timeout_pending = False
            raise SuiteTimeout("injected test-runner timeout")

    def corrupt_run(self, run: SuiteRun, protect: frozenset | set = frozenset()) -> SuiteRun:
        """Report one real, passing, non-target test as failed, once (a spurious failure)."""
        if not self._flaky_pending:
            return run
        candidates = sorted(set(run.passed) - set(protect))
        if not candidates:
            return run
        self._flaky_pending = False
        victim = candidates[0]
        return SuiteRun(run.passed - {victim}, run.failed | {victim})
