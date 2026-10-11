import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from margin.config import ROOT
from margin.context import GraphContext, GraphError, extract_identifiers, extract_paths

FIXTURES = Path(__file__).parent / "fixtures"


def fake(stdout="", returncode=0, stderr="", raises=None):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        run.kwargs = kwargs
        if raises:
            raise raises
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    run.calls = calls
    return run


def test_extract_paths_from_real_search_output():
    paths = extract_paths((FIXTURES / "graph_search_agent.txt").read_text())
    assert any(p.endswith("src/margin/pricing.py") for p in paths)
    assert len(paths) == len(set(paths))


def test_extract_paths_handles_suffixes_quotes_and_ignores_other_extensions():
    text = 'see src/a/b.py:12 and "src/c.py" plus ./d.py, but not x.pyc or /abs/e.py'
    assert extract_paths(text) == ["src/a/b.py", "src/c.py", "d.py"]


def test_extract_identifiers_prefers_backticked_names_then_camel_then_snake():
    text = "`PriceTable.cost` is wrong when SpendMeter sees cache_read tokens"
    assert extract_identifiers(text) == ["cost", "PriceTable", "SpendMeter"]
    assert extract_identifiers("nothing special here") == []


def test_search_builds_the_expected_command(tmp_path):
    run = fake(stdout="src/x.py:1 hit")
    graph = GraphContext(tmp_path, runner=run)
    assert graph.search("fix the cache") == "src/x.py:1 hit"
    cmd = run.calls[0]
    assert cmd[:3] == ["entire", "graph", "search"]
    assert cmd[cmd.index("--query") + 1] == "fix the cache"
    assert cmd[cmd.index("--format") + 1] == "agent"
    assert cmd[cmd.index("--repo") + 1] == str(tmp_path.resolve())


def test_absolute_repo_paths_are_made_relative(tmp_path):
    run = fake(stdout=f"{tmp_path.resolve()}/src/x.py:3 hit")
    assert GraphContext(tmp_path, runner=run).search("q") == "src/x.py:3 hit"


def test_failures_become_graph_errors(tmp_path):
    with pytest.raises(GraphError, match="exit 3"):
        GraphContext(tmp_path, runner=fake(returncode=3)).search("q")
    with pytest.raises(GraphError, match="timed out"):
        GraphContext(tmp_path, runner=fake(raises=subprocess.TimeoutExpired("entire", 1))).search("q")
    with pytest.raises(GraphError, match="not on PATH"):
        GraphContext(tmp_path, runner=fake(raises=FileNotFoundError())).search("q")


def impact_runner(outputs, search_output=""):
    def run(cmd, **kwargs):
        if "search" in cmd:
            return SimpleNamespace(stdout=search_output, stderr="", returncode=0)
        symbol = cmd[cmd.index("--symbol") + 1]
        return SimpleNamespace(stdout=outputs.get(symbol, ""), stderr="", returncode=0)

    return run


def test_impact_size_counts_distinct_files_across_identifiers(tmp_path):
    outputs = {"PriceTable": "src/a.py:1 src/b.py:2", "cost": "src/b.py:9 src/c.py:3"}
    graph = GraphContext(tmp_path, runner=impact_runner(outputs))
    assert graph.impact_size("`PriceTable.cost` is wrong") == 3


def test_impact_size_falls_back_to_search_when_there_are_no_identifiers(tmp_path):
    graph = GraphContext(tmp_path, runner=impact_runner({}, search_output="src/z.py:1 hit"))
    assert graph.impact_size("plain words only") == 1


def test_impact_size_is_zero_when_the_graph_fails(tmp_path):
    assert GraphContext(tmp_path, runner=fake(returncode=1)).impact_size("`Foo.bar` broke") == 0


def test_the_graph_subprocess_never_sees_api_keys(tmp_path, monkeypatch):
    """The graph parses untrusted repository files, so it gets a minimal environment, not our keys."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("NEATLOGS_API_KEY", "nl-secret")
    run = fake(stdout="src/x.py:1 hit")
    GraphContext(tmp_path, runner=run).search("q")
    env = run.kwargs["env"]
    assert "ANTHROPIC_API_KEY" not in env and "NEATLOGS_API_KEY" not in env
    assert env["PATH"] and env["HOME"]


def real_search_with_one_retry(root, query, top_k=3):
    """The real CLI on this repository. It failed once while other processes ran and passed on every rerun; the failure
    was not reproduced (8 and 32 concurrent searches, full CPU load, file churn, a held git index lock). So one failed
    call is retried, and two in a row fail the test with both errors, to show the cause if it happens again."""
    errors = []
    for _ in range(2):
        try:
            return GraphContext(root).search(query, top_k=top_k)
        except GraphError as exc:
            errors.append(str(exc))
    raise AssertionError("entire graph search failed twice: " + " | ".join(errors))


@pytest.mark.skipif(shutil.which("entire") is None, reason="entire CLI is not installed")
def test_real_graph_search_finds_code_in_this_repo():
    out = real_search_with_one_retry(ROOT, "price table cost of a model call")
    assert ".py" in out
