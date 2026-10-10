"""Append-only JSONL ledger of runs, settlement arithmetic and the markdown receipt."""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class RunRecord:
    run_id: str
    task_id: str
    arm: str
    split: str
    solved: bool
    cost_usd: float
    price_usd: float
    revenue_usd: float
    margin_usd: float
    tokens_total: int
    features: dict = field(default_factory=dict)
    quote: dict | None = None
    rung_events: list = field(default_factory=list)
    abort_reason: str | None = None
    duration_s: float = 0.0
    fault: str | None = None
    recoveries: int = 0
    started_at: str = ""
    trace_tags: list = field(default_factory=list)
    verdict_reason: str = ""
    tests_touched: list = field(default_factory=list)  # test paths the agent changed; reverted before judging
    infra_error: bool = False  # the run failed for harness or infrastructure reasons, not on its merits

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> RunRecord:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def settle(price_usd: float, solved: bool, cost_usd: float) -> tuple[float, float]:
    """Pay-per-verified-fix: revenue is the price if solved, else zero."""
    revenue = price_usd if solved else 0.0
    return revenue, revenue - cost_usd


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, rec: RunRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec.to_dict(), sort_keys=True) + "\n")
            f.flush()

    def rows(self, arm: str | None = None) -> list[RunRecord]:
        if not self.path.exists():
            return []
        out: list[RunRecord] = []
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = RunRecord.from_dict(json.loads(line))
            except (json.JSONDecodeError, TypeError, KeyError):
                warnings.warn(f"skipping unreadable ledger line {n}", stacklevel=2)
                continue
            if arm is None or row.arm == arm:
                out.append(row)
        return out

    def latest(self, arm: str) -> dict[str, RunRecord]:
        """Last benchmark row per task. Fault-injection, demo and infrastructure-failure rows never count."""
        out: dict[str, RunRecord] = {}
        for row in self.rows(arm):
            if row.fault or row.infra_error or any(tag.startswith("version:demo") for tag in row.trace_tags):
                continue
            out[row.task_id] = row
        return out


def render_receipt(r: RunRecord) -> str:
    if r.quote:
        quote = f"${r.quote['lo']:.4f} – ${r.quote['hi']:.4f} (p50 ${r.quote['p50']:.4f})"
    else:
        quote = "none (flat price)"
    rungs = "\n".join(f"- turn {e['turn']}: **{e['rung']}**: {e['reason']}" for e in r.rung_events) or "- none"
    verdict = "verified" if r.solved else "not verified"
    lines = [
        f"# Receipt: {r.task_id} (arm {r.arm})",
        "",
        f"- Quoted cost band: {quote}",
        f"- Price: ${r.price_usd:.4f}",
        f"- Actual cost: ${r.cost_usd:.4f} ({r.tokens_total} tokens)",
        f"- Verdict: **{verdict}** ({r.verdict_reason or 'n/a'})",
        f"- Revenue: ${r.revenue_usd:.4f}",
        f"- Margin: ${r.margin_usd:.4f}",
    ]
    if r.abort_reason:
        lines.append(f"- Stopped early: {r.abort_reason}")
    lines += ["", "## Governor decisions", rungs, ""]
    return "\n".join(lines)
