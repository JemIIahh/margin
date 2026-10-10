import pytest

from margin.cli import build_parser


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
