"""The Margin console: one static, interactive page that shows the money story from recorded runs.

Everything on the page comes from files that are committed: the ledger snapshot, a replay snapshot (each run's
turns, built from its event log) and the task manifest. The page embeds them as JSON and draws with plain DOM:
no framework, no network requests, nothing to install. All dynamic text is inserted with textContent.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from margin.bench.report import apply_flat_price, quote_coverage, summarize
from margin.config import Settings
from margin.ledger import Ledger, RunRecord
from margin.quote import COLD_START_MIN, Features, K, Quoter, evaluate_loo, training_rows

PAGE = Path(__file__).with_name("console_page.html")
ARMS = ("A", "B", "C", "D", "E")
ARM_NAMES = {
    "A": "Flat price", "B": "Adds code-graph context", "C": "Adds a quote and a cap",
    "D": "Adds a coach and lessons", "E": "Jev decides when to coach",
}
DEMO_LABELS = {
    "demo-fault-timeout": "The test run times out",
    "demo-fault-flaky": "A test fails by chance",
    "demo-fault-overload": "The model API is overloaded",
    "demo-resume": "The run is killed, then resumed",
}
CAP_GRID = [round(0.5 + 0.05 * i, 2) for i in range(21)]  # the cap as a share of the quoted top: 50% to 150%
_PATH = re.compile(r"/(?:Users|home|private|var|tmp)/[^\s'\")]+")
_TURN_LIMIT = "turn limit reached"
_CAP_STOPS = ("hard cap", "narrowed budget used up")


def _clean(text: str) -> str:
    """Replays are published: keep reasons and names, drop any absolute path that slipped into one."""
    return _PATH.sub("<path>", str(text))


def _reason(text: str) -> str:
    """A governor reason in words: Jev's judgement arrives as a JSON object of probabilities."""
    text = _clean(text)
    head, brace, tail = text.partition("{")
    if not brace:
        return text
    try:
        scores = json.loads("{" + tail)
    except ValueError:
        return text
    if not isinstance(scores, dict):
        return text
    words = ", ".join(f"{str(k).replace('_', ' ')} {float(v):.2f}" for k, v in scores.items() if isinstance(v, int | float))
    return f"{head.strip().rstrip(':')} ({words})" if words else head.strip()


def _first_line(text: str, limit: int = 170) -> str:
    line = _clean(text).strip().splitlines()[0] if str(text).strip() else ""
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "\u2026"


def build_replay(events: Iterable[dict]) -> dict:
    """Turns, tool calls and governor marks from one run's event log.

    Only the worker's calls are turns. A coach call, Jev's intake screening or a Jev judgement costs money but is not a
    turn, so its cost goes into the running total and into the next turn's `cum`. A second `features` event means the process restarted:
    `margin resume` extracts the features again.
    """
    turns: list[dict] = []
    marks: list[dict] = []
    spent = 0.0
    seen_features = False
    last_coach_cost = 0.0
    for e in events:
        kind = e.get("type")
        if kind == "features":
            if seen_features:
                marks.append({"after": len(turns), "kind": "resume", "spend": round(spent, 6), "note": "restart"})
            seen_features = True
        elif kind == "model_usage":
            spent += float(e["cost"])
            role = e.get("role", "worker")
            if role == "worker":
                turns.append({"cost": round(float(e["cost"]), 6), "cum": round(spent, 6), "model": e["model"], "tools": []})
            elif role == "coach":
                last_coach_cost = float(e["cost"])
        elif kind == "tool_call" and turns:
            turns[-1]["tools"].append(str(e["name"]))
        elif kind == "rung":
            marks.append({"after": int(e["turn"]), "kind": str(e["rung"]).lower(), "spend": round(float(e["spend"]), 6),
                          "note": _reason(e.get("reason", ""))})
        elif kind == "coach":
            target = next((m for m in reversed(marks) if m["kind"] == "coach" and "detail" not in m), None)
            if target is not None:
                target["detail"] = _first_line(e.get("note", ""))
                target["cost"] = round(last_coach_cost, 6)
        elif kind == "nudge":
            marks.append({"after": len(turns), "kind": "nudge", "spend": round(spent, 6), "note": "ready to edit"})
        elif kind == "intake":
            spent += float(e.get("cost_usd", 0.0))  # Jev's screening call is billed to the job like any other
            marks.append({"after": 0, "kind": "intake", "spend": round(spent, 6), "note": (
                f"{e.get('decision', '?')}: injection {float(e.get('injection', 0)):.2f}, "
                f"actionable {float(e.get('actionable', 0)):.2f}")})
        elif kind == "lessons":
            marks.append({"after": 0, "kind": "lessons", "spend": 0.0, "note": f"{int(e.get('count', 0))} lessons"})
        elif kind == "retry":
            marks.append({"after": len(turns), "kind": "retry", "spend": round(spent, 6),
                          "note": _clean(str(e.get("error", "")))[:80]})
        elif kind == "recovery":
            marks.append({"after": len(turns), "kind": "recovery", "spend": round(spent, 6),
                          "note": _clean(str(e.get("kind", "")))[:80]})
    if turns and abs(turns[-1]["cum"] - spent) > 5e-7:
        turns[-1]["cum"] = round(spent, 6)  # spend on a side call after the last turn still counts toward the job
    return {"turns": turns, "marks": marks}


