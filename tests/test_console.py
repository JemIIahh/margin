import json
import re

import pytest

from margin.bench.console import (
    CAP_GRID,
    build_replay,
    cli_lines,
    console_data,
    load_links,
    load_replays,
    load_task_meta,
    neighbours,
    parse_verdict,
    quote_check,
    read_events,
    reading,
    receipt_parts,
    render_console,
    simulate_cap,
    step_changes,
)
from margin.cli import main
from margin.ledger import Ledger, render_receipt
from margin.quote import Features, Quoter, training_rows
from test_ledger import rec
from test_results import FLAT, build_ledger, feat

EVENTS = [
    {"type": "features", "t": 1},
    {"type": "quote", "lo": 0.1, "p50": 0.2, "hi": 0.3},
    {"type": "tool_call", "name": "before_any_model_call"},
    {"type": "model_usage", "cost": 0.01, "model": "big"},
    {"type": "tool_call", "name": "read_file"},
    {"type": "tool_call", "name": "run_tests"},
    {"type": "model_usage", "cost": 0.02, "model": "big"},
    {"type": "rung", "turn": 2, "rung": "DOWNGRADE", "spend": 0.03,
     "reason": "no progress at 60% of the cap, see /Users/someone/work/repo/file.py"},
    {"type": "retry", "error": "APITimeoutError"},
    {"type": "model_usage", "cost": 0.005, "model": "small"},
    {"type": "recovery", "kind": "flaky_rerun"},
    {"type": "features", "t": 2},
]


def test_replay_accumulates_spend_and_attaches_tools_to_their_call():
    replay = build_replay(EVENTS)
    assert [t["cum"] for t in replay["turns"]] == [0.01, 0.03, 0.035]
    assert [t["model"] for t in replay["turns"]] == ["big", "big", "small"]
    assert replay["turns"][0]["tools"] == ["read_file", "run_tests"]
    assert all("before_any_model_call" not in t["tools"] for t in replay["turns"])


def test_replay_marks_governor_steps_retries_recoveries_and_a_restart():
    marks = build_replay(EVENTS)["marks"]
    assert [(m["kind"], m["after"]) for m in marks] == [
        ("downgrade", 2), ("retry", 2), ("recovery", 3), ("resume", 3),
    ]
    assert marks[0]["spend"] == 0.03 and "60% of the cap" in marks[0]["note"]


def test_replay_publishes_no_absolute_paths():
    assert "/Users/" not in json.dumps(build_replay(EVENTS))


def test_a_single_features_event_is_not_a_restart():
    assert build_replay(EVENTS[:2])["marks"] == []


