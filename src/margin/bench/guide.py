"""The illustrated guide: how one job runs, drawn from the same data as the console.

`docs/guide.html` is generated and checked like `docs/console.html`. Every number on it comes from the console's
data (the ledger snapshot and the replays), and the page makes a few claims in words ("no job in C, D or E
finished over its cap", "E is level with D"); `render_guide` refuses to build when the data does not support one,
so the guide cannot say something the evidence does not.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from margin.bench.tasks import Task

PAGE = Path(__file__).with_name("guide_page.html")
REPO_URL = "https://github.com/JemIIahh/margin"
ARMS = "ABCDE"
LAST_ARM = "E"  # the version the tour follows
PASS_TASK = "moreitertools-1284"  # a job whose fix verified
FAIL_TASK = "marshmallow-2249"  # a job whose fix broke another test and was stopped before the cap
TASK_ENTRY = "cachetools-423"  # the benchmark task shown as the example of a task file

SHORT = {"A": "Flat price", "B": "+ code map", "C": "+ quote and cap", "D": "+ coach and lessons", "E": "+ Jev"}
DESC = {
    "A": "Charges one flat price for every job.",
    "B": "Gives the agent a map of the code first.",
    "C": "Quotes a price for each job and caps its spending.",
    "D": "Adds a coach for when it stalls, stops once the tests pass, and lessons from other jobs.",
    "E": "Lets Jev, from TypeSafe, screen the issue and decide when to coach.",
}


class GuideError(ValueError):
    """The data does not support what the guide would say."""


def _money(value: float) -> str:
    return ("−$" if value < 0 else "$") + f"{abs(value):.4f}"


def _pct(share: float) -> str:
    return f"{round(share * 100)}%"


def _job(data: dict, task: str) -> dict:
    for job in data["jobs"].get(LAST_ARM, []):
        if job["task"] == task:
            return job
    raise GuideError(f"the guide follows task {task} on version {LAST_ARM}, but the data has no such job")


def _example(data: dict, task: str, outcome: str) -> dict:
    """One job, as the tour draws it: the real quote, the spend after every call, the governor's marks, the receipt."""
    job = _job(data, task)
    if bool(job["solved"]) != (outcome == "pass"):
        wanted = "passes" if outcome == "pass" else "fails"
        raise GuideError(f"the guide shows {task} as a job that {wanted}, but the recorded run says solved={job['solved']}")
    if not job.get("neighbours"):
        raise GuideError(f"{task} has no similar-jobs explanation: the quote could not be reproduced from the ledger")
    replay = data["replays"][job["run_id"]]
    marks, curve = replay["marks"], [t["cum"] for t in replay["turns"]]
    events: list[dict] = []
    for mark in marks:
        kind, after = mark["kind"], mark["after"]
        if kind == "intake":
            events.append({"label": "intake", "cls": "dim", "text": mark["note"]})
        elif kind == "lessons":
            events.append({"label": "lessons", "cls": "dim", "text": mark["note"] + " from other tasks"})
        elif kind == "nudge":
            text = "Jev judged the agent ready to edit, so it was told to edit now"
            events.append({"label": f"turn {after}", "cls": "warnc", "text": text})
        elif kind == "coach":
            events.append({"label": f"turn {after}", "cls": "warnc", "text": "coach called: " + mark["note"],
                           "sub": mark.get("detail", "")})
        elif kind == "abort":
            events.append({"label": f"turn {after}", "cls": "badc", "text": "stopped: " + mark["note"]})
    cap = _money(job["quote"]["hi"])
    events.append({"label": "end", "cls": "dim", "text": f"{len(curve)} calls, {_money(job['cost'])} of the {cap} cap"})
    receipt = [list(item) for item in job["receipt"]["items"]]
    receipt.append(["Command output", job["cli"]["run"].split(": ", 1)[1]])
    intake = next((m for m in marks if m["kind"] == "intake"), None)
    scores = re.search(r"injection ([\d.]+), actionable ([\d.]+)", intake["note"]) if intake else None
    if not scores:
        raise GuideError(f"{task} has no intake screening recorded: the guide's check step needs its scores")
    governor = [
        {"kind": m["kind"], "after": m["after"], "at": curve[min(m["after"], len(curve)) - 1] if m["after"] else 0.0}
        for m in marks if m["kind"] in ("coach", "nudge", "abort")
    ]
    return {
        "curve": curve, "gov": governor, "intake": {"injection": float(scores.group(1)), "actionable": float(scores.group(2))},
        "short_test": job["verdict"]["detail"].split("::")[-1] if outcome == "fail" else "",
        "task": task, "outcome": outcome, "run_id": job["run_id"], "repo": job["repo"], "issue_url": job["issue_url"],
        "title_plain": job["title"].replace("`", ""), "quote": job["quote"], "price": job["price"], "cost": job["cost"],
        "margin": job["margin"], "turns": len(curve), "features": job["features"],
        "neighbours": [{"task": n["task"], "cost": n["cost"]} for n in job["neighbours"]["picked"]],
        "coaches": [{"after": m["after"]} for m in marks if m["kind"] == "coach"],
        "stop": next(({"after": m["after"]} for m in marks if m["kind"] == "abort"), None),
        "events": events, "cli_quote": job["cli"]["quote"], "receipt_title": job["receipt"]["title"], "receipt": receipt,
        "broken": job["verdict"]["detail"] if outcome == "fail" else "",
    }


