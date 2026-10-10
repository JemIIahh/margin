"""Metrics and tables. Every published number is computed here from the ledger."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from margin.ledger import RunRecord, settle


def calibrate_flat_price(rows_a: dict[str, RunRecord], markup: float) -> dict:
    calibration = [r for r in rows_a.values() if r.split == "calibration"]
    if not calibration:
        raise ValueError("no arm A calibration runs in the ledger")
    mean_cost = sum(r.cost_usd for r in calibration) / len(calibration)
    return {
        "flat_price_usd": round(mean_cost * (1 + markup), 6),
        "mean_cost_usd": round(mean_cost, 6),
        "n": len(calibration),
        "markup": markup,
    }


def apply_flat_price(rows: Iterable[RunRecord], flat_price: float) -> list[RunRecord]:
    out = []
    for row in rows:
        if row.arm in ("A", "B"):
            revenue, margin = settle(flat_price, row.solved, row.cost_usd)
            row = replace(row, price_usd=flat_price, revenue_usd=revenue, margin_usd=margin)
        out.append(row)
    return out


def summarize(rows: list[RunRecord]) -> dict:
    n = len(rows)
    solved = [r for r in rows if r.solved]
    revenue = sum(r.revenue_usd for r in rows)
    cost = sum(r.cost_usd for r in rows)
    return {
        "n": n,
        "solve_rate": len(solved) / n if n else 0.0,
        "profitable_share": sum(1 for r in rows if r.margin_usd > 0) / n if n else 0.0,
        "gross_margin": (revenue - cost) / revenue if revenue > 0 else None,
        "wasted_spend_usd": sum(r.cost_usd for r in rows if not r.solved),
        "tokens_per_solved": sum(r.tokens_total for r in solved) / len(solved) if solved else None,
        "cost_total_usd": cost,
        "revenue_total_usd": revenue,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.2f}"


def compare_table(summaries: dict[str, dict]) -> str:
    lines = [
        "| Arm | Runs | Solve rate | Profitable jobs | Gross margin | Wasted spend | Tokens / solved fix |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in sorted(summaries):
        s = summaries[arm]
        tokens = "n/a" if s["tokens_per_solved"] is None else f"{s['tokens_per_solved']:,.0f}"
        lines.append(
            f"| {arm} | {s['n']} | {_pct(s['solve_rate'])} | {_pct(s['profitable_share'])} | "
            f"{_pct(s['gross_margin'])} | {_money(s['wasted_spend_usd'])} | {tokens} |"
        )
    return "\n".join(lines)