def test_read_events_skips_a_line_cut_off_by_a_kill(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"type": "model_usage", "cost": 1, "model": "m"}\n{"type": "mod')
    assert [e["type"] for e in read_events(path)] == ["model_usage"]


def test_load_replays_names_the_runs_it_has_no_log_for(tmp_path):
    (tmp_path / "have").mkdir()
    (tmp_path / "have" / "events.jsonl").write_text(json.dumps(EVENTS[3]) + "\n")
    replays, missing = load_replays(tmp_path, ["have", "gone"])
    assert list(replays) == ["have"] and missing == ["gone"]


def fake_replays(ledger):
    return {r.run_id: {"turns": [{"cost": 0.1, "cum": 0.1, "model": "m", "tools": []}], "marks": []}
            for r in ledger.rows()}


def test_console_data_has_a_row_per_evaluation_task_and_the_arm_summaries(tmp_path):
    ledger = build_ledger(tmp_path)
    data = console_data(ledger, FLAT, fake_replays(ledger))
    assert data["n"] == 2 and data["flat_price"] == 3.0
    assert [j["task"] for j in data["jobs"]["C"]] == ["e1", "e2"]
    assert data["jobs"]["C"][0]["quote"] == {"lo": 0.8, "p50": 1.2, "hi": 1.6}
    assert data["jobs"]["A"][0]["quote"] is None
    c = data["summaries"]["C"]
    assert (c["verified"], c["capped"], c["over_cap"], c["highest_cost"]) == (2, 2, 0, 1.0)
    assert data["summaries"]["A"]["cost_total_usd"] == 4.0
    assert data["coverage"]["n"] == 4


def test_console_data_counts_a_job_that_finished_over_its_cap(tmp_path):
    ledger = build_ledger(tmp_path)
    ledger.append(rec(run_id="Cover", task="e1", arm="C", cost=1.7, price=2.4,
                      quote={"p50": 1.2, "lo": 0.8, "hi": 1.6}))
    assert console_data(ledger, FLAT, fake_replays(ledger))["summaries"]["C"]["over_cap"] == 1


def test_console_data_labels_failure_drills_and_leaves_them_out_of_the_comparison(tmp_path):
    ledger = build_ledger(tmp_path)
    ledger.append(rec(run_id="drill", task="e1", arm="C", cost=0.5, price=2.4, recoveries=1,
                      quote={"p50": 1.2, "lo": 0.8, "hi": 1.6}, trace_tags=["arm:C", "version:demo-fault-timeout"]))
    data = console_data(ledger, FLAT, fake_replays(ledger))
    assert [(d["run_id"], d["label"]) for d in data["demos"]] == [("drill", "The test run times out")]
    assert data["summaries"]["C"]["n"] == 2
    assert "drill" in data["replays"]


def test_console_data_keeps_only_the_replays_the_page_shows(tmp_path):
    ledger = build_ledger(tmp_path)
    replays = {**fake_replays(ledger), "stray": {"turns": [], "marks": []}}
    shown = console_data(ledger, FLAT, replays)["replays"]
    assert "stray" not in shown and "C0" in shown


def test_reading_says_why_arm_c_runs_did_not_verify(tmp_path):
    ledger = build_ledger(tmp_path)
    ledger.append(rec(run_id="Clost", task="e1", arm="C", solved=False, cost=0.4, price=2.4,
                      quote={"p50": 1.2, "lo": 0.8, "hi": 1.6}, abort_reason="turn limit reached",
                      rung_events=[{"turn": 3, "rung": "DOWNGRADE", "reason": "no progress"}]))
    lines = reading(console_data(ledger, FLAT, fake_replays(ledger))["summaries"], 2)
    text = " ".join(lines)
    assert "did not verify 1 of 2" in text and "1 ran into the turn limit and 0 were stopped by the cap" in text
    assert "1 had already been moved to the cheaper model" in text


def test_reading_counts_a_cap_stop_separately_from_the_turn_limit(tmp_path):
    ledger = build_ledger(tmp_path)
    ledger.append(rec(run_id="Ccap", task="e1", arm="C", solved=False, cost=1.6, price=2.4,
                      quote={"p50": 1.2, "lo": 0.8, "hi": 1.6}, abort_reason="hard cap"))
    text = " ".join(reading(console_data(ledger, FLAT, fake_replays(ledger))["summaries"], 2))
    assert "0 ran into the turn limit and 1 were stopped by the cap" in text


def payload(page: str) -> dict:
    match = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.DOTALL)
    return json.loads(match.group(1))


def test_the_page_embeds_the_data_and_is_deterministic(tmp_path):
    ledger = build_ledger(tmp_path)
    data = console_data(ledger, FLAT, fake_replays(ledger))
    page = render_console(data)
    assert page == render_console(data)
    assert payload(page) == data
    assert "__DATA__" not in page


def test_a_task_id_cannot_break_out_of_the_data_block(tmp_path):
    ledger = build_ledger(tmp_path)
    evil = "</script><script>alert(1)</script>"
    ledger.append(rec(run_id="evil", task=evil, arm="C", cost=1.0, price=2.4,
                      quote={"p50": 1.2, "lo": 0.8, "hi": 1.6}))
    page = render_console(console_data(ledger, FLAT, fake_replays(ledger)))
    assert evil not in page and "<script>alert(1)" not in page
    assert re.search(r'id="data">(.*?)</script>', page, re.DOTALL).group(1).count("<") == 0
    assert evil in [j["task"] for j in payload(page)["jobs"]["C"]]


