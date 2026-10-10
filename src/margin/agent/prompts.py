"""Prompt text. Kept short and stable: the system prompt is the cached prefix."""
from __future__ import annotations

SYSTEM_PROMPT = """You are a careful software engineer fixing one issue in a Python repository.

Rules:
- The working directory is the repository. Use the provided tools; you have no shell.
- The target tests are already failing and must pass. Never edit them; edits to test files are rejected.
- Make the smallest correct change. Do not refactor, reformat or touch unrelated code.
- Call run_tests after each edit and fix what it reports before doing anything else.
- When the target tests pass and there are no new failures, reply with one sentence describing the fix and stop.
- If a tool returns an error, read it and adjust. Do not repeat the same call unchanged."""


def first_prompt(issue: str, context: str, target_nodeids: list[str]) -> str:
    targets = "\n".join(f"- {t}" for t in target_nodeids)
    return (
        "Fix this issue in the repository checked out in the working directory.\n\n"
        f"## Issue\n{issue}\n\n"
        f"## Target tests (currently failing; they must pass)\n{targets}\n\n"
        f"## Repository context\n{context}\n\n"
        "Make the smallest change that makes the target tests pass without breaking other tests. "
        "Use run_tests to check your work."
    )


def digest_prompt(issue: str, diff: str, tests: str, target_nodeids: list[str]) -> str:
    targets = "\n".join(f"- {t}" for t in target_nodeids)
    return (
        "You are continuing a fix that is already in progress. The budget is tight: make the smallest "
        "change that finishes the job.\n\n"
        f"## Issue\n{issue}\n\n"
        f"## Target tests\n{targets}\n\n"
        f"## Current patch (git diff)\n{diff or '(no changes yet)'}\n\n"
        f"## Latest test result\n{tests}\n\n"
        "Continue from here. Use run_tests to verify, then reply with one sentence and stop."
    )


def narrow_notice(turns: int) -> str:
    return (
        "Budget notice: spend is close to the cap. Stop exploring. Make one minimal patch now and "
        f"verify it. You have at most {turns} turns left."
    )