def _check_claims(data: dict, passing: dict, failing: dict) -> None:
    """The sentences on the page that are claims about the data, each checked."""
    summaries = data["summaries"]
    for arm in ARMS:
        if arm not in summaries:
            raise GuideError(f"the guide draws five versions, but the data has no version {arm}")
    for arm in "CDE":
        if summaries[arm]["over_cap"]:
            raise GuideError(f"the guide says no job in C, D or E finished over its cap, but version {arm} has "
                             f"{summaries[arm]['over_cap']}")
    if summaries["E"]["verified"] != summaries["D"]["verified"]:
        raise GuideError("the guide says version E is level with version D, but they verified different numbers")
    if data["markup"] != 0.5:
        raise GuideError("the guide says the price is the cap plus 50%, but the recorded markup is different")
    if not passing["coaches"] or passing["stop"]:
        raise GuideError("the passing example must show a coach call and no stop")
    if not failing["stop"] or not failing["coaches"]:
        raise GuideError("the failing example must show a coach call and a stop before the cap")


def _versions_rows(data: dict) -> str:
    rows = []
    for arm in ARMS:
        s = data["summaries"][arm]
        rows.append(
            f'      <div class="vrow" title="{html.escape(DESC[arm])}"><div class="vname"><b>{arm}</b>'
            f"<span>{html.escape(SHORT[arm])}</span></div>"
            f'<div class="vtrack" role="img" aria-label="Version {arm} kept {_pct(s["gross_margin"])} of what it billed">'
            f'<i style="width:{s["gross_margin"] * 100:.1f}%"></i></div>'
            f'<div class="vnum"><b>{_pct(s["gross_margin"])}</b><small>{s["verified"]} of {s["n"]} fixed</small></div></div>'
        )
    return "\n".join(rows)


def _task_block(tasks: list[Task]) -> str:
    """The example task file: a real entry from bench/tasks.toml, with the comments a newcomer needs."""
    task = next((t for t in tasks if t.id == TASK_ENTRY), None)
    if task is None:
        raise GuideError(f"the guide shows task {TASK_ENTRY} as the example task file, but the manifest has no such task")
    lines = [
        ("# my-tasks.toml: one entry per bug", ""), ("[[task]]", ""), (f'id = "{task.id}"', ""),
        (f'split = "{task.split}"', "calibration or evaluation, as in bench/tasks.toml"), (f'repo = "{task.repo}"', ""),
        (f'base_commit = "{task.base_commit}"', "the commit before the fix"),
        (f'fix_commit = "{task.fix_commit}"', "the known fix, used to check the task is valid"),
        (f'issue_url = "{task.issue_url}"', ""), (f'issue_file = "{task.issue_file}"', "the issue text, saved as a file"),
        (f"target_tests = {json.dumps(task.target_tests)}", "fail before, pass after"),
        (f"test_files = {json.dumps(task.test_files)}", ""), (f"test_args = {json.dumps(task.test_args)}", ""),
        (f"deps = {json.dumps(task.deps)}", ""), (f"pythonpath = {json.dumps(task.pythonpath)}", ""),
    ]
    out = []
    for code, note in lines:
        if code.startswith("#"):
            out.append(f'<span class="cm">{html.escape(code, quote=False)}</span>')
        else:
            out.append(html.escape(code, quote=False) + (f'   <span class="cm"># {html.escape(note, quote=False)}</span>' if note else ""))
    return "\n".join(out)


def render_guide(
    data: dict[str, Any],
    tasks: list[Task],
    *,
    console_href: str = "console.html",
    guide_href: str = "guide.html",
    repo_url: str = REPO_URL,
) -> str:
    """`data` is the console's data. `console_href` and `guide_href` are where the two pages live relative to each other."""
    passing, failing = _example(data, PASS_TASK, "pass"), _example(data, FAIL_TASK, "fail")
    _check_claims(data, passing, failing)
    costs = [j["cost"] for arm in ARMS for j in data["jobs"].get(arm, [])]  # the runs the site shows
    fills = {
        "repo": repo_url, "demo_run": passing["run_id"], "n": str(data["n"]), "versions_rows": _versions_rows(data),
        "run_cost_lo": f"${min(costs):.2f}", "run_cost_hi": f"${max(costs):.2f}", "task_toml": _task_block(tasks),
        "console": html.escape(console_href), "guide": html.escape(guide_href),
    }
    template = PAGE.read_text(encoding="utf-8")
    if template.count("__DATA__") != 1:
        raise ValueError("guide_page.html must contain __DATA__ exactly once")
    for key, value in fills.items():
        template = template.replace("{{" + key + "}}", value)
    left = re.findall(r"\{\{[^}]*\}\}", template)
    if left:
        raise ValueError(f"guide_page.html has tokens nothing fills: {sorted(set(left))}")
    payload = {"examples": {"pass": passing, "fail": failing}, "markup": data["markup"]}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).replace("<", "\\u003c")  # no raw "<" in the block
    return template.replace("__DATA__", blob)
