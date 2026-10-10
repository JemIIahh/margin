from margin import telemetry


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("NEATLOGS_API_KEY", raising=False)
    assert telemetry.init_telemetry("margin", ["arm:A"]) is False


def test_trace_is_a_noop_when_disabled():
    with telemetry.trace("x", kind="TOOL", **{"margin.n": 1}) as sp:
        sp.set_attribute("margin.y", "z")


def test_span_decorator_passes_through():
    @telemetry.span(kind="TOOL", name="f")
    def f(a, b=2):
        return a + b

    assert f(1) == 3


def test_coerce_attribute_values():
    assert telemetry.coerce(True) is True
    assert telemetry.coerce(3) == 3
    assert telemetry.coerce("s") == "s"
    assert telemetry.coerce(0.123456789) == "0.123457"
    assert telemetry.coerce({"a": 1}) == '{"a": 1}'