def read_events(path: Path) -> list[dict]:
    """Tolerant of a killed process: a cut-off last line is skipped."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def load_replays(runs_dir: Path, run_ids: Iterable[str]) -> tuple[dict[str, dict], list[str]]:
    replays: dict[str, dict] = {}
    missing: list[str] = []
    for run_id in run_ids:
        path = Path(runs_dir) / run_id / "events.jsonl"
        if path.exists():
            replays[run_id] = build_replay(read_events(path))
        else:
            missing.append(run_id)
    return replays, missing


def load_task_meta(tasks_path: Path, root: Path) -> dict[str, dict]:
    """Repository, issue link and issue title per task. The title is the first heading of the issue file."""
    tasks_path = Path(tasks_path)
    if not tasks_path.exists():
        return {}
    meta = {}
    for task in tomllib.loads(tasks_path.read_text(encoding="utf-8")).get("task", []):
        repo = re.sub(r"^https?://github\.com/", "", str(task.get("repo", ""))).removesuffix(".git")
        title = ""
        issue_file = Path(root) / str(task.get("issue_file", ""))
        if task.get("issue_file") and issue_file.exists():
            first = issue_file.read_text(encoding="utf-8").lstrip().splitlines()[:1]
            title = re.sub(r"^#+\s*", "", first[0]).strip() if first else ""
        meta[str(task["id"])] = {"repo": repo, "issue_url": str(task.get("issue_url", "")), "title": title}
    return meta


def parse_verdict(row: RunRecord) -> dict:
    """What the verifier said, in three kinds: it passed, a target test still fails, or a test that passed broke."""
    reason = row.verdict_reason or ""
    if row.solved:
        return {"kind": "solved", "detail": ""}
    if reason.startswith("target tests still failing"):
        return {"kind": "target", "detail": _clean(reason.partition(":")[2].strip())[:240]}
    if reason.startswith("new failures vs baseline"):
        return {"kind": "regression", "detail": _clean(reason.partition(":")[2].strip())[:240]}
    return {"kind": "other", "detail": _clean(reason)[:240]}


def neighbours(row: RunRecord, ledger: Ledger, version: str | None = None) -> dict | None:
    """The past jobs a quote was learned from, in the order the quoter ranks them.

    Re-derived from the same arm B rows the quoter uses, and only returned when their median reproduces the
    quote stored on the run: a page that explains a quote must not explain a different one. The distance is the
    quoter's own (a private method, since it has no public one): if `quote.py` changes, this returns None.
    """
    if not (row.quote and row.features):
        return None
    pool = [
        (task_id, Features.from_dict(b.features), b.cost_usd)
        for task_id, b in ledger.latest("B", version).items()
        if task_id != row.task_id and b.features
    ]
    if not pool:
        return None
    quoter = Quoter([(f, cost) for _, f, cost in pool])
    vector = Features.from_dict(row.features).vector()
    ranked = sorted((quoter._distance(vector, f.vector()), i) for i, (_, f, _) in enumerate(pool))
    chosen = ranked if len(pool) < COLD_START_MIN else ranked[:K]
    picked = [{"task": pool[i][0], "cost": round(pool[i][2], 6)} for _, i in chosen]
    median = statistics.median(p["cost"] for p in picked)
    if not math.isclose(median, row.quote["p50"], rel_tol=1e-4):
        return None
    return {"picked": picked, "pool": len(pool), "spread": round(math.log(row.quote["hi"] / row.quote["p50"]), 4)}


def simulate_cap(cum: list[float], cap: float) -> tuple[float, bool]:
    """Where a run would have ended under `cap`, from its recorded cumulative spend.

    It stops before the first call that would carry spend past the cap. Returns (cost, stopped).
    """
    if not cum or cum[-1] <= cap + 1e-12:
        return (cum[-1] if cum else 0.0, False)
    spent = [c for c in cum if c <= cap + 1e-12]
    return (spent[-1] if spent else 0.0, True)


def cli_lines(row: RunRecord, ledger: Ledger) -> dict:
    """What `margin quote` and `margin run` print for this run, in the commands' own formats.

    Arms A and B were priced at zero while they ran (the flat price is set at report time), so the margin the command
    printed was minus the cost.
    """
    quote = None
    if row.quote:
        past = len(training_rows(ledger, exclude=row.task_id))
        quote = (
            f"{row.task_id}: cost band ${row.quote['lo']:.4f} - ${row.quote['hi']:.4f} (p50 ${row.quote['p50']:.4f}) "
            f"from {past} past runs; price ${row.price_usd:.4f}"
        )
    margin = -row.cost_usd if row.arm in ("A", "B") else row.margin_usd
    run = f"{row.run_id}: solved={row.solved} cost=${row.cost_usd:.4f} margin=${margin:.4f}"
    return {"quote": quote, "run": run, "receipt_path": f"runs/{row.run_id}/receipt.md"}


def receipt_parts(row: RunRecord) -> dict:
    """The receipt's fields in the order and wording of `render_receipt`, for the page to draw."""
    if row.quote:
        band = f"${row.quote['lo']:.4f} \u2013 ${row.quote['hi']:.4f} (p50 ${row.quote['p50']:.4f})"
    else:
        band = "none (flat price)"
    verdict = "verified" if row.solved else "not verified"
    items = [
        ["Quoted cost band", band],
        ["Price", f"${row.price_usd:.4f}"],
        ["Actual cost", f"${row.cost_usd:.4f} ({row.tokens_total} tokens)"],
        ["Verdict", f"{verdict} ({_clean(row.verdict_reason) or 'n/a'})"],
        ["Revenue", f"${row.revenue_usd:.4f}"],
        ["Margin", f"${row.margin_usd:.4f}"],
    ]
    if row.abort_reason:
        items.append(["Stopped early", _clean(row.abort_reason)])
    governor = [f"turn {e['turn']}: {e['rung']}: {_clean(e['reason'])}" for e in row.rung_events]
    flat = row.quote is None and row.arm in ("A", "B")
    return {
        "title": f"Receipt: {row.task_id} (arm {row.arm})", "items": items, "governor": governor,
        "note": "Flat price, set at report time from the arm A calibration runs." if flat else "",
    }


