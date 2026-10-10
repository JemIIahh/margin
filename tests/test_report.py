import pytest

from margin.bench.report import apply_flat_price, calibrate_flat_price, compare_table, summarize
from test_ledger import rec


def test_summarize_three_runs():
    rows = [
        rec(run_id="1", task="a", solved=True, cost=1.0, price=2.0),
        rec(run_id="2", task="b", solved=True, cost=2.0, price=2.0),
        rec(run_id="3", task="c", solved=False, cost=1.0, price=2.0),
    ]
    s = summarize(rows)
    assert s["n"] == 3
    assert s["solve_rate"] == pytest.approx(2 / 3)
    assert s["profitable_share"] == pytest.approx(1 / 3)   # margins 1.0, 0.0, -1.0
    assert s["gross_margin"] == pytest.approx(0.0)         # revenue 4.0, cost 4.0
    assert s["wasted_spend_usd"] == pytest.approx(1.0)
    assert s["tokens_per_solved"] == pytest.approx(1000)
    assert s["cost_total_usd"] == pytest.approx(4.0)


def test_summarize_empty_and_no_revenue():
    assert summarize([])["n"] == 0
    s = summarize([rec(solved=False, cost=1.0, price=2.0)])
    assert s["gross_margin"] is None and s["tokens_per_solved"] is None


def test_calibrate_flat_price_uses_only_calibration_runs():
    rows = {
        "a": rec(task="a", cost=1.0), "b": rec(task="b", cost=3.0), "c": rec(task="c", cost=100.0),
    }
    rows["a"].split = rows["b"].split = "calibration"
    result = calibrate_flat_price(rows, markup=0.5)
    assert result["mean_cost_usd"] == pytest.approx(2.0)
    assert result["flat_price_usd"] == pytest.approx(3.0)
    assert result["n"] == 2


def test_calibrate_flat_price_requires_calibration_runs():
    with pytest.raises(ValueError, match="no arm A calibration"):
        calibrate_flat_price({"c": rec(task="c")}, markup=0.5)


def test_apply_flat_price_only_reprices_arms_a_and_b():
    rows = [rec(arm="A", cost=1.0, price=0.0), rec(arm="B", cost=1.0, price=0.0, solved=False),
            rec(arm="C", cost=1.0, price=9.0)]
    a, b, c = apply_flat_price(rows, 3.0)
    assert (a.price_usd, a.revenue_usd, a.margin_usd) == (3.0, 3.0, 2.0)
    assert (b.price_usd, b.revenue_usd, b.margin_usd) == (3.0, 0.0, -1.0)
    assert c.price_usd == 9.0


def test_compare_table_orders_arms_and_marks_missing_values():
    table = compare_table({"B": summarize([rec(solved=False)]), "A": summarize([rec()])})
    lines = table.splitlines()
    assert lines[0].startswith("| Arm") and lines[2].startswith("| A") and lines[3].startswith("| B")
    assert "n/a" in lines[3]
