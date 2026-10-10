"""The agent loop: one model call per turn, tools run locally, spend governed before each call."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from margin.agent.prompts import SYSTEM_PROMPT, digest_prompt, narrow_notice
from margin.agent.tools import tool_schemas
from margin.config import Settings
from margin.governor import Rung
from margin.model import build_request, is_transient
from margin.pricing import PriceTable, SpendMeter, Usage
from margin.state import RunState
from margin.telemetry import trace


@dataclass
class AgentResult:
    stop: str  # end_turn | abort | narrow_exhausted | max_turns | refusal | error
    turns: int
    abort_reason: str | None = None
    final_text: str = ""
    rung_events: list = field(default_factory=list)
    messages: list = field(default_factory=list)


def call_with_retry(client: Any, params: dict, *, state: RunState, faults: Any, sleep: Callable, retries: int = 4):
    for attempt in range(retries + 1):
        try:
            if faults is not None:
                faults.before_model_call()
            return client.create(**params)
        except Exception as exc:
            if attempt == retries or not is_transient(exc):
                raise
            delay = min(2**attempt, 8)
            state.log("retry", attempt=attempt + 1, error=type(exc).__name__, delay=delay)
            sleep(delay)


def _append_notice(messages: list, text: str) -> None:
    last = messages[-1]
    if last["role"] != "user":
        messages.append({"role": "user", "content": text})
    elif isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}, {"type": "text", "text": text}]
    else:
        last["content"].append({"type": "text", "text": text})


def run_agent(
    *,
    first_prompt: str,
    arm: str,
    client: Any,
    meter: SpendMeter,
    governor: Any,
    executor: Any,
    state: RunState,
    prices: PriceTable,
    settings: Settings,
    faults: Any = None,
    resume: dict | None = None,
    sleep: Callable = time.sleep,
    after_turn_hook: Callable[[int], None] | None = None,
) -> AgentResult:
    model, effort = settings.main_model, settings.main_effort
    rung_events: list[dict] = []
    narrow_until: int | None = None
    if resume:
        messages, turn = resume["messages"], resume["turn"]
        model, effort = resume["model"], resume["effort"]
        governor.restore(resume["rung"])
        rung_events = list(resume["extra"].get("rung_events", []))
        narrow_until = resume["extra"].get("narrow_until")
        executor.progress.restore(resume["extra"].get("progress", {}))
    else:
        messages, turn = [{"role": "user", "content": first_prompt}], 0
    last_prompt_tokens = max(1, len(str(messages)) // 3)
    tools = tool_schemas(arm)

    def result(stop: str, reason: str | None = None, final_text: str = "") -> AgentResult:
        return AgentResult(stop, turn, reason, final_text, rung_events, messages)

    while turn < settings.max_turns:
        est = prices.estimate_next_call(model, last_prompt_tokens, settings.expected_output_tokens)
        decision = governor.check(meter.total_usd, est, executor.progress.events)
        if decision.changed:
            event = {
                "turn": turn, "rung": decision.rung.name, "reason": decision.reason,
                "spend": round(meter.total_usd, 6),
            }
            rung_events.append(event)
            state.log("rung", **event)
            with trace(
                "governor", kind="GUARDRAIL",
                **{"margin.rung": decision.rung.name, "margin.spend_usd": meter.total_usd, "margin.reason": decision.reason},
            ):
                pass
        if decision.rung == Rung.ABORT:
            return result("abort", decision.reason)
        if decision.changed and decision.rung == Rung.DOWNGRADE:
            model, effort = settings.fallback_model, settings.fallback_effort
            digest = executor.digest()
            messages = [
                {
                    "role": "user",
                    "content": digest_prompt(
                        executor.issue_text, digest["diff"], digest["tests"], executor.target_nodeids
                    ),
                }
            ]
            last_prompt_tokens = max(1, len(messages[0]["content"]) // 3)
        if decision.changed and decision.rung == Rung.NARROW:
            narrow_until = turn + settings.narrow_turns
            _append_notice(messages, narrow_notice(settings.narrow_turns))
        if narrow_until is not None and turn >= narrow_until:
            return result("narrow_exhausted", "narrowed budget used up")
        if meter.total_usd >= settings.run_hard_cap_usd:
            return result("abort", "hard cap")

        params = build_request(
            model=model, effort=effort, system=SYSTEM_PROMPT, tools=tools, messages=messages,
            max_tokens=settings.max_tokens,
        )
        try:
            with trace(f"turn-{turn}", kind="AGENT", **{"margin.turn": turn, "margin.model": model}):
                response = call_with_retry(client, params, state=state, faults=faults, sleep=sleep)
        except Exception as exc:  # noqa: BLE001 - a failed call ends the run, it must not crash the batch
            message = f"{type(exc).__name__}: {exc}"
            state.log("error", error=message)
            return result("error", message)

        usage = Usage.from_api(response.usage)
        cost = meter.record(model, usage)
        state.log("model_usage", model=model, usage=usage.to_dict(), cost=round(cost, 6), stop=response.stop_reason)
        last_prompt_tokens = max(1, usage.prompt_tokens)
        messages.append({"role": "assistant", "content": [b.to_dict() for b in response.content]})
        turn += 1

        if response.stop_reason == "refusal":
            return result("refusal", "model refusal")
        if response.stop_reason == "end_turn":
            final = "".join(b.text for b in response.content if b.type == "text")
            return result("end_turn", None, final)
        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                out = executor.execute(block.name, block.input)
                item = {"type": "tool_result", "tool_use_id": block.id, "content": out.text}
                if out.is_error:
                    item["is_error"] = True
                results.append(item)
            messages.append({"role": "user", "content": results})
        else:  # max_tokens or anything unexpected: ask the model to carry on
            messages.append(
                {
                    "role": "user",
                    "content": "Your last reply was cut off. Continue with tool calls, or finish with one sentence.",
                }
            )

        state.save_checkpoint(
            turn=turn, messages=messages, model=model, effort=effort, rung=governor.rung.name,
            extra={
                "rung_events": rung_events, "narrow_until": narrow_until,
                "progress": executor.progress.to_dict(),
            },
        )
        if after_turn_hook is not None:
            after_turn_hook(turn)

    return result("max_turns", "turn limit reached")
