"""Arm D: arm C plus a coach instead of the downgrade, stop-when-verified, a run_python tool and lessons from past runs."""
import json

from fakes import FakeExecutor, ScriptedClient, reply, text, tool_use
from margin.agent.loop import run_agent
from margin.agent.tools import ARM_TOOLS, ProgressTracker, ToolOutput, tool_schemas
from margin.config import ROOT, Settings
from margin.governor import Governor, NullGovernor
from margin.pricing import PriceTable, SpendMeter
from margin.state import RunState
from test_tools import make_executor

PRICES = PriceTable.load(ROOT / "pricing.toml")
COACH = "claude-sonnet-4.6"


def go(tmp_path, replies, *, arm="D", governor=None, settings=None, executor=None):
    client = ScriptedClient(replies)
    state = RunState(tmp_path / "run")
    result = run_agent(
        first_prompt="FIRST", arm=arm, client=client, meter=SpendMeter(PRICES), governor=governor or NullGovernor(),
        executor=executor or FakeExecutor(), state=state, prices=PRICES,
        settings=settings or Settings(coach_model=COACH), sleep=lambda s: None,
    )
    return result, client, state


class GreenExecutor(FakeExecutor):
    """Edits clear the green flag; a test run sets it, as a fully passing run would."""

    def __init__(self):
        super().__init__()
        self.green = False

    def execute(self, name, args):
        self.calls.append((name, args))
        if name in ("edit_file", "write_file"):
            self.green = False
            self.progress.note_edit()
        if name == "run_tests":
            self.green = True
        return ToolOutput("ok")


# --- tools ----------------------------------------------------------------------------------------------------------
def test_arm_d_has_every_arm_c_tool_plus_run_python_and_arm_c_does_not():
    assert ARM_TOOLS["D"] == [*ARM_TOOLS["C"], "run_python"]
    assert "run_python" not in ARM_TOOLS["C"]
    assert [t["name"] for t in tool_schemas("D")][-1] == "run_python"


def test_run_python_runs_a_snippet_against_the_repository(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path, arm="D")
    out = ex.execute("run_python", {"code": "from pkg.mathy import add\nprint(add(1, 2))"})
    assert not out.is_error and "-1" in out.text and "exit code 0" in out.text
    where = ex.execute("run_python", {"code": "import os\nprint(os.getcwd())"})
    assert str(sandbox.root) not in where.text and "." in where.text
    failed = ex.execute("run_python", {"code": "raise SystemExit(3)"})
    assert "exit code 3" in failed.text


def test_run_python_stops_a_snippet_that_runs_too_long_and_leaves_no_file_in_the_repository(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path, arm="D")
    ex.python_timeout_s = 1
    out = ex.execute("run_python", {"code": "import time\ntime.sleep(5)"})
    assert out.is_error and "timed out after 1s" in out.text
    assert sandbox.git_diff() == ""


def test_run_python_is_not_offered_to_arm_c(sandbox, tmp_path):
    out = make_executor(sandbox, tmp_path, arm="C").execute("run_python", {"code": "print(1)"})
    assert out.is_error and "unknown tool" in out.text


