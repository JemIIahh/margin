"""Findings of the second fresh-context review (arms D and E, the intake gate), each reproduced before the fix."""
import sys
from pathlib import Path

import pytest

from fakes import FakeExecutor, ScriptedClient, reply, text, tool_use
from margin.agent.loop import run_agent
from margin.config import ROOT, Settings
from margin.errors import TransientModelError
from margin.governor import Governor, NullGovernor
from margin.pricing import PriceTable, SpendMeter
from margin.state import RunState
from test_arm_e import FakeJevClient
from test_tools import make_executor

PRICES = PriceTable.load(ROOT / "pricing.toml")
COACH = "claude-sonnet-4.6"


# 1. run_python can change the tree, so it must clear the "fix verifies" flag
def test_a_snippet_after_a_green_run_clears_the_verified_flag(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path, arm="D")
    ex.execute("edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})
    ex.execute("run_tests", {})
    assert ex.green
    ex.execute("run_python", {"code": "open('pkg/mathy.py', 'a').write('\\n')"})
    assert not ex.green


# 2. snippet output must never show the user's home directory (interpreter paths in tracebacks)
def test_snippet_output_never_shows_the_home_directory(sandbox, tmp_path):
    out = make_executor(sandbox, tmp_path, arm="D").execute("run_python", {"code": "import sys\nprint(sys.executable)"})
    assert str(Path.home()) not in out.text and "exit code 0" in out.text


# 4. resuming arm E must not re-pick lessons (double metering) and must keep the gate's cost
def test_resuming_does_not_pick_lessons_again(tmp_path):
    from margin.jev import Jev
    from margin.run import _learning

    client = FakeJevClient({"l0": 0.9})
    state, meter = RunState(tmp_path / "r"), SpendMeter(PRICES)
    task = type("T", (), {"id": "t1", "repo": "r"})()
    settings = Settings(lessons_path=tmp_path / "lessons.jsonl")
    (tmp_path / "lessons.jsonl").write_text('{"task_id": "t2", "repo": "r", "text": "Read the parser first.", "run_id": "x"}\n')
    lessons, judge = _learning("E", task, "issue", settings, state, meter, Jev(client), resume=True)
    assert lessons is None and judge is not None and client.calls == [] and meter.total_usd == 0
    lessons, judge = _learning("E", task, "issue", settings, state, meter, Jev(client), resume=False)
    spent = meter.total_usd
    assert lessons == ["Read the parser first."] and len(client.calls) == 1 and spent > 0
    lessons, judge = _learning("E", task, "issue", settings, state, meter, Jev(client), resume=True)
    assert lessons == ["Read the parser first."] and len(client.calls) == 1 and meter.total_usd == spent


def test_a_resumed_run_keeps_the_cost_of_its_original_intake_screen(tmp_path):
    from margin.run import _restored_intake_cost

    state = RunState(tmp_path / "r")
    assert _restored_intake_cost(state) == 0.0
    state.log("intake", decision="accept", cost_usd=0.00004)
    assert _restored_intake_cost(state) == pytest.approx(0.00004)


def test_the_coach_and_nudge_gaps_survive_a_resume(tmp_path):
    from margin.jev import Jev, ProgressJudge

    state = RunState(tmp_path / "r")
    resume = {
        "messages": [{"role": "user", "content": "FIRST"}], "turn": 10, "model": "claude-sonnet-5-5", "effort": "medium",
        "rung": "CONTINUE", "extra": {"coach_notes": 1, "last_progress_turn": 9, "last_coach_turn": 9, "last_nudge_turn": 9},
    }
    client = ScriptedClient([reply([text("done")])])
    run_agent(
        first_prompt="FIRST", arm="E", client=client, meter=SpendMeter(PRICES), governor=NullGovernor(),
        executor=FakeExecutor(), state=state, prices=PRICES, resume=resume, sleep=lambda s: None,
        settings=Settings(coach_model=COACH, judge_warmup_turns=3), judge=ProgressJudge(Jev(FakeJevClient({"ready_to_edit": 0.1}))),
    )
    assert not any(c["model"] == COACH for c in client.calls)       # the last note was one turn ago: the 4-turn gap holds


def test_the_checkpoint_keeps_the_coach_and_nudge_turns(tmp_path):
    from margin.jev import Jev, ProgressJudge

    state = RunState(tmp_path / "r")
    replies = [*[reply([tool_use(f"t{i}", "read_file", {"path": str(i)})], stop="tool_use") for i in range(3)],
               reply([text("Next step: edit.")]),                                   # the coach, at turn 3
               reply([tool_use("t3", "read_file", {"path": "3"})], stop="tool_use"),  # a turn that is checkpointed
               reply([text("done")])]
    run_agent(
        first_prompt="FIRST", arm="E", client=ScriptedClient(replies), meter=SpendMeter(PRICES), governor=NullGovernor(),
        executor=FakeExecutor(), state=state, prices=PRICES, sleep=lambda s: None,
        settings=Settings(coach_model=COACH, judge_warmup_turns=3), judge=ProgressJudge(Jev(FakeJevClient({"ready_to_edit": 0.1}))),
    )
    extra = state.load_checkpoint()["extra"]
    assert extra["last_coach_turn"] == 3 and "last_nudge_turn" in extra


# 5. the coach must be priced before anything is spent, and a transient error must be retried, not lose the note
def test_an_unpriced_coach_model_is_refused_before_any_spend():
    from margin.run import _require_priced

    _require_priced(PRICES, COACH)
    with pytest.raises(ValueError, match="pricing.toml"):
        _require_priced(PRICES, "a-model-with-no-price")


def test_a_transient_coach_error_is_retried(tmp_path):
    replies = [
        reply([tool_use("t1", "read_file", {"path": "a"})], stop="tool_use", input_tokens=100_000, output_tokens=45_000),
        TransientModelError("overloaded"),                       # the coach's first attempt
        reply([text("Next step: run the tests.")]),             # the retry
        reply([text("done")]),
    ]
    client = ScriptedClient(replies)
    state = RunState(tmp_path / "r")
    run_agent(
        first_prompt="FIRST", arm="D", client=client, meter=SpendMeter(PRICES), governor=Governor(cap_usd=1.0),
        executor=FakeExecutor(), state=state, prices=PRICES, settings=Settings(coach_model=COACH), sleep=lambda s: None,
    )
    assert "Next step: run the tests." in str(client.calls[-1]["messages"])
    assert state.events("retry")


# 6. a TypeSafe outage is an infrastructure failure, not a benchmark loss
def test_a_gate_outage_is_recorded_as_an_infrastructure_failure(tmp_path):
    from margin.run import execute_run
    from test_run_intake import FakeGate
    from test_tasks import make_task, settings_for

    task, settings = make_task(tmp_path), settings_for(tmp_path)
    row = execute_run(task, "E", settings, tasks_root=tmp_path, client=ScriptedClient([]),
                      gate=FakeGate("review", reasons=["gate unavailable: TypeSafeAPIConnectionError"]), run_id="r-out",
                      version="v4-jev", venv_python=Path(sys.executable))
    assert row.infra_error and not row.solved
    declined = execute_run(task, "E", settings, tasks_root=tmp_path, client=ScriptedClient([]),
                           gate=FakeGate("decline", reasons=["injection 0.99 >= 0.70"]), run_id="r-dec",
                           version="v4-jev", venv_python=Path(sys.executable))
    assert not declined.infra_error


# the demo shows `margin run`'s output: the receipt path it prints must not name the user's home directory
def test_run_prints_the_receipt_path_relative_to_the_repository(monkeypatch, capsys):
    from types import SimpleNamespace

    from margin.cli import main

    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls, env=None: Settings()))
    monkeypatch.setattr("margin.cli.init_telemetry", lambda *a, **k: None)
    monkeypatch.setattr("margin.cli.shutdown_telemetry", lambda: None)
    record = SimpleNamespace(run_id="cachetools-423-C-1", solved=True, cost_usd=0.1, margin_usd=0.2)
    monkeypatch.setattr("margin.run.execute_run", lambda *a, **k: record)
    assert main(["run", "--task", "cachetools-423", "--arm", "C"]) == 0
    out = capsys.readouterr().out
    assert "receipt: runs/cachetools-423-C-1/receipt.md" in out and str(Path.home()) not in out


def test_a_home_directory_at_the_filesystem_root_is_not_scrubbed(sandbox, tmp_path, monkeypatch):
    monkeypatch.setattr("margin.agent.tools.Path.home", classmethod(lambda cls: Path("/")))
    out = make_executor(sandbox, tmp_path, arm="D").execute("run_python", {"code": "print('a/b')"})
    assert "a/b" in out.text
