import pytest

from fakes import FakeExecutor, ScriptedClient, reply, text
from margin import telemetry
from margin.agent.loop import run_agent
from margin.config import ROOT, Settings
from margin.errors import TransientModelError
from margin.faults import FAULTS, FaultInjector
from margin.governor import NullGovernor
from margin.pricing import PriceTable, SpendMeter
from margin.sandbox import SuiteTimeout
from margin.state import RunState
from margin.verify import SuiteRun
from test_tools import make_executor

PRICES = PriceTable.load(ROOT / "pricing.toml")


def test_unknown_fault_kind_is_rejected():
    with pytest.raises(ValueError):
        FaultInjector("nope")
    assert set(FAULTS) == {"api_overload", "flaky_tests", "tool_timeout"}


def test_api_overload_fails_twice_then_clears():
    fault = FaultInjector("api_overload")
    for _ in range(2):
        with pytest.raises(TransientModelError):
            fault.before_model_call()
    fault.before_model_call()


def test_tool_timeout_fires_once():
    fault = FaultInjector("tool_timeout")
    with pytest.raises(SuiteTimeout):
        fault.before_tests()
    fault.before_tests()


def test_flaky_tests_flips_one_unprotected_passing_test_once():
    fault = FaultInjector("flaky_tests")
    run = SuiteRun(frozenset({"a::t1", "a::t2"}), frozenset())
    flipped = fault.corrupt_run(run, protect={"a::t1"})
    assert flipped.failed == frozenset({"a::t2"}) and flipped.passed == frozenset({"a::t1"})
    assert fault.corrupt_run(run, protect=set()) == run


def test_no_fault_changes_nothing():
    fault = FaultInjector(None)
    fault.before_model_call()
    fault.before_tests()
    run = SuiteRun(frozenset({"a::t1"}), frozenset())
    assert fault.corrupt_run(run) == run


def test_the_flaky_fault_is_cleared_by_the_rerun(sandbox, tmp_path):
    state = RunState(tmp_path / "s")
    executor = make_executor(sandbox, tmp_path, faults=FaultInjector("flaky_tests"), state=state)
    out = executor.execute("run_tests", {})
    assert "New failures vs baseline: none" in out.text
    assert [e["kind"] for e in state.events("recovery")] == ["flaky_rerun"]


def test_a_test_timeout_falls_back_to_the_target_tests(sandbox, tmp_path):
    state = RunState(tmp_path / "s")
    executor = make_executor(sandbox, tmp_path, faults=FaultInjector("tool_timeout"), state=state)
    out = executor.execute("run_tests", {})
    assert "Target tests: 1 failing of 1" in out.text
    assert [e["kind"] for e in state.events("recovery")] == ["tool_timeout"]


def test_api_overload_is_retried_inside_the_loop(tmp_path):
    state = RunState(tmp_path / "s")
    sleeps = []
    result = run_agent(
        first_prompt="F", arm="A", client=ScriptedClient([reply([text("ok")])]), meter=SpendMeter(PRICES),
        governor=NullGovernor(), executor=FakeExecutor(), state=state, prices=PRICES, settings=Settings(),
        faults=FaultInjector("api_overload"), sleep=sleeps.append,
    )
    assert result.stop == "end_turn" and sleeps == [1, 2] and len(state.events("retry")) == 2


def test_record_failure_is_a_noop_when_telemetry_is_off():
    assert telemetry.record_failure("failed:x", "boom") is None
