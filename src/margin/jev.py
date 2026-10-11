"""Jev, TypeSafe's System One model, as arm E's cheap judge: typed yes/no probabilities in one call, metered, never fatal.

Jev answers questions about a state; it does not generate text. Code owns every decision made from its answers. Its own
documentation warns that accuracy falls as the state grows with irrelevant content and that text written to steer it can
shift its answers, so the state sent here is a short digest and nothing it says is a security boundary.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from margin.agent.coach import recent_calls
from margin.intake import CHARS_PER_TOKEN, PROMPT_OVERHEAD_TOKENS, USD_PER_MTOK_INPUT

JEV_MODEL = "jev-latest"  # the price row in pricing.toml has the same name

PROGRESS_QUESTIONS = {
    "progress": (
        "In its most recent actions the agent made progress toward fixing the issue: it changed the code in a way "
        "that moves toward a fix, or it learned something new and specific about the cause."
    ),
    "repeating": (
        "The agent's most recent actions repeat an approach that already failed, or re-read information it already "
        "had without acting on it."
    ),
    "ready_to_edit": (
        "The agent has already found the code that must change and knows what to change, so it should edit the code "
        "now instead of reading or running more."
    ),
}
EDIT_NUDGE = (
    "Reviewer check: you appear to know enough to make the change. Edit the code now and run the tests; "
    "stop reading or running snippets until you have."
)
_EXPLORING = {"read_file", "search_code", "graph_impact", "run_python", "git_diff"}


NO_KEY = "arm E needs TYPESAFE_API_KEY in .env (create a key at console.typesafe.ai); arms A to D run without it"


class JevUnavailable(RuntimeError):
    pass


def _estimated_tokens(state: Any, payload: dict) -> int:
    sent = json.dumps(state, default=str) + json.dumps(payload, default=str)
    return len(sent) // CHARS_PER_TOKEN + PROMPT_OVERHEAD_TOKENS


@dataclass(frozen=True)
class JevAnswers:
    nouls: dict
    input_tokens: int
    cost_usd: float


class Jev:
    def __init__(self, client: Any):
        self.client = client
        self.input_tokens = 0  # every token Jev reported, so callers can meter exactly what was used

    def nouls(self, state: Any, questions: dict[str, str]) -> JevAnswers | None:
        """One call with a Noul per question. Any failure returns None: Jev is advice, never a dependency."""
        payload = {name: {"type": "noul", "instructions": text} for name, text in questions.items()}
        try:
            result = self.client.system_one(state, payload)
            values = {name: float(result.nouls[name].noul) for name in questions}
            reported = getattr(getattr(result, "usage", None), "input_tokens", None)
        except Exception:  # noqa: BLE001 - an unavailable judge must not end a paid run
            return None
        # A reply without a usage figure was still paid for: estimate it as the intake gate does, never meter it as free.
        tokens = int(reported) if reported is not None else _estimated_tokens(state, payload)
        self.input_tokens += tokens
        return JevAnswers(values, tokens, tokens * USD_PER_MTOK_INPUT / 1_000_000)


def make_jev() -> Jev:
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise JevUnavailable(NO_KEY)
    from typesafe_sdk import RetryPolicy, TypeSafeClient

    return Jev(TypeSafeClient(retry=RetryPolicy(max_retries=2, timeout=15.0)))


def recent_tool_names(messages: list, limit: int) -> list[str]:
    names = [
        b.get("name") for m in messages if m.get("role") == "assistant" and isinstance(m.get("content"), list)
        for b in m["content"] if b.get("type") == "tool_use"
    ]
    return names[-limit:]


def exploring(messages: list, last: int = 3) -> bool:
    """The agent's last few calls only looked around: nothing was edited and no test was run."""
    names = recent_tool_names(messages, last)
    return len(names) == last and all(n in _EXPLORING for n in names)


class ProgressJudge:
    """Asks Jev, from a compact digest of the run, whether the agent is progressing, repeating itself, or ready to edit."""

    def __init__(self, jev: Jev):
        self.jev = jev

    def assess(self, executor: Any, messages: list) -> JevAnswers | None:
        digest = executor.digest()
        state = {
            "issue": executor.issue_text[:1500],
            "patch_so_far": (digest["diff"] or "(no changes yet)")[:2000],
            "latest_tests": digest["tests"][:800],
            "recent_actions": recent_calls(messages, 6),
        }
        return self.jev.nouls(state, PROGRESS_QUESTIONS)


def pick_lessons(issue: str, candidates: list[str], jev: Jev, limit: int, floor: float = 0.5) -> list[str]:
    """The candidate lessons Jev rates relevant to this issue, best first; the first ones if Jev is unavailable."""
    if not candidates:
        return []
    questions = {
        f"l{i}": f"This advice is relevant to fixing the issue described in the state: {text}"
        for i, text in enumerate(candidates)
    }
    answers = jev.nouls({"issue": issue[:3000]}, questions)
    if answers is None:
        return candidates[:limit]
    ranked = sorted(range(len(candidates)), key=lambda i: -answers.nouls[f"l{i}"])
    return [candidates[i] for i in ranked if answers.nouls[f"l{i}"] >= floor][:limit]


def describe(answers: JevAnswers) -> str:
    return json.dumps({k: round(v, 2) for k, v in answers.nouls.items()})
