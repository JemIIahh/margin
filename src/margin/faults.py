"""Fault injection. Task 17 implements the injector; the tool executor only needs these hook names."""
from __future__ import annotations

from margin.verify import SuiteRun


class FaultInjector:
    def __init__(self, kind: str | None = None):
        self.kind = kind

    def before_model_call(self) -> None:
        return None

    def before_tests(self) -> None:
        return None

    def corrupt_run(self, run: SuiteRun, protect: frozenset | set = frozenset()) -> SuiteRun:
        return run