def _job(row: RunRecord, ledger: Ledger, meta: dict[str, dict], b_version: str | None = None) -> dict:
    quote = row.quote
    info = meta.get(row.task_id, {})
    return {
        "run_id": row.run_id, "task": row.task_id, "arm": row.arm, "solved": row.solved,
        "cost": round(row.cost_usd, 6), "price": round(row.price_usd, 6), "revenue": round(row.revenue_usd, 6),
        "margin": round(row.margin_usd, 6), "tokens": row.tokens_total,
        "quote": {k: round(quote[k], 6) for k in ("lo", "p50", "hi")} if quote else None,
        "rungs": [e["rung"] for e in row.rung_events], "timeouts": row.api_timeouts,
        "features": row.features or None, "verdict": parse_verdict(row),
        "stop": row.abort_reason if row.abort_reason == _TURN_LIMIT or row.abort_reason in _CAP_STOPS else None,
        "neighbours": neighbours(row, ledger, b_version) if row.quote else None,
        "cli": cli_lines(row, ledger), "receipt": receipt_parts(row),
        "repo": info.get("repo", ""), "issue_url": info.get("issue_url", ""), "title": info.get("title", ""),
    }


def _stopped_by_cap(row: RunRecord) -> bool:
    return any(e["rung"] == "ABORT" for e in row.rung_events) or row.abort_reason in _CAP_STOPS


