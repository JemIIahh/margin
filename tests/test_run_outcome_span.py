"""A run's root span says why the run ended, so a reader (or neatlogs' own AI) does not have to guess."""
import sys
from pathlib import Path

import pytest

from fakes import ScriptedClient, reply, text, tool_use
from margin import telemetry
from margin.run import execute_run
from test_tasks import make_task, settings_for


def test_annotate_sets_attributes_on_the_open_span_when_telemetry_is_on(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider

    monkeypatch.setattr(telemetry, "_enabled", True)
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("margin.run") as sp:
        telemetry.annotate(**{"margin.stop_reason": "abort", "margin.edits": 0, "margin.solved": False, "margin.cost_usd": 0.0924})
    assert sp.attributes["margin.stop_reason"] == "abort" and sp.attributes["margin.edits"] == 0
    assert sp.attributes["margin.solved"] is False and sp.attributes["margin.cost_usd"] == "0.092400"


def test_annotate_is_a_no_op_without_telemetry_and_never_raises():
    telemetry.annotate(**{"margin.stop_reason": "abort"})


def _run(tmp_path, replies, arm="A", run_id="r1", monkeypatch=None):
    seen = {}
    monkeypatch.setattr("margin.run.annotate", lambda **kw: seen.update(kw))
    rec = execute_run(
        make_task(tmp_path), arm, settings_for(tmp_path), tasks_root=tmp_path, client=ScriptedClient(replies),
        run_id=run_id, venv_python=Path(sys.executable),
    )
    return rec, seen


def test_a_fix_that_verifies_says_so_on_the_root_span(tmp_path, monkeypatch):
    replies = [
        reply([tool_use("t1", "edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})], stop="tool_use"),
        reply([text("fixed")]),
    ]
    rec, seen = _run(tmp_path, replies, monkeypatch=monkeypatch)
    assert rec.solved
    assert seen["margin.outcome"] == "verified" and seen["margin.edits"] == 1 and seen["margin.stop_reason"] == "end_turn"
    assert seen["margin.solved"] is True and seen["margin.cost_usd"] == pytest.approx(rec.cost_usd)


def test_a_run_that_ends_without_an_edit_says_why_on_the_root_span(tmp_path, monkeypatch):
    rec, seen = _run(tmp_path, [reply([text("I give up")])], monkeypatch=monkeypatch)
    assert not rec.solved
    assert seen["margin.outcome"] == "not verified" and seen["margin.edits"] == 0 and seen["margin.solved"] is False
    assert seen["margin.stop_reason"] == "end_turn"


def test_a_run_stopped_by_the_cap_names_the_cap_and_the_stop(tmp_path, monkeypatch):
    import dataclasses

    replies = [reply([tool_use("t1", "read_file", {"path": "pkg/mathy.py"})], stop="tool_use", input_tokens=100_000, output_tokens=45_000)] * 3
    seen = {}
    monkeypatch.setattr("margin.run.annotate", lambda **kw: seen.update(kw))
    settings = settings_for(tmp_path)
    rec = execute_run(
        make_task(tmp_path), "C", dataclasses.replace(settings, run_hard_cap_usd=0.0001), tasks_root=tmp_path,
        client=ScriptedClient(replies), run_id="r-cap", venv_python=Path(sys.executable),
    )
    assert not rec.solved
    assert seen["margin.stop_reason"] == "abort" and "cap" in seen["margin.stop_detail"] and seen["margin.edits"] == 0
