"""The agent loop: one model call per turn, tools run locally, spend governed before each call."""
from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from margin.agent.coach import ask_coach, coach_digest, coach_note
from margin.agent.prompts import SYSTEM_PROMPT, digest_prompt, narrow_notice
from margin.agent.tools import tool_schemas
from margin.config import Settings
from margin.governor import Rung
from margin.jev import EDIT_NUDGE, JEV_MODEL, describe, exploring
from margin.model import build_request, is_transient
from margin.pricing import PriceTable, SpendMeter, Usage
from margin.state import RunState
from margin.telemetry import coerce, record_failure, trace


@dataclass
class AgentResult:
    stop: str  # end_turn | verified | abort | narrow_exhausted | max_turns | refusal | error
    turns: int
    abort_reason: str | None = None
    final_text: str = ""
    rung_events: list = field(default_factory=list)
    messages: list = field(default_factory=list)


def _retry_after(exc: BaseException) -> float | None:
    """Seconds the API asked us to wait, if it said so as a number."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    try:
        return float(headers.get("retry-after")) if headers is not None else None
    except (TypeError, ValueError):
        return None  # absent, or an HTTP date we do not parse


def call_with_retry(client: Any, params: dict, *, state: RunState, faults: Any, sleep: Callable, retries: int = 6):
    """Retry transient failures with backoff of 1, 2, 4, ... 32 s (a minute of overload), honouring retry-after."""
    for attempt in range(retries + 1):
        try:
            if faults is not None:
                faults.before_model_call()
            return client.create(**params)
        except Exception as exc:
            if attempt == retries or not is_transient(exc):
                raise
            delay = min(2**attempt, 32)
            asked = _retry_after(exc)
            if asked is not None:
                delay = min(max(delay, asked), 120)
            state.log("retry", attempt=attempt + 1, error=type(exc).__name__, delay=delay)
            record_failure("failed:model_call", f"{type(exc).__name__}: {exc}")
            with trace("retry", kind="GUARDRAIL", **{"margin.attempt": attempt + 1, "margin.delay_s": delay}):
                pass
            sleep(delay)


def _label_turn(span: Any, usage: Usage, cost: float, spend: float) -> None:
    """Put the turn's tokens and metered cost on its trace span. Telemetry must never fail the run."""
    with contextlib.suppress(Exception):
        for key, value in {
            "margin.input_tokens": usage.input_tokens, "margin.output_tokens": usage.output_tokens,
            "margin.cache_read_tokens": usage.cache_read_tokens, "margin.cache_write_tokens": usage.cache_write_tokens,
            "margin.cost_usd": cost, "margin.spend_usd": spend,
        }.items():
            span.set_attribute(key, coerce(value))


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
    judge: Any = None,
) -> AgentResult:
    model, effort = settings.main_model, settings.main_effort
    rung_events: list[dict] = []
    narrow_until: int | None = None
    # arm D: a coach instead of the downgrade, and an end to the run once the fix has verified
    coaching = arm in ("D", "E")
    judging = arm == "E" and judge is not None  # arm E: Jev judges progress each turn instead of the fixed stall rule
    coach_model = settings.coach_model or settings.main_model
    coach_notes, last_progress_turn, green_turn, judge_failures = 0, 0, None, 0
    last_coach_turn = last_nudge_turn = -(10**6)
    if resume:
        messages, turn = resume["messages"], resume["turn"]
        model, effort = resume["model"], resume["effort"]
        rung_events = list(resume["extra"].get("rung_events", []))
        narrow_until = resume["extra"].get("narrow_until")
        executor.progress.restore(resume["extra"].get("progress", {}))
        governor.restore(resume["rung"], resume["extra"].get("governor_seen", 0))
        coach_notes = resume["extra"].get("coach_notes", 0)
        last_progress_turn = resume["extra"].get("last_progress_turn", turn)
        green_turn = resume["extra"].get("green_turn")
        last_coach_turn = resume["extra"].get("last_coach_turn", last_coach_turn)
        last_nudge_turn = resume["extra"].get("last_nudge_turn", last_nudge_turn)
    else:
        messages, turn = [{"role": "user", "content": first_prompt}], 0
    seen_progress = executor.progress.events
    last_prompt_tokens = max(1, len(str(messages)) // 3)
    tools = tool_schemas(arm)

    def result(stop: str, reason: str | None = None, final_text: str = "") -> AgentResult:
        return AgentResult(stop, turn, reason, final_text, rung_events, messages)

    def log_rung(rung: str, reason: str) -> None:
        event = {"turn": turn, "rung": rung, "reason": reason, "spend": round(meter.total_usd, 6)}
        rung_events.append(event)
        state.log("rung", **event)
        with trace(
            "governor", kind="GUARDRAIL",
            **{"margin.rung": rung, "margin.spend_usd": meter.total_usd, "margin.reason": reason},
        ):
            pass

    def coach(reason: str) -> None:
        nonlocal coach_notes, last_progress_turn, last_coach_turn
        coach_notes += 1
        last_progress_turn = last_coach_turn = turn  # give the worker time to act on the note before judging it again
        log_rung("COACH", reason)
        note = ask_coach(  # retried like the worker's calls; injected faults stay on the worker's calls
            client, coach_model, coach_digest(executor, messages), meter=meter, state=state,
            create=lambda params: call_with_retry(client, params, state=state, faults=None, sleep=sleep),
        )
        if note:
            _append_notice(messages, coach_note(note))

    while turn < settings.max_turns:
        est = prices.estimate_next_call(model, last_prompt_tokens, settings.expected_output_tokens)
        decision = governor.check(meter.total_usd, est, executor.progress.events)
        can_coach = coaching and coach_notes < settings.coach_max_notes and not getattr(executor, "green", False)
        stuck_on_budget = coaching and decision.changed and decision.rung == Rung.DOWNGRADE
        # on arms D and E the stuck rung is logged as the coach's note below, unless no note can be given
        if decision.changed and not (stuck_on_budget and can_coach):
            log_rung(decision.rung.name, decision.reason)
        if decision.rung == Rung.ABORT:
            return result("abort", decision.reason)
        if executor.progress.events > seen_progress:
            seen_progress, last_progress_turn = executor.progress.events, turn
        verdict = None
        judge_blip = False  # a failed Jev call this turn that is not yet an outage
        if judging and turn >= settings.judge_warmup_turns and not getattr(executor, "green", False):
            verdict = judge.assess(executor, messages)
            if verdict is not None:  # Jev's tokens are part of the run's cost like any other call
                judge_failures = 0
                jev_usage = Usage(input_tokens=verdict.input_tokens)
                jev_cost = meter.record(JEV_MODEL, jev_usage)
                state.log("model_usage", model=JEV_MODEL, usage=jev_usage.to_dict(), cost=round(jev_cost, 8), stop="judge", role="judge")
                state.log("judge", turn=turn, **verdict.nouls)
            else:  # arm D's stall rule takes over only once Jev has failed several turns in a row
                judge_failures += 1
                judge_blip = judge_failures < settings.judge_fallback_after
                state.log("judge_unavailable", turn=turn, consecutive=judge_failures)
        if can_coach:
            if stuck_on_budget:
                coach(decision.reason)
            elif decision.changed and decision.rung == Rung.NARROW:
                coach(f"{decision.reason}; no fix verified yet")
            elif verdict is not None:  # calibrated: only readiness to edit separated stuck runs from working ones
                stuck = verdict.nouls["ready_to_edit"] < settings.judge_unready_below
                if stuck and turn - last_coach_turn >= settings.judge_min_gap:
                    coach(f"Jev judged the run stuck: {describe(verdict)}")
            elif not judge_blip and turn - last_progress_turn >= settings.coach_stall_turns:
                coach(f"no progress in {turn - last_progress_turn} turns")
        if (
            verdict is not None and verdict.nouls["ready_to_edit"] >= settings.judge_ready_at and exploring(messages)
            and turn - last_nudge_turn >= settings.judge_min_gap
        ):  # free: a fixed sentence, no model call
            last_nudge_turn = turn
            _append_notice(messages, EDIT_NUDGE)
            state.log("nudge", turn=turn, ready_to_edit=verdict.nouls["ready_to_edit"])
        if decision.changed and decision.rung == Rung.DOWNGRADE and not coaching:
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
            with trace(f"turn-{turn}", kind="AGENT", **{"margin.turn": turn, "margin.model": model}) as turn_span:
                response = call_with_retry(client, params, state=state, faults=faults, sleep=sleep)
                usage = Usage.from_api(response.usage)
                cost = meter.record(model, usage)
                state.log(
                    "model_usage", model=model, usage=usage.to_dict(), cost=round(cost, 6), stop=response.stop_reason
                )
                _label_turn(turn_span, usage, cost, meter.total_usd)
        except Exception as exc:  # noqa: BLE001 - a failed call ends the run, it must not crash the batch
            message = f"{type(exc).__name__}: {exc}"
            state.log("error", error=message)
            return result("error", message)

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
            notice = "Your last reply was cut off. Continue with tool calls, or finish with one sentence."
            unanswered = [b for b in response.content if b.type == "tool_use"]
            if unanswered:
                # A tool call cut off mid-way is never run, but the API rejects a request whose tool_use has no
                # tool_result, so every one is answered with an error before the nudge.
                answers = [
                    {
                        "type": "tool_result", "tool_use_id": b.id, "is_error": True,
                        "content": "This tool call was cut off by the output limit and was not run. Send it again, smaller.",
                    }
                    for b in unanswered
                ]
                messages.append({"role": "user", "content": [*answers, {"type": "text", "text": notice}]})
            else:
                messages.append({"role": "user", "content": notice})

        if coaching:  # stop when verified: a green full run that the agent keeps working past ends the run
            if not getattr(executor, "green", False):
                green_turn = None
            elif green_turn is None:
                green_turn = turn
        state.save_checkpoint(
            turn=turn, messages=messages, model=model, effort=effort, rung=governor.rung.name,
            extra={
                "rung_events": rung_events, "narrow_until": narrow_until,
                "progress": executor.progress.to_dict(), "governor_seen": getattr(governor, "seen_progress", 0),
                "coach_notes": coach_notes, "last_progress_turn": last_progress_turn, "green_turn": green_turn,
                "last_coach_turn": last_coach_turn, "last_nudge_turn": last_nudge_turn,
            },
        )
        if after_turn_hook is not None:
            after_turn_hook(turn)
        if green_turn is not None and turn - green_turn >= settings.stop_after_green_turns:
            return result("verified", None)

    return result("max_turns", "turn limit reached")
