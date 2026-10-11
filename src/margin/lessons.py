"""Lessons from past runs: post-mortems turned into short, repository-level advice for later runs.

A run never sees a lesson written about its own task (leave-one-out, the same rule the quote follows), so arm D is
measured on what it learned from other jobs, not on a hint about the answer.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from margin.agent.coach import recent_calls
from margin.ledger import RunRecord
from margin.model import build_request
from margin.pricing import PriceTable, SpendMeter, Usage

POSTMORTEM_SYSTEM = """You review one finished attempt by an AI agent to fix an issue in a Python repository.
Write one to three lessons that would help the same agent fix a DIFFERENT issue in the SAME repository next time:
how the code is organised, what to check before editing, which approach wasted time, what finally worked.
Do not describe this issue's fix or give a patch. Each lesson is one sentence on its own line, starting with "- "."""


@dataclass(frozen=True)
class Lesson:
    task_id: str
    repo: str
    text: str
    run_id: str = ""


def load_lessons(path: Path) -> list[Lesson]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(Lesson(**json.loads(line)))
        except (ValueError, TypeError):  # a torn or foreign line: skip it
            continue
    return out


def save_lessons(path: Path, lessons: Iterable[Lesson]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(asdict(x), sort_keys=True) + "\n" for x in lessons), encoding="utf-8")


# The tools refuse every write to a test file, so advice to add or write tests only leads the agent into refused calls.
_WRITES_TESTS = re.compile(r"\b(add|adding|write|writing|create|creating)\b[^.]{0,60}\btests?\b", re.IGNORECASE)


def lessons_for(task_id: str, repo: str, lessons: Iterable[Lesson], limit: int) -> list[str]:
    """Lessons from other tasks of the same repository, without duplicates, in the order they were learned."""
    chosen: list[str] = []
    for lesson in lessons:
        if _WRITES_TESTS.search(lesson.text):
            continue
        if lesson.repo == repo and lesson.task_id != task_id and lesson.text not in chosen:
            chosen.append(lesson.text)
        if len(chosen) >= limit:
            break
    return chosen


def select_runs(rows: Iterable[RunRecord]) -> list[RunRecord]:
    """Every failed benchmark run, then the cheapest verified run of each task: what went wrong and what worked."""
    real = [
        r for r in rows
        if not r.infra_error and not r.fault and r.task_id != "smoke-add"
        and not any(t.startswith("version:demo") for t in r.trace_tags)
    ]
    failed = [r for r in real if not r.solved]
    cheapest: dict[str, RunRecord] = {}
    for r in real:
        if r.solved and (r.task_id not in cheapest or r.cost_usd < cheapest[r.task_id].cost_usd):
            cheapest[r.task_id] = r
    return failed + list(cheapest.values())


def _postmortem_digest(row: RunRecord, messages: list, issue: str) -> str:
    outcome = "verified fix" if row.solved else f"not verified: {row.verdict_reason or row.abort_reason}"
    return (
        f"## Issue\n{issue[:3000]}\n\n## Outcome\n{outcome} (arm {row.arm}, {len(messages)} messages, "
        f"${row.cost_usd:.3f})\n\n## The agent's tool calls, last 20\n" + "\n".join(recent_calls(messages, 20))
    )


def build_lessons(
    runs: Iterable[RunRecord],
    runs_dir: Path,
    repo_of: dict[str, str],
    *,
    client: Any,
    model: str,
    prices: PriceTable,
    issue_of: Callable[[str], str],
) -> tuple[list[Lesson], float]:
    """Ask the model for lessons from each run's saved conversation. Returns the lessons and what the calls cost."""
    meter = SpendMeter(prices)
    lessons: list[Lesson] = []
    for row in runs:
        checkpoint = Path(runs_dir) / row.run_id / "checkpoint.json"
        if not checkpoint.exists() or row.task_id not in repo_of:
            continue
        messages = json.loads(checkpoint.read_text(encoding="utf-8"))["messages"]
        params = build_request(
            model=model, effort="low", system=POSTMORTEM_SYSTEM, tools=[],
            messages=[{"role": "user", "content": _postmortem_digest(row, messages, issue_of(row.task_id))}], max_tokens=600,
        )
        params.pop("tools")
        response = client.create(**params)
        meter.record(model, Usage.from_api(response.usage))
        reply = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text")
        for line in reply.splitlines():
            line = line.strip()
            if line.startswith("- ") and len(line) > 4:
                lessons.append(Lesson(row.task_id, repo_of[row.task_id], line[2:].strip(), row.run_id))
    return lessons, meter.total_usd
