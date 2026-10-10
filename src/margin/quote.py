"""Pre-run cost quote learned from past runs.

Prediction: the median cost of the K nearest past runs (standardised log features), or the median of
all of them when fewer than COLD_START_MIN exist. Spread: the 90th percentile of leave-one-out
|ln(actual / predicted)|. The band is [p50 e^-q, p50 e^+q]; its upper bound is what the spec calls p90.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from margin.context import is_source

EPS = 1e-6
K = 3
COLD_START_MIN = 5
DEFAULT_Q = math.log(2.0)  # a x2 band when there is too little data to estimate the spread
MIN_Q = 0.05               # never a zero-width band


@dataclass(frozen=True)
class Features:
    issue_tokens: int
    impact_files: int
    repo_loc: int
    baseline_seconds: float

    def vector(self) -> list[float]:
        return [
            math.log1p(self.issue_tokens), math.log1p(self.impact_files),
            math.log1p(self.repo_loc), math.log1p(self.baseline_seconds),
        ]

    def to_dict(self) -> dict:
        return {
            "issue_tokens": self.issue_tokens, "impact_files": self.impact_files,
            "repo_loc": self.repo_loc, "baseline_seconds": self.baseline_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Features:
        return cls(int(d["issue_tokens"]), int(d["impact_files"]), int(d["repo_loc"]), float(d["baseline_seconds"]))


@dataclass(frozen=True)
class Quote:
    p50: float
    lo: float
    hi: float

    def price(self, markup: float) -> float:
        return self.hi * (1 + markup)


class Quoter:
    def __init__(self, rows: Sequence[tuple[Features, float]], *, prior_cost: float = 1.0):
        self.rows = [(f, max(cost, EPS)) for f, cost in rows]
        self.prior_cost = prior_cost
        self._sd = self._spreads()
        self.q = self._spread()

    def _spreads(self) -> list[float]:
        if not self.rows:
            return [1.0] * 4
        columns = list(zip(*(f.vector() for f, _ in self.rows)))
        out = []
        for col in columns:
            mean = sum(col) / len(col)
            out.append((sum((x - mean) ** 2 for x in col) / len(col)) ** 0.5 or 1.0)
        return out

    def _distance(self, a: list[float], b: list[float]) -> float:
        return sum(((x - y) / s) ** 2 for x, y, s in zip(a, b, self._sd, strict=True)) ** 0.5

    def _predict(self, features: Features, exclude: int | None = None) -> float:
        vector = features.vector()
        pool = [
            (self._distance(vector, f.vector()), i, cost)
            for i, (f, cost) in enumerate(self.rows)
            if i != exclude
        ]
        if not pool:
            return self.prior_cost
        costs = [cost for _, _, cost in sorted(pool)]
        if len(pool) < COLD_START_MIN:
            return statistics.median(costs)
        return statistics.median(costs[:K])

    def _spread(self) -> float:
        if len(self.rows) < 2:
            return DEFAULT_Q
        residuals = sorted(
            abs(math.log(cost / self._predict(f, exclude=i))) for i, (f, cost) in enumerate(self.rows)
        )
        index = max(0, math.ceil(0.9 * len(residuals)) - 1)
        return max(residuals[index], MIN_Q)

    def quote(self, features: Features) -> Quote:
        p50 = self._predict(features)
        return Quote(p50, p50 * math.exp(-self.q), p50 * math.exp(self.q))


@dataclass(frozen=True)
class LooResult:
    task_id: str
    actual: float
    quote: Quote
    inside: bool
    abs_log_error: float


def evaluate_loo(rows: Sequence[tuple[str, Features, float]], prior_cost: float = 1.0) -> list[LooResult]:
    """Quote every task using a Quoter fit only on the other tasks, so coverage is out of sample."""
    results = []
    for i, (task_id, features, actual) in enumerate(rows):
        others = [(f, cost) for j, (_, f, cost) in enumerate(rows) if j != i]
        quote = Quoter(others, prior_cost=prior_cost).quote(features)
        results.append(
            LooResult(
                task_id, actual, quote, quote.lo <= actual <= quote.hi,
                abs(math.log(max(actual, EPS) / max(quote.p50, EPS))),
            )
        )
    return results


def count_python_loc(root: Path) -> int:
    root = Path(root)
    total = 0
    for path in root.rglob("*.py"):
        if is_source(path, root):
            with path.open(encoding="utf-8", errors="replace") as handle:
                total += sum(1 for _ in handle)
    return total


def extract_features(issue: str, root: Path, baseline_seconds: float, graph: Any) -> Features:
    return Features(
        issue_tokens=max(1, len(issue) // 4),
        impact_files=graph.impact_size(issue),
        repo_loc=count_python_loc(root),
        baseline_seconds=baseline_seconds,
    )


def training_rows(ledger: Any, exclude: str | None = None) -> list[tuple[Features, float]]:
    """Arm B rows the quoter learns from: unconstrained, graph-scoped runs, minus the task being quoted."""
    return [
        (Features.from_dict(row.features), row.cost_usd)
        for task_id, row in ledger.latest("B").items()
        if task_id != exclude and row.features
    ]
