"""Arm D's coach: a second model that reads where a stuck run stands and tells the worker what to try next.

The worker keeps its own model and its whole conversation; the coach only adds a short note. Its calls are metered on the
same spend meter and count against the run's cap, so coaching is never free money.
"""
from __future__ import annotations

import contextlib
import json
from typing import Any

from margin.model import build_request
from margin.pricing import SpendMeter, Usage
from margin.state import RunState
from margin.telemetry import trace

COACH_SYSTEM = """You are a senior engineer coaching a junior agent that is fixing one issue in a Python repository and is stuck.
The agent can read and edit files, search the code, run the tests and run Python snippets; it has no shell.
Reply in at most 120 words, as plain text:
Diagnosis: one or two sentences on why it is stuck.
Next step: one to three concrete actions (which file, which function, what to check).
Avoid: one thing it should stop doing.
Never tell it to edit or add test files; edits to tests are rejected."""


def _blocks(message: dict) -> list:
    content = message.get("content")
    return content if isinstance(content, list) else [{"type": "text", "text": content or ""}]


def recent_calls(messages: list, limit: int = 8) -> list[str]:
    """The last tool calls of the run with the start of each result, oldest first."""
    results = {
        b.get("tool_use_id"): b for m in messages if m.get("role") == "user" for b in _blocks(m) if b.get("type") == "tool_result"
    }
    lines = []
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for b in _blocks(m):
            if b.get("type") != "tool_use":
                continue
            args = json.dumps(b.get("input", {}), sort_keys=True)[:160]
            res = results.get(b.get("id"), {})
            body = res.get("content")
            body = body if isinstance(body, str) else json.dumps(body or "")
            flag = " (error)" if res.get("is_error") else ""
            lines.append(f"- {b.get('name')} {args}{flag}: {body[:200].replace(chr(10), ' ')}")
    return lines[-limit:]


def coach_digest(executor: Any, messages: list) -> str:
    digest = executor.digest()
    calls = "\n".join(recent_calls(messages)) or "(no tool calls yet)"
    return (
        f"## Issue\n{executor.issue_text[:4000]}\n\n"
        f"## Target tests\n" + "\n".join(f"- {t}" for t in executor.target_nodeids) + "\n\n"
        f"## Patch so far (git diff)\n{digest['diff'][:6000] or '(no changes yet)'}\n\n"
        f"## Latest test result\n{digest['tests'][:3000]}\n\n"
        f"## The agent's last tool calls\n{calls}\n"
    )


def coach_note(note: str) -> str:
    return f"Note from a reviewer who looked at your run so far (follow it if it helps):\n{note.strip()}"


def ask_coach(
    client: Any, model: str, digest: str, *, meter: SpendMeter, state: RunState, max_tokens: int = 800
) -> str | None:
    """One coaching call. A failure returns None: a missing note must never end the worker's run."""
    params = build_request(
        model=model, effort="low", system=COACH_SYSTEM, tools=[], messages=[{"role": "user", "content": digest}],
        max_tokens=max_tokens,
    )
    params.pop("tools")  # an empty tool list is not a valid request on every provider
    try:
        with trace("coach", kind="AGENT", **{"margin.model": model}) as span:
            response = client.create(**params)
            usage = Usage.from_api(response.usage)
            cost = meter.record(model, usage)
            state.log("model_usage", model=model, usage=usage.to_dict(), cost=round(cost, 6), stop=response.stop_reason, role="coach")
            with contextlib.suppress(Exception):
                span.set_attribute("margin.cost_usd", cost)
    except Exception as exc:  # noqa: BLE001 - the coach is optional help
        state.log("coach_error", error=f"{type(exc).__name__}: {exc}"[:300])
        return None
    note = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text").strip()
    state.log("coach", note=note[:2000])
    return note or None
