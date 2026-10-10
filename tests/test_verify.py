import pytest

from margin.sandbox import Sandbox
from margin.verify import (
    Baseline,
    NoJunit,
    SuiteRun,
    final_verdict,
    judge,
    make_baseline,
    nodeid_to_junit,
    parse_junit,
    run_suite,
)

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
<testcase classname="tests.test_a" name="test_ok" time="0.01"/>
<testcase classname="tests.test_a" name="test_bad" time="0.01"><failure message="boom">t</failure></testcase>
<testcase classname="tests.test_a" name="test_err" time="0.01"><error message="e">t</error></testcase>
<testcase classname="tests.test_a" name="test_skip" time="0.01"><skipped message="s"/></testcase>
</testsuite></testsuites>"""


def test_parse_junit_splits_passed_failed_and_ignores_skipped(tmp_path):
    p = tmp_path / "j.xml"
    p.write_text(SAMPLE)
    run = parse_junit(p)
    assert run.passed == frozenset({"tests.test_a::test_ok"})
    assert run.failed == frozenset({"tests.test_a::test_bad", "tests.test_a::test_err"})


def test_parse_junit_rejects_missing_and_garbage(tmp_path):
    with pytest.raises(NoJunit):
        parse_junit(tmp_path / "missing.xml")
    bad = tmp_path / "bad.xml"
    bad.write_text("not xml")
    with pytest.raises(NoJunit):
        parse_junit(bad)


def test_parse_junit_refuses_entity_expansion(tmp_path):
    bomb = tmp_path / "bomb.xml"
    bomb.write_text(
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
        '<testsuites><testsuite><testcase classname="&a;" name="t"/></testsuite></testsuites>'
    )
    with pytest.raises(NoJunit):
        parse_junit(bomb)


@pytest.mark.parametrize(
    "nodeid, expected",
    [
        ("tests/test_x.py::test_y", "tests.test_x::test_y"),
        ("tests/test_x.py::TestC::test_m", "tests.test_x.TestC::test_m"),
        ("a/b/test_x.py::test_p[1-2]", "a.b.test_x::test_p[1-2]"),
    ],
)
def test_nodeid_to_junit(nodeid, expected):
    assert nodeid_to_junit(nodeid) == expected


def test_nodeid_without_a_test_name_is_rejected():
    with pytest.raises(ValueError):
        nodeid_to_junit("tests/test_x.py")


def test_baseline_marks_inconsistent_ids_as_flaky():
    r1 = SuiteRun(frozenset({"a"}), frozenset({"b", "c"}))
    r2 = SuiteRun(frozenset({"a", "c"}), frozenset({"b"}))
    base = make_baseline(r1, r2)
    assert base.failing == frozenset({"b"})
    assert base.flaky == frozenset({"c"})
    assert Baseline.from_dict(base.to_dict()) == base


BASE = Baseline(failing=frozenset({"t::target", "t::old"}), flaky=frozenset({"t::flaky"}))


def test_judge_solved():
    after = SuiteRun(frozenset({"t::target", "t::ok"}), frozenset({"t::old", "t::flaky"}))
    v = judge(BASE, after, ["t::target"])
    assert v.solved and v.reason == "solved"


def test_judge_target_still_failing_or_missing():
    after = SuiteRun(frozenset({"t::ok"}), frozenset({"t::target", "t::old"}))
    v = judge(BASE, after, ["t::target", "t::gone"])
    assert not v.solved
    assert v.target_failing == ["t::target", "t::gone"]
    assert "target tests still failing" in v.reason


def test_judge_new_failure_blocks_a_fix():
    after = SuiteRun(frozenset({"t::target"}), frozenset({"t::old", "t::broke"}))
    v = judge(BASE, after, ["t::target"])
    assert not v.solved and v.new_failures == ["t::broke"]
    assert "new failures" in v.reason


def test_end_to_end_on_fixture_repo(sandbox, tmp_path):
    base = make_baseline(
        run_suite(sandbox, ["tests"], tmp_path / "1.xml"), run_suite(sandbox, ["tests"], tmp_path / "2.xml")
    )
    target = [nodeid_to_junit("tests/test_mathy.py::test_add")]
    assert base.failing == frozenset(target)
    before = final_verdict(sandbox, base, target, ["tests"], tmp_path / "3.xml")
    assert not before.solved and "target tests still failing" in before.reason
    sandbox.edit_file("pkg/mathy.py", "a - b", "a + b")
    assert final_verdict(sandbox, base, target, ["tests"], tmp_path / "4.xml").solved
    sandbox.write_file("tests/test_new.py", "def test_new():\n    assert False\n")
    broke = final_verdict(sandbox, base, target, ["tests"], tmp_path / "5.xml")
    assert not broke.solved and broke.new_failures == ["tests.test_new::test_new"]


def test_collection_error_is_a_failed_verdict_not_a_crash(sandbox, tmp_path):
    base = make_baseline(
        run_suite(sandbox, ["tests"], tmp_path / "1.xml"), run_suite(sandbox, ["tests"], tmp_path / "2.xml")
    )
    target = [nodeid_to_junit("tests/test_mathy.py::test_add")]
    sandbox.write_file("tests/test_mathy.py", "def broken(:\n")
    v = final_verdict(sandbox, base, target, ["tests"], tmp_path / "3.xml")
    assert not v.solved


def test_timeout_and_missing_results_are_failed_verdicts(sandbox, tmp_path):
    base = Baseline(frozenset(), frozenset())
    slow = Sandbox(sandbox.root, sandbox.venv_python, ["."], tmp_path / "h", test_timeout_s=1)
    slow.write_file("tests/test_slow.py", "import time\n\n\ndef test_slow():\n    time.sleep(5)\n")
    v = final_verdict(slow, base, ["t::x"], ["tests/test_slow.py"], tmp_path / "s.xml")
    assert not v.solved and "timed out" in v.reason
    v2 = final_verdict(sandbox, base, ["t::x"], ["no/such/dir"], tmp_path / "m.xml")
    assert not v2.solved and v2.reason
