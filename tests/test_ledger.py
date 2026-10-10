import pytest

from margin.ledger import Ledger, RunRecord, render_receipt, settle


def rec(run_id="r1", task="t1", arm="A", solved=True, cost=1.0, price=1.5, **kw):
    revenue, margin = settle(price, solved, cost)
    return RunRecord(
        run_id=run_id, task_id=task, arm=arm, split="evaluation", solved=solved, cost_usd=cost,
        price_usd=price, revenue_usd=revenue, margin_usd=margin, tokens_total=1000, **kw,
    )


def test_settle_pays_only_for_verified_fixes():
    assert settle(1.5, True, 1.0) == (1.5, 0.5)
    assert settle(1.5, False, 1.0) == (0.0, -1.0)


def test_append_and_read_roundtrip(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(rec(features={"issue_tokens": 10}, quote={"p50": 1.0, "lo": 0.5, "hi": 2.0}))
    rows = ledger.rows()
    assert len(rows) == 1
    assert rows[0].features == {"issue_tokens": 10}
    assert rows[0].quote["hi"] == 2.0


def test_latest_keeps_last_row_per_task_and_filters_arm(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(rec(run_id="r1", task="t1", arm="A", cost=1.0))
    ledger.append(rec(run_id="r2", task="t1", arm="A", cost=2.0))
    ledger.append(rec(run_id="r3", task="t1", arm="B", cost=3.0))
    latest = ledger.latest("A")
    assert set(latest) == {"t1"}
    assert latest["t1"].run_id == "r2"


def test_latest_ignores_fault_and_demo_runs(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(rec(run_id="real", task="t1", arm="C", cost=1.0))
    ledger.append(rec(run_id="fault", task="t1", arm="C", cost=9.0, fault="flaky_tests"))
    ledger.append(rec(run_id="demo", task="t1", arm="C", cost=9.0, trace_tags=["version:demo-x"]))
    assert ledger.latest("C")["t1"].run_id == "real"


def test_truncated_last_line_is_skipped_with_a_warning(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append(rec(run_id="ok"))
    with path.open("a") as f:
        f.write('{"run_id": "cut", "task_id": ')
    with pytest.warns(UserWarning, match="unreadable ledger line"):
        rows = ledger.rows()
    assert [r.run_id for r in rows] == ["ok"]


def test_missing_file_reads_as_empty(tmp_path):
    assert Ledger(tmp_path / "nope.jsonl").rows() == []


def test_receipt_shows_quote_verdict_and_margin():
    r = rec(
        quote={"p50": 1.0, "lo": 0.5, "hi": 2.0},
        rung_events=[{"turn": 3, "rung": "DOWNGRADE", "reason": "no progress at 60% of cap"}],
        verdict_reason="solved",
    )
    text = render_receipt(r)
    assert "$0.5000 – $2.0000" in text
    assert "DOWNGRADE" in text
    assert "verified" in text
    assert "$0.5000" in text  # margin


def test_receipt_for_flat_priced_failure():
    text = render_receipt(rec(solved=False, abort_reason="over budget", verdict_reason="target tests still failing"))
    assert "none (flat price)" in text
    assert "not verified" in text
    assert "over budget" in text


def test_a_record_appended_after_a_torn_line_is_not_lost(tmp_path):
    import pytest

    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(rec(run_id="r1"))
    with ledger.path.open("a") as f:
        f.write('{"run_id": "r2", "task_')            # the process was killed mid-write: no newline
    ledger.append(rec(run_id="r3"))
    with pytest.warns(UserWarning):
        rows = ledger.rows()
    assert [r.run_id for r in rows] == ["r1", "r3"]


def test_latest_ignores_infrastructure_failures_but_they_stay_in_the_ledger_as_spend(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(rec(run_id="ok", task="t1", arm="A", cost=1.0))
    ledger.append(rec(run_id="bad", task="t1", arm="A", cost=0.25, solved=False, infra_error=True))   # a later row
    assert ledger.latest("A")["t1"].run_id == "ok"
    assert [r.run_id for r in ledger.rows()] == ["ok", "bad"]


def test_a_receipt_says_when_a_run_failed_for_infrastructure_reasons():
    from margin.ledger import render_receipt

    text = render_receipt(rec(solved=False, infra_error=True))
    assert "infrastructure" in text.lower() and "not a benchmark result" in text.lower()
