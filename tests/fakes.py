"""Test doubles shared across loop, tools and run tests."""
import copy
from types import SimpleNamespace

from margin.agent.tools import ProgressTracker, ToolOutput


class FakeBlock:
    def __init__(self, type_, **kw):
        self.type = type_
        self.__dict__.update(kw)

    def to_dict(self):
        return dict(self.__dict__)


def text(t):
    return FakeBlock("text", text=t)


def tool_use(id_, name, input_):
    return FakeBlock("tool_use", id=id_, name=name, input=input_)


def reply(blocks, stop="end_turn", input_tokens=100, output_tokens=50):
    usage = SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )
    return SimpleNamespace(content=blocks, stop_reason=stop, usage=usage)


class ScriptedClient:
    """Replays canned replies; an Exception instance in the script is raised instead."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **params):
        self.calls.append(copy.deepcopy(params))
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeExecutor:
    def __init__(self, outputs=None):
        self.progress = ProgressTracker()
        self.faults = None
        self.issue_text = "the issue"
        self.target_nodeids = ["tests/test_x.py::test_y"]
        self.calls = []
        self.outputs = outputs or {}

    def execute(self, name, args):
        self.calls.append((name, args))
        return ToolOutput(self.outputs.get(name, "ok"))

    def digest(self):
        return {"diff": "DIFF", "tests": "TESTS"}


class FakeGraph:
    def search(self, query):
        return f"GRAPH-SEARCH:{query}"

    def impact(self, symbol):
        return f"GRAPH-IMPACT:{symbol}"


def install_fake_neatlogs(monkeypatch):
    """A fake neatlogs whose spans record what the code does to them (like the real one, trace() never marks errors)."""
    import contextlib
    import sys
    import types

    from margin import telemetry

    spans = []

    @contextlib.contextmanager
    def fake_trace(name, kind=None):
        span = types.SimpleNamespace(
            name=name, kind=kind, attrs={}, status=None, exceptions=[],
            set_attribute=lambda k, v: span.attrs.__setitem__(k, v),
            set_status=lambda s: setattr(span, "status", s),
            record_exception=lambda e: span.exceptions.append(e),
        )
        spans.append(span)
        yield span

    monkeypatch.setitem(sys.modules, "neatlogs", types.SimpleNamespace(trace=fake_trace))
    monkeypatch.setattr(telemetry, "_enabled", True)
    return spans
