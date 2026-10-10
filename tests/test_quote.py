import math

import pytest

from margin.ledger import Ledger
from margin.quote import (
    DEFAULT_Q,
    MIN_Q,
    Features,
    Quote,
    Quoter,
    count_python_loc,
    evaluate_loo,
    extract_features,
    training_rows,
)
from test_ledger import rec


def feat(i=100, f=3, loc=1000, s=2.0):
    return Features(i, f, loc, s)


def test_features_roundtrip_and_vector_is_log_scaled():
    f = feat()
    assert Features.from_dict(f.to_dict()) == f
    assert f.vector()[0] == pytest.approx(math.log1p(100))


def test_empty_ledger_uses_the_prior_with_a_finite_band():
    q = Quoter([], prior_cost=1.0).quote(feat())
    assert q.p50 == 1.0
    assert 0 < q.lo < q.p50 < q.hi < float("inf")
    assert q.hi == pytest.approx(math.exp(DEFAULT_Q))


def test_all_equal_costs_give_a_minimum_width_band():
    rows = [(feat(i=100 + 10 * k), 2.0) for k in range(6)]
    q = Quoter(rows).quote(feat())
    assert q.p50 == 2.0
    assert q.hi == pytest.approx(2.0 * math.exp(MIN_Q))
    assert q.lo == pytest.approx(2.0 * math.exp(-MIN_Q))


def test_few_rows_use_the_median_of_all_of_them():
    rows = [(feat(i=100), 1.0), (feat(i=5000), 9.0), (feat(i=120), 3.0)]
    assert Quoter(rows).quote(feat(i=110)).p50 == 3.0


def test_the_nearest_three_neighbours_drive_the_estimate():
    small = [(feat(i=100 + k, f=2, loc=500, s=1.0), 0.2) for k in range(5)]
    large = [(feat(i=3000 + k, f=40, loc=50_000, s=30.0), 4.0) for k in range(5)]
    quoter = Quoter(small + large)
    assert quoter.quote(feat(i=102, f=2, loc=500, s=1.0)).p50 == pytest.approx(0.2)
    assert quoter.quote(feat(i=3002, f=40, loc=50_000, s=30.0)).p50 == pytest.approx(4.0)


def test_price_applies_the_markup_to_the_upper_bound():
    assert Quote(1.0, 0.5, 2.0).price(0.5) == pytest.approx(3.0)


def test_zero_costs_do_not_break_the_logarithms():
    rows = [(feat(i=100 + k), 0.0) for k in range(6)]
    q = Quoter(rows).quote(feat())
    assert q.p50 > 0 and q.lo < q.hi


def test_evaluate_loo_is_out_of_sample_and_self_consistent():
    rows = [(f"t{k}", feat(i=100 + 50 * k), 0.01 * (100 + 50 * k)) for k in range(10)]
    results = evaluate_loo(rows)
    assert [r.task_id for r in results] == [f"t{k}" for k in range(10)]
    for r in results:
        assert r.inside == (r.quote.lo <= r.actual <= r.quote.hi)
        assert r.quote.lo < r.quote.hi
        assert r.abs_log_error >= 0


def test_evaluate_loo_with_identical_costs_is_fully_covered():
    rows = [(f"t{k}", feat(i=100 + 50 * k), 2.0) for k in range(8)]
    assert all(r.inside for r in evaluate_loo(rows))


def test_evaluate_loo_with_one_row_still_returns_a_result():
    (only,) = evaluate_loo([("t", feat(), 1.5)], prior_cost=1.0)
    assert only.quote.p50 == 1.0


def test_count_python_loc_ignores_tests(repo):
    assert count_python_loc(repo) == 2


def test_extract_features_uses_the_graph_for_impact(repo):
    class Graph:
        def impact_size(self, issue):
            return 7

    f = extract_features("x" * 400, repo, 2.5, Graph())
    assert (f.issue_tokens, f.impact_files, f.baseline_seconds) == (100, 7, 2.5)


def test_training_rows_use_arm_b_rows_with_features_and_exclude_the_current_task(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(rec(run_id="1", task="a", arm="B", cost=1.0, features=feat().to_dict()))
    ledger.append(rec(run_id="2", task="b", arm="B", cost=2.0, features=feat(i=500).to_dict()))
    ledger.append(rec(run_id="3", task="c", arm="B", cost=3.0))                              # no features: skipped
    ledger.append(rec(run_id="4", task="d", arm="A", cost=4.0, features=feat().to_dict()))  # wrong arm: skipped
    assert training_rows(ledger, exclude="b") == [(feat(), 1.0)]
