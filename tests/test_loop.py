import pytest

from fakes import FakeExecutor, ScriptedClient, reply, text, tool_use
from margin.agent.loop import run_agent
from margin.agent.tools import ToolOutput
from margin.config import ROOT, Settings
from margin.errors import SimulatedCrash, TransientModelError
from margin.governor import Governor, NullGovernor
from margin.pricing import PriceTable, SpendMeter
from margin.state import RunState

PRICES = PriceTable.load(ROOT / "pricing.toml")


def go(tmp_path, replies, *, governor=None, settings=None, arm="A", resume=None, hook=None, meter=None, state=None, client=None):
    client = client or ScriptedClient(replies)
    meter = meter or SpendMeter(PRICES)
    state = state or RunState(tmp_path / "run")
    sleeps = []
    result = run_agent(
        first_prompt="FIRST", arm=arm, client=client, meter=meter, governor=governor or NullGovernor(),
        executor=FakeExecutor(), state=state, prices=PRICES, settings=settings or Settings(),
        resume=resume, sleep=sleeps.append, after_turn_hook=hook,
    )
    return result, client, meter, state, sleeps


def test_tool_turn_then_finish(tmp_path):
    replies = [
        reply([text("looking"), tool_use("t1", "read_file", {"path": "a.py"})], stop="tool_use"),
        reply([text("done")]),
    ]
    result, client, meter, state, _ = go(tmp_path, replies)
    assert result.stop == "end_turn" and result.turns == 2
    assert result.final_text == "done"
    second = client.calls[1]["messages"]
    assert second[-1]["content"] == [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]
    assert second[-2]["content"][1] == {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.py"}}
    assert meter.total_usd > 0
    assert len(state.events("model_usage")) == 2


def test_request_parameters_follow_the_model_rules(tmp_path):
    _, client, *_ = go(tmp_path, [reply([text("x")])])
    params = client.calls[0]
    assert params["model"] == "claude-sonnet-5-5"
    assert params["output_config"] == {"effort": "medium"}
    assert "temperature" not in params and "thinking" not in params
    assert [t["name"] for t in params["tools"]][:2] == ["read_file", "search_code"]
    assert params["messages"] == [{"role": "user", "content": "FIRST"}]


def test_tool_errors_are_marked_on_the_result(tmp_path):
    ex = FakeExecutor()
    ex.execute = lambda name, args: ToolOutput("boom", True)
    client = ScriptedClient([reply([tool_use("t1", "read_file", {})], stop="tool_use"), reply([text("ok")])])
    run_agent(
        first_prompt="F", arm="A", client=client, meter=SpendMeter(PRICES), governor=NullGovernor(), executor=ex,
        state=RunState(tmp_path / "r"), prices=PRICES, settings=Settings(), sleep=lambda s: None,
    )
    assert client.calls[1]["messages"][-1]["content"][0]["is_error"] is True


def test_abort_before_the_first_call_when_the_cap_is_tiny(tmp_path):
    result, client, *_ = go(tmp_path, [], governor=Governor(cap_usd=0.0001))
    assert result.stop == "abort" and client.calls == []
    assert "cap" in result.abort_reason


def test_downgrade_restarts_on_haiku_from_a_digest(tmp_path):
    replies = [
        reply([tool_use("t1", "read_file", {"path": "a"})], stop="tool_use", input_tokens=100_000, output_tokens=45_000),
        reply([text("done")]),
    ]
    result, client, *_ = go(tmp_path, replies, governor=Governor(cap_usd=1.0))
    assert result.stop == "end_turn"
    assert client.calls[0]["model"] == "claude-sonnet-5-5"
    second = client.calls[1]
    assert second["model"] == "claude-haiku-5-5"
    assert second["output_config"] == {"effort": "low"}
    assert len(second["messages"]) == 1 and "DIFF" in second["messages"][0]["content"]
    assert [e["rung"] for e in result.rung_events] == ["DOWNGRADE"]


def test_narrow_adds_a_notice_then_caps_the_turns(tmp_path):
    cheap = {"input_tokens": 100, "output_tokens": 10}
    replies = [
        reply([tool_use("t1", "read_file", {"path": "a"})], stop="tool_use", input_tokens=100_000, output_tokens=70_000),
        reply([tool_use("t2", "read_file", {"path": "a"})], stop="tool_use", **cheap),
    ]
    settings = Settings(narrow_turns=1)
    result, client, *_ = go(tmp_path, replies, governor=Governor(cap_usd=1.0), settings=settings)
    assert result.stop == "narrow_exhausted"
    last_block = client.calls[1]["messages"][-1]["content"][-1]
    assert last_block["type"] == "text" and "Budget notice" in last_block["text"]
    assert [e["rung"] for e in result.rung_events] == ["NARROW"]


def test_transient_errors_are_retried_with_backoff(tmp_path):
    replies = [TransientModelError("529"), TransientModelError("529"), reply([text("ok")])]
    result, _client, _, state, sleeps = go(tmp_path, replies)
    assert result.stop == "end_turn"
    assert len(state.events("retry")) == 2
    assert sleeps == [1, 2]


def test_non_transient_error_ends_the_run_with_an_error_result(tmp_path):
    result, *_ = go(tmp_path, [ValueError("boom")])
    assert result.stop == "error" and "boom" in result.abort_reason


def test_refusal_stops_the_run(tmp_path):
    result, *_ = go(tmp_path, [reply([text("no")], stop="refusal")])
    assert result.stop == "refusal"


def test_max_tokens_gets_a_continue_nudge(tmp_path):
    replies = [reply([text("cut")], stop="max_tokens"), reply([text("done")])]
    result, client, *_ = go(tmp_path, replies)
    assert result.stop == "end_turn"
    assert "cut off" in client.calls[1]["messages"][-1]["content"]


def test_max_turns_is_enforced(tmp_path):
    replies = [reply([tool_use(f"t{i}", "read_file", {"path": "a"})], stop="tool_use") for i in range(5)]
    result, *_ = go(tmp_path, replies, settings=Settings(max_turns=3))
    assert result.stop == "max_turns" and result.turns == 3


def test_hard_cap_aborts_ungoverned_runs(tmp_path):
    replies = [reply([tool_use("t1", "read_file", {"path": "a"})], stop="tool_use", input_tokens=2_000_000)] * 3
    result, *_ = go(tmp_path, replies, settings=Settings(run_hard_cap_usd=1.0))
    assert result.stop == "abort" and result.abort_reason == "hard cap"


def test_resume_after_a_crash_matches_an_uninterrupted_run(tmp_path):
    def script():
        return [
            reply([tool_use("t1", "read_file", {"path": "a"})], stop="tool_use"),
            reply([tool_use("t2", "read_file", {"path": "b"})], stop="tool_use"),
            reply([text("done")]),
        ]

    full, _, full_meter, *_ = go(tmp_path / "full", script())

    def crash(turn):
        if turn == 1:
            raise SimulatedCrash()

    state = RunState(tmp_path / "crashy" / "run")
    with pytest.raises(SimulatedCrash):
        go(tmp_path, script(), state=state, hook=crash)
    checkpoint = state.load_checkpoint()
    assert checkpoint["turn"] == 1
    meter = SpendMeter(PRICES)
    state.restore_meter(meter)
    resumed, *_ = go(tmp_path, script()[1:], resume=checkpoint, meter=meter, state=state)
    assert resumed.messages == full.messages
    assert meter.total_usd == pytest.approx(full_meter.total_usd)
