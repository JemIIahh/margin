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


def test_record_failure_opens_a_span_that_sees_the_error_and_does_not_leak_it(monkeypatch):
    """With telemetry on, the failed span must close with the exception (so neatlogs marks it errored),
    while the caller, which has already recovered, must never see it."""
    import contextlib
    import sys
    import types

    seen = []

    @contextlib.contextmanager
    def fake_trace(name, kind=None):
        span = types.SimpleNamespace(set_attribute=lambda k, v: seen.append(("attr", k, v)))
        try:
            yield span
        except BaseException as exc:  # a real span records the error, then re-raises it
            seen.append(("error", name, kind, str(exc)))
            raise

    monkeypatch.setitem(sys.modules, "neatlogs", types.SimpleNamespace(trace=fake_trace))
    monkeypatch.setattr(telemetry, "_enabled", True)
    telemetry.record_failure("failed:model_call", "overloaded")  # must not raise
    assert ("error", "failed:model_call", "TOOL", "overloaded") in seen
    assert ("attr", "margin.detail", "overloaded") in seen
