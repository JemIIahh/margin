import pytest

from margin.cli import build_parser


def test_run_subcommand_parses_task_arm_and_defaults():
    args = build_parser().parse_args(["run", "--task", "t1", "--arm", "B", "--version", "v2"])
    assert (args.task, args.arm, args.version) == ("t1", "B", "v2")
    assert args.tasks_file is None and args.run_id is None


def test_an_unknown_arm_is_rejected_before_anything_runs():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--task", "t1", "--arm", "D"])
