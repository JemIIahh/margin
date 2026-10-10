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


from fakes import install_fake_neatlogs as _fake_neatlogs


def test_a_span_an_exception_passes_through_is_marked_failed_and_the_exception_still_propagates(monkeypatch):
    """neatlogs.trace is a bare try/finally (verified in the installed SDK and against the live service: the span
    ended SUCCESS), so the shim must mark failures itself or no recovery would ever look like a failure."""
    import pytest

    spans = _fake_neatlogs(monkeypatch)
    with pytest.raises(RuntimeError, match="boom"), telemetry.trace("injected-failure", kind="TOOL"):
        raise RuntimeError("boom")
    span = spans[0]
    assert span.status is not None and span.status.status_code.name == "ERROR"
    assert [str(e) for e in span.exceptions] == ["boom"]
    assert span.attrs["error"] is True and "boom" in span.attrs["error.message"]


def test_a_span_that_completes_normally_is_not_marked_failed(monkeypatch):
    spans = _fake_neatlogs(monkeypatch)
    with telemetry.trace("ok", kind="TOOL"):
        pass
    assert spans[0].status is None and "error" not in spans[0].attrs


def test_marking_a_failure_never_breaks_the_run_if_the_span_cannot_take_it(monkeypatch):
    import contextlib
    import sys
    import types

    import pytest

    @contextlib.contextmanager
    def bare_trace(name, kind=None):
        yield types.SimpleNamespace(set_attribute=lambda k, v: (_ for _ in ()).throw(RuntimeError("span closed")))

    monkeypatch.setitem(sys.modules, "neatlogs", types.SimpleNamespace(trace=bare_trace))
    monkeypatch.setattr(telemetry, "_enabled", True)
    with pytest.raises(ValueError, match="the real error"), telemetry.trace("x", kind="TOOL"):  # caller sees ITS error
        raise ValueError("the real error")
