"""Arm E: arm D plus Jev (TypeSafe's System One model) as a cheap judge: intake gate, progress judge, lesson picker."""
from types import SimpleNamespace

import pytest

from fakes import FakeExecutor, ScriptedClient, reply, text, tool_use
from margin.agent.loop import run_agent
from margin.config import ROOT, Settings
from margin.governor import NullGovernor
from margin.pricing import PriceTable, SpendMeter
from margin.state import RunState

PRICES = PriceTable.load(ROOT / "pricing.toml")
COACH = "claude-sonnet-4.6"


class FakeJevClient:
    """Answers every Noul from a table (default 0.5) and reports 1,000 input tokens per call."""

    def __init__(self, values=None, fail=False):
        self.values, self.fail, self.calls = values or {}, fail, []

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        if self.fail:
            raise RuntimeError("jev unavailable")
        nouls = {name: SimpleNamespace(noul=self.values.get(name, 0.5)) for name in questions}
        return SimpleNamespace(nouls=nouls, usage=SimpleNamespace(input_tokens=1000))


def go(tmp_path, replies, jev_values=None, *, fail=False, settings=None):
    from margin.jev import Jev, ProgressJudge

    client = ScriptedClient(replies)
    jev_client = FakeJevClient(jev_values, fail)
    state = RunState(tmp_path / "run")
    meter = SpendMeter(PRICES)
    result = run_agent(
        first_prompt="FIRST", arm="E", client=client, meter=meter, governor=NullGovernor(), executor=FakeExecutor(),
        state=state, prices=PRICES, settings=settings or Settings(coach_model=COACH, coach_stall_turns=50),
        sleep=lambda s: None, judge=ProgressJudge(Jev(jev_client)),
    )
    return result, client, jev_client, state, meter


def reads(n):
    return [reply([tool_use(f"t{i}", "read_file", {"path": str(i)})], stop="tool_use") for i in range(n)]


# --- the Jev wrapper --------------------------------------------------------------------------------------------------
def test_jev_returns_probabilities_and_what_the_call_cost():
    from margin.jev import Jev

    answers = Jev(FakeJevClient({"a": 0.9})).nouls("state", {"a": "Is it?", "b": "Is it not?"})
    assert answers.nouls == {"a": 0.9, "b": 0.5}
    assert answers.input_tokens == 1000 and answers.cost_usd == pytest.approx(1000 * 0.042 / 1_000_000)


def test_jev_never_breaks_the_caller():
    from margin.jev import Jev

    assert Jev(FakeJevClient(fail=True)).nouls("state", {"a": "Is it?"}) is None


def test_arm_e_without_a_typesafe_key_says_so(monkeypatch):
    from margin.jev import JevUnavailable, make_jev

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(JevUnavailable, match="TYPESAFE_API_KEY"):
        make_jev()


# --- the progress judge in the loop -----------------------------------------------------------------------------------
def test_when_jev_judges_the_run_stuck_the_coach_is_called_without_waiting_for_the_stall_rule(tmp_path):
    note = reply([text("Next step: edit the parser.")])
    replies = [*reads(3), note, *reads(1), reply([text("done")])]
    result, client, jev_client, state, _meter = go(tmp_path, replies, {"progress": 0.05, "repeating": 0.9, "ready_to_edit": 0.1})
    assert sum(c["model"] == COACH for c in client.calls) == 1
    assert result.rung_events[0]["rung"] == "COACH" and "Jev" in result.rung_events[0]["reason"]
    assert any(e["model"] == "jev-latest" for e in state.events("model_usage"))
    assert jev_client.calls and "recent_actions" in jev_client.calls[0][0]


def test_when_jev_sees_progress_no_coach_is_called(tmp_path):
    replies = [*reads(6), reply([text("done")])]
    result, client, *_ = go(tmp_path, replies, {"progress": 0.9, "repeating": 0.05, "ready_to_edit": 0.1})
    assert not any(c["model"] == COACH for c in client.calls) and result.rung_events == []


def test_when_jev_says_the_agent_knows_enough_it_gets_a_free_nudge_to_edit(tmp_path):
    replies = [*reads(5), reply([text("done")])]
    _result, client, *_ = go(tmp_path, replies, {"progress": 0.9, "repeating": 0.05, "ready_to_edit": 0.95})
    assert not any(c["model"] == COACH for c in client.calls)
    sent = str(client.calls[-1]["messages"])
    assert "Edit the code now" in sent


def test_if_jev_is_down_arm_e_falls_back_to_the_stall_rule(tmp_path):
    note = reply([text("Next step: edit the parser.")])
    replies = [*reads(2), note, *reads(1), reply([text("done")])]
    settings = Settings(coach_model=COACH, coach_stall_turns=2)
    result, client, *_ = go(tmp_path, replies, fail=True, settings=settings)
    assert sum(c["model"] == COACH for c in client.calls) == 1
    assert "no progress in 2 turns" in result.rung_events[0]["reason"]


# --- the lesson picker -----------------------------------------------------------------------------------------------
def test_jev_picks_the_lessons_that_fit_this_issue_and_falls_back_to_the_first_ones():
    from margin.jev import Jev, pick_lessons

    candidates = ["About grouping.", "About comments.", "About keywords.", "About whitespace."]
    jev = Jev(FakeJevClient({"l0": 0.2, "l1": 0.95, "l2": 0.4, "l3": 0.7}))
    assert pick_lessons("issue", candidates, jev, limit=3) == ["About comments.", "About whitespace."]
    assert pick_lessons("issue", candidates, Jev(FakeJevClient(fail=True)), limit=2) == ["About grouping.", "About comments."]
    assert pick_lessons("issue", [], jev, limit=3) == []


# --- arm E in the CLI and in execute_run ------------------------------------------------------------------------------
def test_arm_e_and_the_intake_commands_parse():
    from margin.cli import build_parser

    p = build_parser()
    assert p.parse_args(["run", "--task", "x", "--arm", "E"]).arm == "E"
    assert p.parse_args(["bench", "--arm", "E"]).arm == "E"
    assert p.parse_args(["intake-eval", "--split", "calibration"]).split == "calibration"


def test_arm_e_gates_a_benchmark_run_but_other_arms_still_need_a_demo_version(tmp_path):
    from fakes import ScriptedClient as Client
    from margin.run import execute_run
    from test_run_intake import FakeGate
    from test_tasks import make_task, settings_for

    task, settings = make_task(tmp_path), settings_for(tmp_path)
    declined = execute_run(task, "E", settings, tasks_root=tmp_path, client=Client([]), gate=FakeGate("decline"),
                           run_id="r-e", version="v4-jev")
    assert not declined.solved and declined.abort_reason.startswith("declined at intake")
    with pytest.raises(ValueError, match="demo"):
        execute_run(task, "C", settings, tasks_root=tmp_path, client=Client([]), gate=FakeGate("accept"),
                    run_id="r-c", version="v4-jev")
