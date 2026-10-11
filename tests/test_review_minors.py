"""The minor findings of the second fresh-context review, each reproduced before the fix."""
import contextlib
import json
import os
import signal
import subprocess
import time

import pytest

from fakes import FakeExecutor, ScriptedClient, reply, text, tool_use
from margin.agent.loop import run_agent
from margin.config import ROOT, Settings
from margin.governor import Governor
from margin.pricing import PriceTable, SpendMeter
from margin.state import RunState
from test_arm_e import FakeJevClient, go, reads

PRICES = PriceTable.load(ROOT / "pricing.toml")
COACH = "claude-sonnet-4.6"


# 1. the governor's 60% rung must leave a record even when the coach cannot take it
@pytest.mark.parametrize("why", ["coach notes used up", "fix already verifies"])
def test_the_downgrade_rung_is_logged_when_the_coach_does_not_step_in(tmp_path, why):
    executor = FakeExecutor()
    settings = Settings(coach_model=COACH)
    if why == "coach notes used up":
        settings = Settings(coach_model=COACH, coach_max_notes=0)
    else:
        executor.green = True
    replies = [
        reply([tool_use("t1", "read_file", {"path": "a"})], stop="tool_use", input_tokens=100_000, output_tokens=45_000),
        reply([text("done")]),
    ]
    result = run_agent(
        first_prompt="FIRST", arm="D", client=ScriptedClient(replies), meter=SpendMeter(PRICES),
        governor=Governor(cap_usd=1.0), executor=executor, state=RunState(tmp_path / "r"), prices=PRICES,
        settings=settings, sleep=lambda s: None,
    )
    assert [e["rung"] for e in result.rung_events] == ["DOWNGRADE"]


# 2. one failed Jev call is a blip; arm D's stall rule takes over only after several in a row
def test_the_stall_rule_waits_for_several_failed_judge_calls_in_a_row(tmp_path):
    note = reply([text("Next step: edit the parser.")])
    replies = [*reads(2), note, *reads(1), reply([text("done")])]
    settings = Settings(coach_model=COACH, coach_stall_turns=1, coach_max_notes=1, judge_warmup_turns=0, judge_fallback_after=3)
    result, _client, _jev, state, _meter = go(tmp_path, replies, fail=True, settings=settings)
    assert [(e["rung"], e["turn"]) for e in result.rung_events] == [("COACH", 2)]
    assert [e["consecutive"] for e in state.events("judge_unavailable")][:3] == [1, 2, 3]


# 3. a Jev reply without a usage figure is estimated, never metered as free
def test_a_jev_call_without_reported_usage_is_estimated_not_free():
    from margin.jev import Jev

    class NoUsage(FakeJevClient):
        def system_one(self, state, questions):
            result = super().system_one(state, questions)
            result.usage = None
            return result

    jev = Jev(NoUsage())
    answers = jev.nouls({"issue": "x" * 4000}, {"a": "Is it?"})
    assert answers.input_tokens >= 1000 and answers.cost_usd > 0 and jev.input_tokens == answers.input_tokens


# 4. without a TypeSafe key, arm E and resume say what to do instead of giving wrong advice or a traceback
def test_the_gate_without_a_key_gives_advice_that_fits_every_command(monkeypatch):
    from margin.intake import IntakeUnavailable, make_gate

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(IntakeUnavailable) as caught:
        make_gate()
    assert "TYPESAFE_API_KEY" in str(caught.value) and "--gate" not in str(caught.value)
    assert "arms A to D" in str(caught.value)


def test_resuming_an_arm_e_run_without_a_key_explains_instead_of_crashing(tmp_path, monkeypatch, capsys):
    from margin.cli import main
    from margin.jev import JevUnavailable

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr("margin.cli.load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr("margin.cli.init_telemetry", lambda *a, **k: None)
    monkeypatch.setattr("margin.cli.shutdown_telemetry", lambda: None)
    settings = Settings(runs_dir=tmp_path / "runs", ledger_path=tmp_path / "ledger.jsonl")
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls, env=None: settings))

    def needs_jev(*args, **kwargs):  # what execute_run does on arm E when there is no key
        raise JevUnavailable("arm E needs TYPESAFE_API_KEY")

    monkeypatch.setattr("margin.run.execute_run", needs_jev)
    run_dir = tmp_path / "runs" / "killed-E-run"
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(json.dumps({"task_id": "cachetools-423", "arm": "E", "version": "v4-jev"}))
    assert main(["resume", "--run-id", "killed-E-run"]) == 2
    assert "TYPESAFE_API_KEY" in capsys.readouterr().out


# 5. a postmortem that numbers its lessons must not lose them
def test_numbered_and_starred_lessons_are_kept():
    from margin.lessons import lesson_lines

    reply_text = "Lessons:\n- Read the parser first.\n2. Run the target test before editing.\n3) Check the config loader.\n* Grep for callers.\nThanks."
    assert lesson_lines(reply_text) == [
        "Read the parser first.", "Run the target test before editing.", "Check the config loader.", "Grep for callers.",
    ]


# 6. nothing a snippet starts may outlive it
def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _gone_within(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


SPAWN = (
    "import subprocess, sys, time\n"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],"
    " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
    "open({pidfile!r}, 'w').write(str(p.pid))\n"
)


@pytest.mark.parametrize("ending", ["times out", "exits normally"])
def test_a_process_started_by_a_snippet_does_not_outlive_it(sandbox, tmp_path, ending):
    pidfile = tmp_path / "child.pid"
    code = SPAWN.format(pidfile=str(pidfile)) + ("time.sleep(60)\n" if ending == "times out" else "")
    try:
        if ending == "times out":
            with pytest.raises(subprocess.TimeoutExpired):
                sandbox.run_python(code, 2)
        else:
            assert sandbox.run_python(code, 20)[0] == 0
        assert _gone_within(int(pidfile.read_text()))
    finally:  # never leave a sleeper behind, even when the test fails
        with contextlib.suppress(Exception):
            os.kill(int(pidfile.read_text()), signal.SIGKILL)


# 7. run ids made in the same second must not collide, even in a test that makes fifty of them
def test_a_run_id_has_enough_randomness_that_a_collision_is_negligible():
    from margin.run import new_run_id

    suffix = new_run_id("t", "A").rsplit("-", 1)[1]
    assert len(suffix) >= 8 and int(suffix, 16) >= 0


def test_the_real_graph_search_test_tolerates_one_transient_failure(monkeypatch):
    import test_graph
    from margin.context import GraphContext, GraphError

    calls = []

    def flaky_search(self, query, top_k=6):
        calls.append(query)
        if len(calls) == 1:
            raise GraphError("transient")
        return "1. src/margin/pricing.py:83 PriceTable._price"

    monkeypatch.setattr(GraphContext, "search", flaky_search)
    assert ".py" in test_graph.real_search_with_one_retry(ROOT, "price table cost of a model call")
    assert len(calls) == 2


def test_a_graph_search_that_fails_twice_reports_both_errors(monkeypatch):
    import test_graph
    from margin.context import GraphContext, GraphError

    def broken(self, query, top_k=6):
        raise GraphError("index locked")

    monkeypatch.setattr(GraphContext, "search", broken)
    with pytest.raises(AssertionError, match="index locked"):
        test_graph.real_search_with_one_retry(ROOT, "q")
