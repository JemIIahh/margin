"""Replay arm E's progress judge on recorded calibration-task runs, to choose its thresholds from our own data.

Calibration tasks only, so the evaluation tasks never influence the thresholds. For every recorded run on a calibration
task (any arm) the judge is asked about the run as it stood at several turns. Two groups are compared:

- productive: a turn in a run that went on to verify, before its first fully green test run;
- stuck: a turn from turn 12 on in a run that ran out of turns without verifying.

Run with the TypeSafe key in .env: `uv run python scripts/calibrate_judge.py`. Prints one line per sample and a summary.
Costs a fraction of a cent (about 600 input tokens per call at $0.042 per million).
"""
import json
import statistics

from margin.agent.coach import recent_calls
from margin.config import ROOT, load_dotenv
from margin.jev import PROGRESS_QUESTIONS, make_jev

load_dotenv()
CALIBRATION = {"cachetools-423", "toolz-602", "moreitertools-1304", "sqlparse-772"}


def assistant_turns(messages: list) -> list[int]:
    return [i for i, m in enumerate(messages) if m["role"] == "assistant"]


def last_tests(messages: list) -> str:
    for m in reversed(messages):
        if m["role"] == "user" and isinstance(m["content"], list):
            for b in m["content"]:
                body = b.get("content") if b.get("type") == "tool_result" else None
                if isinstance(body, str) and body.startswith("Target tests"):
                    return body[:800]
    return "(tests not run yet)"


def edits_so_far(messages: list) -> str:
    """The patch at this turn, rebuilt from the recorded edit_file and write_file calls (the diff itself was not saved)."""
    lines = []
    for m in messages:
        if m["role"] == "assistant" and isinstance(m["content"], list):
            for b in m["content"]:
                if b.get("type") == "tool_use" and b.get("name") == "edit_file":
                    i = b.get("input", {})
                    lines.append(f"{i.get('path')}: replaced {str(i.get('old'))[:150]!r} with {str(i.get('new'))[:150]!r}")
                elif b.get("type") == "tool_use" and b.get("name") == "write_file":
                    lines.append(f"{b.get('input', {}).get('path')}: wrote a new version")
    return "\n".join(lines)[-2000:] or "(no changes yet)"


def first_green(messages: list) -> int | None:
    turn = -1
    for m in messages:
        if m["role"] == "assistant":
            turn += 1
        if m["role"] == "user" and isinstance(m["content"], list):
            for b in m["content"]:
                body = b.get("content") if b.get("type") == "tool_result" else None
                if isinstance(body, str) and body.startswith("Target tests: 0 failing"):
                    return turn
    return None


def main() -> None:
    jev = make_jev()
    rows = [json.loads(line) for line in (ROOT / "runs" / "ledger.jsonl").read_text().splitlines() if line.strip()]
    samples = []
    for r in rows:
        if r["task_id"] not in CALIBRATION or r.get("infra_error") or r.get("fault") or r["rung_events"]:
            continue
        if any(t.startswith("version:demo") for t in r["trace_tags"]):
            continue
        checkpoint = ROOT / "runs" / r["run_id"] / "checkpoint.json"
        if not checkpoint.exists():
            continue
        messages = json.loads(checkpoint.read_text())["messages"]
        issue = messages[0]["content"] if isinstance(messages[0]["content"], str) else ""
        turns = assistant_turns(messages)
        green = first_green(messages)
        for k in range(4, len(turns), 4):
            if r["solved"] and green is not None and k < green:
                group = "productive"
            elif not r["solved"] and k >= 12:
                group = "stuck"
            else:
                continue
            upto = messages[: turns[k] + 1]
            state = {
                "issue": issue[:1500], "patch_so_far": edits_so_far(upto),
                "latest_tests": last_tests(upto), "recent_actions": recent_calls(upto, 6),
            }
            answers = jev.nouls(state, PROGRESS_QUESTIONS)
            if answers is None:
                continue
            samples.append((group, r["arm"], r["task_id"], k, answers.nouls))
            print(group, r["arm"], r["task_id"], k, {q: round(v, 2) for q, v in answers.nouls.items()})
    print("\nsummary (median, min, max) by group:")
    for group in ("productive", "stuck"):
        chosen = [s for s in samples if s[0] == group]
        for q in PROGRESS_QUESTIONS:
            values = [s[4][q] for s in chosen]
            if values:
                print(f"  {group:10} n={len(values):3} {q:13} median {statistics.median(values):.2f}  min {min(values):.2f}  max {max(values):.2f}")
    print(f"Jev input tokens used: {jev.input_tokens}")
    (ROOT / ".superpowers").mkdir(exist_ok=True)
    (ROOT / ".superpowers" / "judge_samples.json").write_text(json.dumps(samples))
    rules = {
        "progress < 0.25": lambda a: a["progress"] < 0.25,
        "progress < 0.30": lambda a: a["progress"] < 0.30,
        "progress < 0.35": lambda a: a["progress"] < 0.35,
        "ready_to_edit < 0.40": lambda a: a["ready_to_edit"] < 0.40,
        "progress < 0.35 and ready_to_edit < 0.40": lambda a: a["progress"] < 0.35 and a["ready_to_edit"] < 0.40,
        "repeating >= 0.75": lambda a: a["repeating"] >= 0.75,
    }
    stuck = [s[4] for s in samples if s[0] == "stuck"]
    productive = [s[4] for s in samples if s[0] == "productive"]
    print("\nrule: share of stuck samples it flags (want high) / share of productive samples it flags (want low)")
    for name, rule in rules.items():
        hit = sum(rule(a) for a in stuck) / max(1, len(stuck))
        false = sum(rule(a) for a in productive) / max(1, len(productive))
        print(f"  {name:42} {hit:5.0%} / {false:5.0%}")


if __name__ == "__main__":
    main()
