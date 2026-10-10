import json

import pytest

from margin.config import ROOT
from margin.pricing import PriceTable, SpendMeter, Usage
from margin.state import CorruptCheckpoint, RunState


def test_log_and_read_events(tmp_path):
    s = RunState(tmp_path / "run")
    s.log("model_usage", model="m", usage={"input_tokens": 1})
    s.log("retry", attempt=1)
    assert [e["type"] for e in s.events()] == ["model_usage", "retry"]
    assert len(s.events("retry")) == 1


def test_truncated_last_event_is_skipped(tmp_path):
    s = RunState(tmp_path / "run")
    s.log("a")
    with s.events_path.open("a") as f:
        f.write('{"type": "b", "x":')
    with pytest.warns(UserWarning, match="unreadable event line"):
        assert [e["type"] for e in s.events()] == ["a"]


def test_usage_events_restore_the_meter(tmp_path):
    s = RunState(tmp_path / "run")
    u = Usage(input_tokens=1_000_000)
    s.log("model_usage", model="claude-sonnet-5-5", usage=u.to_dict(), cost=2.0)
    meter = SpendMeter(PriceTable.load(ROOT / "pricing.toml"))
    s.restore_meter(meter)
    assert meter.total_usd == pytest.approx(2.0)


def test_checkpoint_roundtrip(tmp_path):
    s = RunState(tmp_path / "run")
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": [{"type": "text", "text": "yo"}]}]
    s.save_checkpoint(turn=2, messages=msgs, model="claude-sonnet-5-5", effort="medium", rung="CONTINUE", extra={"k": 1})
    ck = s.load_checkpoint()
    assert ck["turn"] == 2
    assert ck["messages"] == msgs
    assert ck["extra"] == {"k": 1}
    assert not list(s.dir.glob("*.tmp"))


def test_no_checkpoint_returns_none(tmp_path):
    assert RunState(tmp_path / "run").load_checkpoint() is None


def test_tampered_checkpoint_is_rejected(tmp_path):
    s = RunState(tmp_path / "run")
    s.save_checkpoint(turn=1, messages=[{"role": "user", "content": "hi"}], model="m", effort="low", rung="CONTINUE", extra={})
    data = json.loads(s.checkpoint_path.read_text())
    data["messages"][0]["content"] = "tampered"
    s.checkpoint_path.write_text(json.dumps(data))
    with pytest.raises(CorruptCheckpoint):
        s.load_checkpoint()


def test_an_event_logged_after_a_torn_line_is_not_lost_and_the_torn_line_is_reported(tmp_path):
    import pytest

    state = RunState(tmp_path / "s")
    state.log("first")
    with state.events_path.open("a") as f:
        f.write('{"t": 1, "type": "mo')               # killed mid-write
    state.log("model_usage", model="m", usage={})      # this is a cost event: losing it would lose paid spend
    with pytest.warns(UserWarning):
        types = [e["type"] for e in state.events()]
    assert types == ["first", "model_usage"]


def test_a_checkpoint_that_is_not_json_is_reported_as_corrupt(tmp_path):
    s = RunState(tmp_path / "run")
    s.save_checkpoint(turn=1, messages=[{"role": "user", "content": "hi"}], model="m", effort="low", rung="CONTINUE", extra={})
    s.checkpoint_path.write_text('{"turn": 1, "messages": [')
    with pytest.raises(CorruptCheckpoint):
        s.load_checkpoint()