# --- stop when verified -----------------------------------------------------------------------------------------------
def test_on_arm_d_a_fully_green_test_run_says_the_fix_verifies_and_an_edit_clears_it(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path, arm="D")
    ex.execute("edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})
    out = ex.execute("run_tests", {})
    assert ex.green and "the fix verifies" in out.text and "finish" in out.text
    ex.execute("edit_file", {"path": "pkg/mathy.py", "old": "a + b", "new": "b + a"})
    assert not ex.green
    plain = make_executor(sandbox, tmp_path, arm="B")
    plain.execute("edit_file", {"path": "pkg/mathy.py", "old": "b + a", "new": "a + b"})
    assert "the fix verifies" not in plain.execute("run_tests", {}).text


def test_arm_d_ends_the_run_two_turns_after_a_green_test_run_if_the_agent_keeps_going(tmp_path):
    script = [
        reply([tool_use("t1", "edit_file", {"path": "a", "old": "x", "new": "y"})], stop="tool_use"),
        reply([tool_use("t2", "run_tests", {})], stop="tool_use"),
        reply([tool_use("t3", "read_file", {"path": "a"})], stop="tool_use"),
        reply([tool_use("t4", "read_file", {"path": "b"})], stop="tool_use"),
        reply([tool_use("t5", "read_file", {"path": "c"})], stop="tool_use"),
        reply([text("done")]),
    ]
    result, client, _ = go(tmp_path, list(script), executor=GreenExecutor())
    assert result.stop == "verified" and len(client.replies) == 2
    other, other_client, _ = go(tmp_path / "b", list(script), arm="B", executor=GreenExecutor())
    assert other.stop == "end_turn" and other_client.replies == []


# --- coach instead of downgrade ---------------------------------------------------------------------------------------
def test_arm_d_asks_a_coach_instead_of_downgrading_and_the_worker_keeps_its_model_and_memory(tmp_path):
    replies = [
        reply([tool_use("t1", "read_file", {"path": "a"})], stop="tool_use", input_tokens=100_000, output_tokens=45_000),
        reply([text("Diagnosis: you never ran the tests. Next step: call run_tests.")]),  # the coach
        reply([text("done")]),
    ]
    result, client, state = go(tmp_path, replies, governor=Governor(cap_usd=1.0))
    coach_calls = [c for c in client.calls if c["model"] == COACH]
    worker_calls = [c for c in client.calls if c["model"] != COACH]
    assert len(coach_calls) == 1 and "tools" not in coach_calls[0]
    assert {c["model"] for c in worker_calls} == {"claude-sonnet-5-5"}
    last = worker_calls[-1]["messages"]
    assert last[0] == {"role": "user", "content": "FIRST"}
    assert "you never ran the tests" in json.dumps(last[-1])
    assert [e["rung"] for e in result.rung_events] == ["COACH"]
    assert any(e["model"] == COACH for e in state.events("model_usage"))


def test_the_coach_also_steps_in_after_turns_without_progress_and_at_most_twice(tmp_path):
    read = lambda i: reply([tool_use(f"t{i}", "read_file", {"path": str(i)})], stop="tool_use")
    note = reply([text("Next step: edit the function the issue names.")])
    replies = [read(0), read(1), note, read(2), read(3), note, read(4), read(5)]
    settings = Settings(coach_model=COACH, coach_stall_turns=2, max_turns=6)
    result, client, _ = go(tmp_path, replies, settings=settings)
    assert sum(c["model"] == COACH for c in client.calls) == 2
    assert [e["rung"] for e in result.rung_events] == ["COACH", "COACH"]
    assert all("no progress" in e["reason"] for e in result.rung_events)


def test_a_failing_coach_call_does_not_end_the_run(tmp_path):
    class CoachDown(ScriptedClient):
        def create(self, **params):
            if params["model"] == COACH:
                self.calls.append(params)
                raise RuntimeError("coach unavailable")
            return super().create(**params)

    client = CoachDown([read for read in (
        reply([tool_use("t0", "read_file", {"path": "0"})], stop="tool_use"),
        reply([tool_use("t1", "read_file", {"path": "1"})], stop="tool_use"),
        reply([text("done")]),
    )])
    result = run_agent(
        first_prompt="FIRST", arm="D", client=client, meter=SpendMeter(PRICES), governor=NullGovernor(),
        executor=FakeExecutor(), state=RunState(tmp_path / "r"), prices=PRICES,
        settings=Settings(coach_model=COACH, coach_stall_turns=2), sleep=lambda s: None,
    )
    assert result.stop == "end_turn"


def test_arm_c_still_downgrades(tmp_path):
    replies = [
        reply([tool_use("t1", "read_file", {"path": "a"})], stop="tool_use", input_tokens=100_000, output_tokens=45_000),
        reply([text("done")]),
    ]
    result, client, _ = go(tmp_path, replies, arm="C", governor=Governor(cap_usd=1.0))
    assert [e["rung"] for e in result.rung_events] == ["DOWNGRADE"]
    assert client.calls[-1]["model"] == Settings().fallback_model


# --- lessons ----------------------------------------------------------------------------------------------------------
def test_lessons_for_a_task_come_from_other_tasks_of_the_same_repository_only(tmp_path):
    from margin.lessons import Lesson, lessons_for

    lessons = [
        Lesson("sqlparse-826", "https://github.com/andialbrecht/sqlparse", "Read the grouping engine before the filters."),
        Lesson("sqlparse-772", "https://github.com/andialbrecht/sqlparse", "Lesson written about this very task."),
        Lesson("tabulate-241", "https://github.com/astanin/python-tabulate", "Other repository."),
        Lesson("sqlparse-332", "https://github.com/andialbrecht/sqlparse", "Read the grouping engine before the filters."),
    ]
    chosen = lessons_for("sqlparse-772", "https://github.com/andialbrecht/sqlparse", lessons, limit=5)
    assert chosen == ["Read the grouping engine before the filters."]      # its own lesson is out; duplicates collapse


def test_the_first_prompt_carries_lessons_only_when_there_are_some():
    from margin.agent.prompts import first_prompt

    with_lessons = first_prompt("issue", "ctx", ["t::x"], lessons=["Use run_python to reproduce the issue."])
    assert "Lessons from earlier jobs in this repository" in with_lessons and "Use run_python" in with_lessons
    assert "Lessons" not in first_prompt("issue", "ctx", ["t::x"])


def test_lessons_are_built_from_failed_runs_and_the_cheapest_verified_run_per_task(tmp_path):
    from margin.lessons import build_lessons, select_runs
    from test_ledger import rec

    rows = [
        rec(run_id="a-fail", task="t1", arm="A", solved=False, cost=0.3),
        rec(run_id="b-ok", task="t1", arm="B", solved=True, cost=0.1),
        rec(run_id="c-ok", task="t1", arm="C", solved=True, cost=0.05),
        rec(run_id="demo", task="t1", arm="C", solved=True, cost=0.01, trace_tags=["version:demo-x"]),
    ]
    assert [r.run_id for r in select_runs(rows)] == ["a-fail", "c-ok"]
    for run_id in ("a-fail", "c-ok"):
        (tmp_path / run_id).mkdir()
        (tmp_path / run_id / "checkpoint.json").write_text(json.dumps({"messages": [
            {"role": "user", "content": "FIRST"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": "read_file", "input": {"path": "a.py"}}]},
        ]}))
    client = ScriptedClient([reply([text("- Reproduce the issue first.\n- Run the full suite before finishing.")]),
                             reply([text("- Check the grouping code.")])])
    lessons, cost = build_lessons(
        select_runs(rows), tmp_path, {"t1": "https://github.com/x/y"}, client=client, model=COACH,
        prices=PRICES, issue_of=lambda task_id: "the issue",
    )
    assert [(l.task_id, l.text) for l in lessons] == [
        ("t1", "Reproduce the issue first."), ("t1", "Run the full suite before finishing."), ("t1", "Check the grouping code."),
    ]
    assert all(l.repo == "https://github.com/x/y" for l in lessons) and cost > 0
    assert all(c["model"] == COACH and "tools" not in c for c in client.calls)


# --- plumbing ---------------------------------------------------------------------------------------------------------
def test_arm_d_is_accepted_by_run_and_bench_and_lessons_build_parses():
    from margin.cli import build_parser

    p = build_parser()
    assert p.parse_args(["run", "--task", "x", "--arm", "D"]).arm == "D"
    assert p.parse_args(["bench", "--arm", "D"]).arm == "D"
    assert p.parse_args(["lessons", "build"]).command == "lessons"


def test_a_verified_stop_is_a_normal_finish_on_the_ledger_row():
    from margin.run import _abort_reason

    assert _abort_reason("verified", None) is None and _abort_reason("end_turn", None) is None
    assert _abort_reason("max_turns", None) == "max_turns"


def test_the_results_page_compares_arm_d_when_it_has_runs(tmp_path):
    from margin.bench.report import render_results
    from margin.ledger import Ledger
    from test_ledger import rec
    from test_results import FLAT, build_ledger

    ledger = build_ledger(tmp_path)
    for n, task in enumerate(["e1", "e2"]):
        row = rec(run_id=f"D{n}", task=task, arm="D", cost=0.5, price=2.4, quote={"p50": 1.2, "lo": 0.8, "hi": 1.6})
        ledger.append(row)
    page = render_results(Ledger(ledger.path), FLAT)
    assert "| D | 2 |" in page


def test_progress_tracker_is_unchanged_for_the_other_arms():
    tracker = ProgressTracker(initial_failing=2)
    tracker.note_tests(2)
    assert tracker.events == 0


def test_a_lesson_that_tells_the_agent_to_write_tests_is_never_given_to_it():
    from margin.lessons import Lesson, lessons_for

    repo = "https://github.com/x/y"
    lessons = [
        Lesson("t1", repo, "Before writing any fix, add the failing test case first and run it."),
        Lesson("t1", repo, "When adding a validator, also add parametrised test cases to tests/test_validate.py."),
        Lesson("t1", repo, "Read the grouping engine before the filters."),
    ]
    assert lessons_for("t2", repo, lessons, limit=5) == ["Read the grouping engine before the filters."]
