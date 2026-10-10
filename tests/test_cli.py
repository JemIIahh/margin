import pytest

from margin.cli import build_parser, main


def test_run_subcommand_parses_task_arm_and_defaults():
    args = build_parser().parse_args(["run", "--task", "t1", "--arm", "B", "--version", "v2"])
    assert (args.task, args.arm, args.version) == ("t1", "B", "v2")
    assert args.tasks_file is None and args.run_id is None


def test_an_unknown_arm_is_rejected_before_anything_runs():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--task", "t1", "--arm", "D"])


def test_tasks_validate_subcommand_parses_ids():
    args = build_parser().parse_args(["tasks", "validate", "--ids", "a", "b"])
    assert args.ids == ["a", "b"] and args.tasks_file is None
    assert build_parser().parse_args(["tasks", "validate"]).ids is None


def test_bench_and_calibrate_flat_subcommands_parse():
    args = build_parser().parse_args(["bench", "--arm", "A", "--split", "calibration", "--only-missing"])
    assert (args.arm, args.split, args.version, args.only_missing) == ("A", "calibration", "v1", True)
    assert build_parser().parse_args(["bench", "--arm", "B"]).split == "all"
    assert build_parser().parse_args(["calibrate-flat"]).command == "calibrate-flat"


def test_quote_subcommand_parses():
    args = build_parser().parse_args(["quote", "--task", "t1"])
    assert args.task == "t1" and args.tasks_file is None


def test_resume_subcommand_requires_a_run_id():
    assert build_parser().parse_args(["resume", "--run-id", "r1"]).run_id == "r1"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["resume"])


def test_bench_refuses_to_run_while_a_fault_is_set(monkeypatch, capsys):
    """A stray MARGIN_FAULT would silently inject faults into benchmark runs and waste the spend on rows that are ignored."""
    monkeypatch.setenv("MARGIN_FAULT", "tool_timeout")
    assert main(["bench", "--arm", "A", "--split", "calibration"]) == 2
    assert "MARGIN_FAULT" in capsys.readouterr().out


def test_quote_removes_the_worktree_it_prepared(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from margin.cli import main
    from margin.quote import Features

    tasks_file = tmp_path / "tasks.toml"
    tasks_file.write_text(
        '[[task]]\nid = "t1"\nsplit = "evaluation"\nrepo = "r"\nbase_commit = "b"\nfix_commit = "f"\n'
        f'issue_url = "u"\nissue_file = "{tmp_path / "i.md"}"\ntarget_tests = []\ntest_files = []\n'
    )
    (tmp_path / "i.md").write_text("an issue")
    prep = SimpleNamespace(sandbox=SimpleNamespace(root=tmp_path / "work"), baseline_seconds=1.0, bare=tmp_path / "bare")
    removed = []
    monkeypatch.setattr("margin.bench.tasks.prepare_run", lambda *a, **k: prep)
    monkeypatch.setattr("margin.bench.tasks.remove_worktree", lambda bare, work: removed.append((bare, work)))
    monkeypatch.setattr("margin.context.GraphContext", lambda root: None)
    monkeypatch.setattr("margin.quote.extract_features", lambda *a, **k: Features(100, 3, 1000, 2.0))
    assert main(["quote", "--task", "t1", "--tasks-file", str(tasks_file)]) == 0
    assert removed == [(tmp_path / "bare", tmp_path / "work")]


def test_quote_on_a_fresh_clone_learns_from_the_published_evidence_ledger(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from margin.cli import main
    from margin.config import Settings
    from margin.ledger import Ledger
    from margin.quote import Features
    from test_ledger import rec

    (tmp_path / "docs" / "evidence").mkdir(parents=True)
    published = Ledger(tmp_path / "docs" / "evidence" / "ledger.jsonl")
    for n in range(6):
        published.append(rec(run_id=f"e{n}", task=f"old{n}", arm="B", cost=0.1 + n * 0.02, features=Features(100 + n, 3, 1000, 2.0).to_dict()))
    settings = Settings(root=tmp_path, runs_dir=tmp_path / "runs", ledger_path=tmp_path / "runs" / "ledger.jsonl", cache_dir=tmp_path / "cache")
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls, env=None: settings))
    tasks_file = tmp_path / "tasks.toml"
    (tmp_path / "i.md").write_text("an issue")
    tasks_file.write_text(
        '[[task]]\nid = "t1"\nsplit = "evaluation"\nrepo = "r"\nbase_commit = "b"\nfix_commit = "f"\n'
        f'issue_url = "u"\nissue_file = "{tmp_path / "i.md"}"\ntarget_tests = []\ntest_files = []\n'
    )
    prep = SimpleNamespace(sandbox=SimpleNamespace(root=tmp_path / "work"), baseline_seconds=1.0, bare=tmp_path / "bare")
    monkeypatch.setattr("margin.bench.tasks.prepare_run", lambda *a, **k: prep)
    monkeypatch.setattr("margin.bench.tasks.remove_worktree", lambda bare, work: None)
    monkeypatch.setattr("margin.context.GraphContext", lambda root: None)
    monkeypatch.setattr("margin.quote.extract_features", lambda *a, **k: Features(103, 3, 1000, 2.0))
    assert main(["quote", "--task", "t1", "--tasks-file", str(tasks_file)]) == 0
    assert "from 6 past runs" in capsys.readouterr().out