def test_the_page_makes_no_requests_and_never_writes_html_from_data(tmp_path):
    page = render_console(console_data(build_ledger(tmp_path), FLAT, {}))
    for forbidden in ("<link", " src=", "@import", "fetch(", "XMLHttpRequest", "innerHTML", "outerHTML",
                      "insertAdjacentHTML", "document.write", "eval(", "<img", "<iframe"):
        assert forbidden not in page, forbidden
    assert "prefers-reduced-motion" in page and 'data-palette="black"' in page and "white" in page


def test_links_file_is_optional_and_only_keeps_label_and_href(tmp_path):
    assert load_links(tmp_path / "none.json") == []
    path = tmp_path / "links.json"
    path.write_text(json.dumps([{"label": "Repo", "href": "https://example.com/r", "extra": 1}]))
    assert load_links(path) == [{"label": "Repo", "href": "https://example.com/r"}]


def test_links_with_a_script_scheme_are_dropped(tmp_path):
    path = tmp_path / "links.json"
    path.write_text(json.dumps([{"label": "x", "href": "javascript:alert(1)"}, {"label": "ok", "href": "../a.md"}]))
    assert load_links(path) == [{"label": "ok", "href": "../a.md"}]


def write_runs(tmp_path, ledger):
    runs = tmp_path / "runs"
    for row in ledger.rows():
        (runs / row.run_id).mkdir(parents=True)
        (runs / row.run_id / "events.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in EVENTS[3:7])
        )
    return runs


def cli_args(tmp_path, ledger):
    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps(FLAT))
    layout = tmp_path / "report.toml"
    layout.write_text("[headline]\n")  # no pinned versions: use each arm's latest, whatever the repo's own report.toml says
    return ["--ledger", str(ledger.path), "--flat", str(flat), "--layout", str(layout)]


def test_snapshot_then_console_writes_then_checks_the_page(tmp_path):
    ledger = build_ledger(tmp_path)
    runs = write_runs(tmp_path, ledger)
    base = cli_args(tmp_path, ledger)
    replays, page = tmp_path / "replays.json", tmp_path / "console.html"
    assert main(["snapshot-replays", *base, "--runs-dir", str(runs), "--out", str(replays)]) == 0
    assert set(json.loads(replays.read_text())) == {"A2", "A3", "B2", "B3", "C0", "C1"}
    console = ["console", *base, "--replays", str(replays), "--out", str(page)]
    assert main(console) == 0 and page.exists()
    assert main([*console, "--check"]) == 0
    page.write_text(page.read_text() + "tampered")
    assert main([*console, "--check"]) == 1


def test_snapshot_replays_refuses_when_a_shown_run_has_no_event_log(tmp_path, capsys):
    ledger = build_ledger(tmp_path)
    runs = write_runs(tmp_path, ledger)
    (runs / "C0" / "events.jsonl").unlink()
    args = ["snapshot-replays", *cli_args(tmp_path, ledger), "--runs-dir", str(runs), "--out", str(tmp_path / "r.json")]
    assert main(args) == 1
    assert "C0" in capsys.readouterr().out and not (tmp_path / "r.json").exists()


@pytest.mark.parametrize("missing", ["flat", "replays"])
def test_console_says_what_to_run_when_an_input_is_missing(tmp_path, capsys, missing):
    ledger = build_ledger(tmp_path)
    args = cli_args(tmp_path, ledger)
    if missing == "flat":
        args[3] = str(tmp_path / "nope.json")
    out = ["--replays", str(tmp_path / "none.json"), "--out", str(tmp_path / "c.html")]
    assert main(["console", *args, *out]) == 1
    assert ("calibrate-flat" if missing == "flat" else "snapshot-replays") in capsys.readouterr().out


def test_parse_verdict_reads_the_three_kinds_and_keeps_paths_out():
    assert parse_verdict(rec(solved=True, verdict_reason="solved")) == {"kind": "solved", "detail": ""}
    target = parse_verdict(rec(solved=False, verdict_reason="target tests still failing: tests.a::b, tests.c::d"))
    assert target == {"kind": "target", "detail": "tests.a::b, tests.c::d"}
    broke = parse_verdict(
        rec(solved=False, verdict_reason="new failures vs baseline (failed, skipped or missing): tests.x::y[file://]")
    )
    assert broke == {"kind": "regression", "detail": "tests.x::y[file://]"}
    other = parse_verdict(rec(solved=False, verdict_reason="harness error in /Users/someone/work/x.py"))
    assert other["kind"] == "other" and "/Users/" not in other["detail"]


