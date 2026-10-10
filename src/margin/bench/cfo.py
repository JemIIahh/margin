"""Turn measured ledger numbers into the inputs for the cfo.ai business plan."""
from __future__ import annotations

import math

from margin.bench.report import apply_flat_price
from margin.ledger import Ledger


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def cfo_inputs(ledger: Ledger, flat_price: float) -> dict:
    out: dict[str, dict] = {}
    for arm in ("A", "B", "C"):
        rows = [
            r for r in apply_flat_price(ledger.latest(arm).values(), flat_price) if r.split == "evaluation"
        ]
        if not rows:
            continue
        solved = [r for r in rows if r.solved]
        cost = sum(r.cost_usd for r in rows)
        revenue = sum(r.revenue_usd for r in rows)
        out[arm] = {
            "runs": len(rows),
            "solve_rate": len(solved) / len(rows),
            "cost_per_job_p50": percentile([r.cost_usd for r in rows], 0.5),
            "cost_per_job_p90": percentile([r.cost_usd for r in rows], 0.9),
            "cost_per_verified_fix": cost / len(solved) if solved else None,
            "avg_price": sum(r.price_usd for r in rows) / len(rows),
            "revenue_per_job": revenue / len(rows),
            "gross_margin": (revenue - cost) / revenue if revenue > 0 else None,
        }
    return out


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.2f}"


def render_inputs_table(inputs: dict) -> str:
    lines = [
        "| Arm | Runs | Solve rate | Cost/job p50 | Cost/job p90 | Cost per verified fix | Avg price | Revenue/job | Gross margin |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, s in inputs.items():
        margin = "n/a" if s["gross_margin"] is None else f"{s['gross_margin']:.0%}"
        lines.append(
            f"| {arm} | {s['runs']} | {s['solve_rate']:.0%} | {_money(s['cost_per_job_p50'])} | "
            f"{_money(s['cost_per_job_p90'])} | {_money(s['cost_per_verified_fix'])} | {_money(s['avg_price'])} | "
            f"{_money(s['revenue_per_job'])} | {margin} |"
        )
    return "\n".join(lines)


def render_ari_prompt(inputs: dict) -> str:
    c = inputs.get("C") or next(iter(inputs.values()))
    return (
        "I run Margin, an agent that fixes software issues and charges per verified fix. "
        "Please build a monthly financial model with a base and a growth scenario, covering pricing, "
        "costs, revenue and runway.\n\n"
        "Measured unit economics from a benchmark of real runs:\n"
        f"- Cost to run one job: median {_money(c['cost_per_job_p50'])}, 90th percentile {_money(c['cost_per_job_p90'])} "
        "(mostly model usage).\n"
        f"- The agent verifies a fix on {c['solve_rate']:.0%} of jobs; customers pay only for verified fixes.\n"
        f"- All-in cost per verified fix, including failed attempts: {_money(c['cost_per_verified_fix'])}.\n"
        f"- Current average price per job: {_money(c['avg_price'])}.\n\n"
        "Please: (1) recommend a pricing structure (per verified fix, with a quote band) and test two price points; "
        "(2) model revenue and gross margin at the volumes I give you; (3) add hosting, observability and "
        "tooling costs as separate fixed lines; (4) show monthly cash and runway given my starting cash. "
        "Ask me for volumes, fixed costs and starting cash before you build it."
    )
