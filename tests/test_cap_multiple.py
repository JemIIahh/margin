"""A cap multiple lets a test give a job more runway than its quote allows, without touching the price."""
import dataclasses
import sys
from pathlib import Path

import pytest

from fakes import ScriptedClient, reply, text
from margin.config import Settings
from margin.run import execute_run
from test_tasks import make_task, settings_for


def test_the_cap_multiple_is_one_by_default_and_read_from_the_environment():
    assert Settings().cap_multiple == 1.0
    assert Settings.from_env({"MARGIN_CAP_MULTIPLE": "4"}).cap_multiple == 4.0


def test_a_benchmark_run_cannot_use_a_cap_multiple(tmp_path):
    settings = dataclasses.replace(settings_for(tmp_path), cap_multiple=3.0)
    with pytest.raises(ValueError, match="live"):
        execute_run(make_task(tmp_path), "C", settings, tasks_root=tmp_path, client=ScriptedClient([]), version="v2")


def test_a_cap_multiple_must_be_positive(tmp_path):
    settings = dataclasses.replace(settings_for(tmp_path), cap_multiple=0.0)
    with pytest.raises(ValueError, match="cap_multiple"):
        execute_run(make_task(tmp_path), "C", settings, tasks_root=tmp_path, client=ScriptedClient([]), version="live-x")


def test_the_governor_gets_the_scaled_cap_and_the_price_is_still_the_quoted_one(tmp_path, monkeypatch):
    import margin.run as run_mod

    seen = []
    real = run_mod.Governor
    monkeypatch.setattr(run_mod, "Governor", lambda cap, *a, **k: (seen.append(cap), real(cap, *a, **k))[1])

    task = make_task(tmp_path)

    def run_with(multiple, run_id):
        settings = dataclasses.replace(settings_for(tmp_path), cap_multiple=multiple)
        return execute_run(
            task, "C", settings, tasks_root=tmp_path, client=ScriptedClient([reply([text("done")])]),
            run_id=run_id, version="live-x", venv_python=Path(sys.executable),
        )

    base = run_with(1.0, "r-1x")
    wide = run_with(3.0, "r-3x")
    assert seen[1] == pytest.approx(seen[0] * 3)
    assert wide.price_usd == base.price_usd and "cap:x3" in wide.trace_tags and "cap:x3" not in base.trace_tags