def test_simulate_cap_stops_before_the_call_that_would_pass_the_cap():
    cum = [0.02, 0.05, 0.09, 0.14]
    assert simulate_cap(cum, 0.2) == (0.14, False)
    assert simulate_cap(cum, 0.14) == (0.14, False)
    assert simulate_cap(cum, 0.1) == (0.09, True)
    assert simulate_cap(cum, 0.01) == (0.0, True)
    assert simulate_cap([], 1.0) == (0.0, False)


def test_console_data_precomputes_where_each_run_would_end_under_every_cap(tmp_path):
    ledger = build_ledger(tmp_path)
    replays = fake_replays(ledger)
    replays["C0"] = {"turns": [{"cost": 0.5, "cum": c, "model": "m", "tools": []} for c in (0.5, 1.0, 1.5, 2.0)], "marks": []}
    data = console_data(ledger, FLAT, replays)
    assert set(data["capfx"]) == {"C"}  # only a version that quotes a price has a cap
    fx = data["capfx"]["C"]["e1"]
    assert len(fx) == len(CAP_GRID) == len(data["cap_grid"])
    assert fx[CAP_GRID.index(1.0)] == [1.5, True]  # the cap is the quoted top, 1.6
    assert fx[CAP_GRID.index(1.5)] == [2.0, False]  # a cap of 2.4 lets the whole run finish
    assert data["governor"] == {"downgrade_at": 0.6, "narrow_at": 0.85, "max_turns": 30}


def quoted_ledger(tmp_path):
    """Six arm B jobs and an arm C job whose stored quote came from those jobs, as the harness stores it."""
    ledger = Ledger(tmp_path / "quoted.jsonl")
    for i, cost in enumerate([0.05, 0.08, 0.12, 0.2, 0.3, 0.09]):
        features = Features(100 + 30 * i, 2 + i, 5000 + 500 * i, 2.0).to_dict()
        ledger.append(rec(run_id=f"B{i}", task=f"t{i}", arm="B", cost=cost, price=0.0, features=features))
    features = Features(150, 4, 5200, 2.0)
    quote = Quoter(training_rows(ledger, exclude="t9")).quote(features)
    ledger.append(rec(run_id="C9", task="t9", arm="C", cost=0.1, price=quote.price(0.5), features=features.to_dict(),
                      quote={"p50": quote.p50, "lo": quote.lo, "hi": quote.hi}))
    return ledger


def test_neighbours_reproduce_the_stored_quote(tmp_path):
    ledger = quoted_ledger(tmp_path)
    row = ledger.latest("C")["t9"]
    found = neighbours(row, ledger)
    assert found["pool"] == 6 and len(found["picked"]) == 3
    assert sorted(p["cost"] for p in found["picked"])[1] == pytest.approx(row.quote["p50"], rel=1e-4)
    assert all(p["task"].startswith("t") for p in found["picked"])
    assert found["spread"] > 0


def test_neighbours_are_withheld_when_they_do_not_explain_the_stored_quote(tmp_path):
    ledger = quoted_ledger(tmp_path)
    row = ledger.latest("C")["t9"]
    row.quote = {**row.quote, "p50": row.quote["p50"] * 2}
    assert neighbours(row, ledger) is None
    assert neighbours(rec(arm="C", features={}), ledger) is None