def _summary(rows: list[RunRecord]) -> dict:
    base = summarize(rows)
    verified = [r for r in rows if r.solved]
    unverified = [r for r in rows if not r.solved]
    return {
        **base,
        "verified": len(verified),
        "profitable": sum(1 for r in rows if r.margin_usd > 0),
        "highest_cost": max((r.cost_usd for r in rows), default=0.0),
        "cost_per_verified": base["cost_total_usd"] / len(verified) if verified else None,
        "cost_verified_usd": sum(r.cost_usd for r in verified),
        "over_cap": sum(1 for r in rows if r.quote and r.cost_usd > r.quote["hi"] + 1e-9),
        "capped": sum(1 for r in rows if r.quote),
        "unverified": len(unverified),
        "unverified_turn_limit": sum(1 for r in unverified if r.abort_reason == _TURN_LIMIT),
        "unverified_by_cap": sum(1 for r in unverified if _stopped_by_cap(r)),
        "unverified_downgraded": sum(1 for r in unverified if any(e["rung"] == "DOWNGRADE" for e in r.rung_events)),
    }


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def reading(summaries: dict[str, dict], n: int) -> list[str]:
    """Plain statements of what the numbers say, including where the quote and cap did not help."""
    b, c = summaries.get("B"), summaries.get("C")
    if not (b and c):
        return []
    out = []
    if c["capped"]:
        out.append(f"Version C jobs that finished over their cap: {c['over_cap']} of {c['capped']}.")
    if c["unverified"]:
        out.append(
            f"Version C did not verify {c['unverified']} of {n}: {c['unverified_turn_limit']} ran into the turn "
            f"limit and {c['unverified_by_cap']} were stopped by the cap; {c['unverified_downgraded']} had already "
            "been moved to the cheaper model."
        )
    if b["verified"] > c["verified"]:
        out.append(f"Version B verified more issues than version C ({b['verified']} against {c['verified']}).")
    elif c["verified"] > b["verified"]:
        out.append(f"Version C verified more issues than version B ({c['verified']} against {b['verified']}).")
    d, e = summaries.get("D"), summaries.get("E")
    if d:
        out.append(
            f"Version D, which adds a coach, a stop once verified and lessons from past jobs, verified {d['verified']} of {n}, against "
            f"{c['verified']} for version C and {b['verified']} for version B."
        )
    if d and e:
        level = "level with" if e["verified"] == d["verified"] else f"against {d['verified']} for"
        out.append(f"Version E, where Jev decides when to coach, verified {e['verified']} of {n}, {level} version D.")
    return out


def _signed(value: float, suffix: str = "", digits: int = 0) -> str:
    sign = "+" if value > 0 else "\u2212" if value < 0 else ""
    return f"{sign}{abs(value):.{digits}f}{suffix}"


def step_changes(summaries: dict[str, dict]) -> list[dict]:
    """What each change between versions did, as formatted rows: A to B (code graph), B to C (quote and cap),
    C to D (coach, stop once verified, lessons) and D to E (Jev decides when to coach).

    `better` is "yes", "no" or "same", so the page can colour a change without knowing which direction is good.
    """
    steps = [
        ("A", "B", "Gave the agent a map of the code"),
        ("B", "C", "Added a quote and a spending cap"),
        ("C", "D", "Added a coach, a stop once verified and lessons"),
        ("D", "E", "Let Jev decide when to coach"),
    ]
    out = []
    for old, new, what in steps:
        a, b = summaries.get(old), summaries.get(new)
        if not (a and b):
            continue
        rows = []

        def add(label, fa, fb, delta, better, rows=rows):
            rows.append({"label": label, "from": fa, "to": fb, "delta": delta, "better": better})

        dv = b["verified"] - a["verified"]
        add("Fixes verified", f"{a['verified']} of {a['n']}", f"{b['verified']} of {b['n']}", _signed(dv),
            "same" if dv == 0 else "yes" if dv > 0 else "no")
        if a["gross_margin"] is not None and b["gross_margin"] is not None:
            dm = round(b["gross_margin"] * 100) - round(a["gross_margin"] * 100)  # from the shown figures, so the sum checks
            add("Margin", _pct(a["gross_margin"]), _pct(b["gross_margin"]), _signed(dm, " pts"),
                "same" if dm == 0 else "yes" if dm > 0 else "no")
        if a["cost_per_verified"] and b["cost_per_verified"]:
            dc = (b["cost_per_verified"] / a["cost_per_verified"] - 1) * 100
            add("Cost per verified fix", f"${a['cost_per_verified']:.3f}", f"${b['cost_per_verified']:.3f}",
                _signed(round(dc), "%"), "same" if round(dc) == 0 else "yes" if dc < 0 else "no")
        dh = (b["highest_cost"] / a["highest_cost"] - 1) * 100 if a["highest_cost"] else 0
        add("Most any one job cost", f"${a['highest_cost']:.3f}", f"${b['highest_cost']:.3f}", _signed(round(dh), "%"),
            "same" if round(dh) == 0 else "yes" if dh < 0 else "no")
        out.append({"from": old, "to": new, "what": what, "rows": rows})
    return out


def quote_check(ledger: Ledger, version: str | None = None) -> list[dict]:
    """Each recorded cost against the band it would have been quoted from the other jobs (leave-one-out)."""
    rows = sorted((r for r in ledger.latest("B", version).values() if r.features), key=lambda r: r.task_id)
    results = evaluate_loo([(r.task_id, Features.from_dict(r.features), r.cost_usd) for r in rows])
    return [
        {"task": r.task_id, "actual": round(r.actual, 6), "lo": round(r.quote.lo, 6), "p50": round(r.quote.p50, 6),
         "hi": round(r.quote.hi, 6), "inside": bool(r.inside)}
        for r in results
    ]


