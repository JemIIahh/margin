from types import SimpleNamespace

import pytest

from margin.config import ROOT
from margin.pricing import PriceTable, SpendMeter, Usage


@pytest.fixture(scope="module")
def prices():
    return PriceTable.load(ROOT / "pricing.toml")


def test_sonnet_cost_all_components(prices):
    u = Usage(input_tokens=1000, output_tokens=2000, cache_write_tokens=500, cache_read_tokens=10_000)
    # (1000*2.00 + 2000*10.00 + 500*2.50 + 10_000*0.10) / 1e6; cache reads are $0.10 on Sonnet 5.5
    assert prices.cost("claude-sonnet-5-5", u) == pytest.approx(0.02425)


def test_haiku_long_prompt_multiplier_applies_above_threshold(prices):
    u = Usage(input_tokens=150_000, output_tokens=1000)
    assert prices.cost("claude-haiku-5-5", u) == pytest.approx(0.0775)


def test_haiku_at_threshold_is_not_long(prices):
    u = Usage(input_tokens=100_000, output_tokens=1000)
    assert prices.cost("claude-haiku-5-5", u) == pytest.approx((100_000 * 0.10 + 1000 * 0.50) / 1e6)


def test_unknown_model_raises(prices):
    with pytest.raises(KeyError, match="no price for model"):
        prices.cost("nope", Usage())


def test_usage_from_api_handles_none_fields():
    api = SimpleNamespace(
        input_tokens=10, output_tokens=5, cache_creation_input_tokens=None, cache_read_input_tokens=None
    )
    assert Usage.from_api(api) == Usage(10, 5, 0, 0)


def test_estimate_next_call_assumes_warm_cache(prices):
    est = prices.estimate_next_call("claude-sonnet-5-5", prompt_tokens=100_000, expected_output_tokens=4000)
    assert est == pytest.approx(100_000 * 0.10 / 1e6 + 4000 * 10 / 1e6)


def test_meter_accumulates_per_model(prices):
    m = SpendMeter(prices)
    m.record("claude-sonnet-5-5", Usage(input_tokens=1_000_000))
    m.record("claude-haiku-5-5", Usage(output_tokens=1_000_000))
    assert m.total_usd == pytest.approx(2.0 + 0.5)
    assert m.total_tokens == 2_000_000
    assert set(m.usage_by_model) == {"claude-sonnet-5-5", "claude-haiku-5-5"}


def test_usage_add_and_roundtrip():
    a, b = Usage(1, 2, 3, 4), Usage(10, 20, 30, 40)
    assert a + b == Usage(11, 22, 33, 44)
    assert Usage.from_dict(a.to_dict()) == a