def test_console_data_attaches_neighbours_and_verdicts_to_the_jobs(tmp_path):
    ledger = quoted_ledger(tmp_path)
    ledger.append(rec(run_id="Cx", task="t8", arm="C", solved=False, cost=0.1, price=0.3,
                      verdict_reason="target tests still failing: tests.a::b", features=Features(1, 1, 1, 1.0).to_dict(),
                      quote={"p50": 0.1, "lo": 0.05, "hi": 0.2}))
    data = console_data(ledger, {**FLAT, "flat_price_usd": 0.3}, fake_replays(ledger))
    assert [j["task"] for j in data["jobs"]["C"]] == ["t8", "t9"] and data["n"] == 2
    t9 = next(j for j in data["jobs"]["C"] if j["task"] == "t9")
    assert t9["neighbours"] is not None and t9["verdict"]["kind"] == "solved"
    t8 = next(j for j in data["jobs"]["C"] if j["task"] == "t8")
    assert t8["neighbours"] is None and t8["verdict"]["kind"] == "target"


def test_task_meta_reads_repo_issue_link_and_title(tmp_path):
    (tmp_path / "bench" / "issues").mkdir(parents=True)
    (tmp_path / "bench" / "issues" / "a-1.md").write_text("# `Thing` breaks when empty\n\nbody text")
    manifest = tmp_path / "tasks.toml"
    manifest.write_text(
        '[[task]]\nid = "a-1"\nrepo = "https://github.com/o/r"\nissue_url = "https://github.com/o/r/issues/1"\n'
        'issue_file = "bench/issues/a-1.md"\n\n[[task]]\nid = "a-2"\nrepo = "https://github.com/o/s.git"\n'
        'issue_url = "u"\nissue_file = "bench/issues/missing.md"\n'
    )
    meta = load_task_meta(manifest, tmp_path)
    assert meta["a-1"] == {"repo": "o/r", "issue_url": "https://github.com/o/r/issues/1", "title": "`Thing` breaks when empty"}
    assert meta["a-2"]["repo"] == "o/s" and meta["a-2"]["title"] == ""
    assert load_task_meta(tmp_path / "none.toml", tmp_path) == {}


def test_jobs_carry_the_issue_title_from_the_manifest(tmp_path):
    ledger = build_ledger(tmp_path)
    meta = {"e1": {"repo": "o/r", "issue_url": "https://github.com/o/r/issues/1", "title": "It breaks"}}
    jobs = console_data(ledger, FLAT, fake_replays(ledger), meta=meta)["jobs"]["C"]
    assert (jobs[0]["title"], jobs[0]["repo"]) == ("It breaks", "o/r") and jobs[1]["title"] == ""


@pytest.mark.parametrize("href", [
    "javascript:alert(1)", "javascript:alert(1)//x", "data:text/html,hi", "//evil.example/x", "vbscript:x", "",
])
def test_links_with_a_script_or_scheme_relative_href_are_dropped(tmp_path, href):
    path = tmp_path / "links.json"
    path.write_text(json.dumps([{"label": "x", "href": href}, {"label": "ok", "href": "https://example.com/a"}]))
    assert [item["label"] for item in load_links(path)] == ["ok"]


def test_cli_lines_use_the_commands_own_formats(tmp_path):
    ledger = quoted_ledger(tmp_path)
    row = ledger.latest("C")["t9"]
    lines = cli_lines(row, ledger)
    q = row.quote
    assert lines["quote"] == (
        f"t9: cost band ${q['lo']:.4f} - ${q['hi']:.4f} (p50 ${q['p50']:.4f}) from 6 past runs; price ${row.price_usd:.4f}"
    )
    assert lines["run"] == f"C9: solved=True cost=$0.1000 margin=${row.margin_usd:.4f}"
    assert lines["receipt_path"] == "runs/C9/receipt.md"


def test_flat_priced_runs_print_no_quote_and_a_margin_of_minus_the_cost(tmp_path):
    """Arms A and B were priced at zero while they ran, so `margin run` printed the cost with a minus sign."""
    ledger = quoted_ledger(tmp_path)
    lines = cli_lines(ledger.latest("B")["t0"], ledger)
    assert lines["quote"] is None and lines["run"] == "B0: solved=True cost=$0.0500 margin=$-0.0500"