def console_data(
    ledger: Ledger, flat: dict, replays: dict[str, dict], links: list[dict] | None = None,
    meta: dict[str, dict] | None = None, layout: dict | None = None,
) -> dict:
    meta = meta or {}
    defaults = Settings()
    headline = (layout or {}).get("headline", {})  # the same pinned runs the results page reports
    latest = {arm: ledger.latest(arm, headline.get(arm)) for arm in ARMS}
    priced = {arm: apply_flat_price(rows.values(), flat["flat_price_usd"]) for arm, rows in latest.items()}
    evaluation = {
        arm: sorted((r for r in rows if r.split == "evaluation"), key=lambda r: r.task_id)
        for arm, rows in priced.items()
    }
    b_version = headline.get("B")
    jobs = {arm: [_job(r, ledger, meta, b_version) for r in rows] for arm, rows in evaluation.items()}
    summaries = {arm: _summary(rows) for arm, rows in evaluation.items() if rows}
    coverage = quote_coverage(sorted(latest["B"].values(), key=lambda r: r.task_id))
    n = len(evaluation["C"]) or max((len(v) for v in evaluation.values()), default=0)

    demos = []
    for row in ledger.rows("C"):
        version = next((t.split(":", 1)[1] for t in row.trace_tags if t.startswith("version:demo")), None)
        if version in DEMO_LABELS:
            demos.append({**_job(row, ledger, meta, b_version), "label": DEMO_LABELS[version], "recoveries": row.recoveries})
    used = {j["run_id"] for arm_jobs in jobs.values() for j in arm_jobs} | {d["run_id"] for d in demos}
    models = sorted({t["model"] for run_id in used for t in replays.get(run_id, {}).get("turns", [])})
    timeouts = sorted(
        (r.task_id, arm, r.api_timeouts) for arm, rows in evaluation.items() for r in rows if r.api_timeouts
    )
    capfx: dict[str, dict] = {}
    for arm in ARMS:
        for job in jobs[arm]:
            if job["quote"] and job["run_id"] in replays:
                cum = [t["cum"] for t in replays[job["run_id"]]["turns"]]
                capfx.setdefault(arm, {})[job["task"]] = [
                    [round(cost, 6), stopped]
                    for cost, stopped in (simulate_cap(cum, job["quote"]["hi"] * k) for k in CAP_GRID)
                ]
    return {
        "arms": {arm: {"name": ARM_NAMES[arm]} for arm in ARMS},
        "n": n,
        "flat_price": round(flat["flat_price_usd"], 6),
        "flat_mean_cost": round(flat.get("mean_cost_usd", 0.0), 6),
        "markup": flat.get("markup"),
        "jobs": jobs,
        "summaries": summaries,
        "reading": reading(summaries, n),
        "changes": step_changes(summaries),
        "quote_check": quote_check(ledger, b_version),
        "coverage": coverage,
        "models": models,
        "timeouts": [{"task": t, "arm": a, "n": k} for t, a, k in timeouts],
        "demos": demos,
        "replays": {run_id: replays[run_id] for run_id in sorted(used) if run_id in replays},
        "cap_grid": CAP_GRID,
        "capfx": capfx,
        "governor": {"downgrade_at": defaults.downgrade_at, "narrow_at": defaults.narrow_at, "max_turns": defaults.max_turns},
        "links": links or [],
    }


def render_console(data: dict) -> str:
    template = PAGE.read_text(encoding="utf-8")
    if template.count("__DATA__") != 1:
        raise ValueError("console_page.html must contain __DATA__ exactly once")
    # No raw "<" inside the data block: "</script>" and "<!--" cannot end or confuse it. JSON.parse reads < back.
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).replace("<", "\\u003c")
    return template.replace("__DATA__", payload)


def load_links(path: Path) -> list[dict[str, Any]]:
    """Optional, builder-maintained public links shown in the header: [{"label": ..., "href": ...}].

    Only http(s) links and relative paths are kept; any other scheme (javascript:, data:) is dropped.
    """
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for item in json.loads(path.read_text(encoding="utf-8")):
        href = str(item.get("href", ""))
        parts = urlsplit(href)
        if parts.scheme in ("http", "https") and parts.netloc or (not parts.scheme and not parts.netloc and href):
            out.append({"label": str(item["label"]), "href": href})
    return out