def test_receipt_parts_match_the_receipt_the_harness_writes(tmp_path):
    ledger = quoted_ledger(tmp_path)
    row = ledger.latest("C")["t9"]
    row.rung_events = [{"turn": 4, "rung": "DOWNGRADE", "reason": "no progress at 60% of the cap"}]
    row.abort_reason = "turn limit reached"
    row.verdict_reason = "solved"
    written = render_receipt(row).replace("**", "").splitlines()
    parts = receipt_parts(row)
    assert written[0] == "# " + parts["title"]
    assert [line for line in written if line.startswith("- ") and not line.startswith("- turn")] == [
        f"- {label}: {value}" for label, value in parts["items"]
    ]
    assert [line[2:] for line in written if line.startswith("- turn")] == parts["governor"]


def test_receipt_parts_say_when_the_price_is_set_at_report_time(tmp_path):
    ledger = quoted_ledger(tmp_path)
    parts = receipt_parts(ledger.latest("B")["t0"])
    assert parts["items"][0] == ["Quoted cost band", "none (flat price)"] and "report time" in parts["note"]
    assert receipt_parts(ledger.latest("C")["t9"])["note"] == ""


def test_receipts_published_on_the_page_carry_no_absolute_paths(tmp_path):
    ledger = quoted_ledger(tmp_path)
    row = ledger.latest("C")["t9"]
    row.verdict_reason = "new failures vs baseline: /Users/someone/work/tests/x.py::t"
    row.rung_events = [{"turn": 1, "rung": "NARROW", "reason": "see /home/me/secret"}]
    assert "/Users/" not in json.dumps(receipt_parts(row)) and "/home/" not in json.dumps(receipt_parts(row))


def test_console_data_gives_every_job_its_cli_lines_and_receipt(tmp_path):
    ledger = build_ledger(tmp_path)
    data = console_data(ledger, FLAT, fake_replays(ledger))
    for arm in "ABC":
        for job in data["jobs"][arm]:
            assert job["cli"]["run"].startswith(job["run_id"]) and job["receipt"]["items"]


def summary(verified, margin, cpv, highest, n=12):
    return {"verified": verified, "n": n, "gross_margin": margin, "cost_per_verified": cpv, "highest_cost": highest}


def test_step_changes_format_before_after_and_say_which_way_is_better():
    steps = step_changes({"A": summary(8, 0.128, 0.26, 0.303), "B": summary(11, 0.636, 0.109, 0.206),
                          "C": summary(9, 0.629, 0.129, 0.176)})
    assert [(s["from"], s["to"]) for s in steps] == [("A", "B"), ("B", "C")]
    ab = {r["label"]: r for r in steps[0]["rows"]}
    assert ab["Fixes verified"] == {"label": "Fixes verified", "from": "8 of 12", "to": "11 of 12", "delta": "+3", "better": "yes"}
    assert ab["Cost per verified fix"]["delta"] == "\u221258%" and ab["Cost per verified fix"]["better"] == "yes"
    bc = {r["label"]: r for r in steps[1]["rows"]}
    assert bc["Fixes verified"]["delta"] == "\u22122" and bc["Fixes verified"]["better"] == "no"
    assert bc["Most any one job cost"]["better"] == "yes" and bc["Cost per verified fix"]["better"] == "no"


def test_step_changes_margin_points_are_the_difference_of_the_shown_percentages():
    rows = step_changes({"A": summary(8, 0.128, 0.26, 0.3), "B": summary(11, 0.636, 0.1, 0.2)})[0]["rows"]
    margin = next(r for r in rows if r["label"] == "Margin")
    assert (margin["from"], margin["to"], margin["delta"]) == ("13%", "64%", "+51 pts")


def test_step_changes_skip_a_step_when_a_version_is_missing():
    assert step_changes({"A": summary(8, 0.1, 0.2, 0.3)}) == []
    assert [s["to"] for s in step_changes({"B": summary(11, 0.6, 0.1, 0.2), "C": summary(9, 0.6, 0.1, 0.2)})] == ["C"]


def test_quote_check_matches_the_coverage_the_page_states(tmp_path):
    ledger = build_ledger(tmp_path)
    check = quote_check(ledger)
    data = console_data(ledger, FLAT, fake_replays(ledger))
    assert len(check) == data["coverage"]["n"] == 4
    assert sum(q["inside"] for q in check) == data["coverage"]["covered"]
    assert all(q["lo"] <= q["p50"] <= q["hi"] for q in check)
    assert data["quote_check"] == check and len(data["changes"]) == 2


COACHED_EVENTS = [
    {"type": "intake", "decision": "accept", "injection": 0.06, "actionable": 0.98, "cost_usd": 0.00004},
    {"type": "lessons", "count": 3},
    {"type": "features", "t": 1},
    {"type": "model_usage", "cost": 0.01, "model": "small", "role": "worker"},
    {"type": "tool_call", "name": "read_file"},
    {"type": "model_usage", "cost": 0.02, "model": "small", "role": "worker"},
    {"type": "judge", "progress": 0.3},
    {"type": "rung", "turn": 2, "rung": "COACH", "spend": 0.03,
     "reason": 'Jev judged the run stuck: {"progress": 0.31, "repeating": 0.7, "ready_to_edit": 0.2}'},
    {"type": "model_usage", "cost": 0.04, "model": "big", "role": "coach"},
    {"type": "coach", "note": "Diagnosis: look in parse.py\nthen edit it"},
    {"type": "nudge"},
    {"type": "model_usage", "cost": 0.01, "model": "small", "role": "worker"},
    {"type": "model_usage", "cost": 0.001, "model": "jev", "role": "judge"},
]


def test_replay_counts_only_worker_calls_as_turns_but_all_spend_as_cost():
    turns = build_replay(COACHED_EVENTS)["turns"]
    assert [t["model"] for t in turns] == ["small", "small", "small"]
    # intake 0.00004 is billed to the job; the coach's 0.04 lands on the next turn; the judge's 0.001 after the last turn
    assert [t["cum"] for t in turns] == pytest.approx([0.01004, 0.03004, 0.08104])


def test_replay_marks_intake_lessons_coach_and_nudge_with_the_coachs_note():
    marks = {m["kind"]: m for m in build_replay(COACHED_EVENTS)["marks"]}
    assert [m["kind"] for m in build_replay(COACHED_EVENTS)["marks"]] == ["intake", "lessons", "coach", "nudge"]
    assert marks["intake"]["note"] == "accept: injection 0.06, actionable 0.98"
    assert marks["lessons"]["note"] == "3 lessons"
    assert marks["coach"]["detail"] == "Diagnosis: look in parse.py" and marks["coach"]["cost"] == 0.04
    assert marks["coach"]["after"] == 2 and marks["nudge"]["after"] == 2


def test_a_judges_probabilities_are_written_as_words_not_json():
    note = next(m for m in build_replay(COACHED_EVENTS)["marks"] if m["kind"] == "coach")["note"]
    assert note == "Jev judged the run stuck (progress 0.31, repeating 0.70, ready to edit 0.20)"
    assert "{" not in note


def version_ledger(tmp_path):
    ledger = build_ledger(tmp_path)
    for arm, cost in (("D", 0.9), ("E", 0.8)):
        for n, task in enumerate(["e1", "e2"]):
            ledger.append(rec(run_id=f"{arm}{n}", task=task, arm=arm, cost=cost, price=2.4,
                              quote={"p50": 1.2, "lo": 0.8, "hi": 1.6}, features=feat(180 + 40 * n)))
    return ledger


def test_console_data_covers_versions_d_and_e(tmp_path):
    ledger = version_ledger(tmp_path)
    data = console_data(ledger, FLAT, fake_replays(ledger))
    assert list(data["arms"]) == ["A", "B", "C", "D", "E"] and data["arms"]["E"]["name"]
    assert [j["run_id"] for j in data["jobs"]["E"]] == ["E0", "E1"]
    assert set(data["capfx"]) == {"C", "D", "E"} and set(data["capfx"]["E"]) == {"e1", "e2"}
    assert [(s["from"], s["to"]) for s in data["changes"]] == [("A", "B"), ("B", "C"), ("C", "D"), ("D", "E")]


def test_reading_describes_versions_d_and_e(tmp_path):
    ledger = version_ledger(tmp_path)
    text = " ".join(reading(console_data(ledger, FLAT, fake_replays(ledger))["summaries"], 2))
    assert "Version D" in text and "Version E, where Jev decides when to coach" in text and "level with version D" in text
