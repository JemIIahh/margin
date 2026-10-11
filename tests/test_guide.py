import copy
import json
import re

import pytest

from margin.bench.guide import FAIL_TASK, PASS_TASK, TASK_ENTRY, GuideError, render_guide
from margin.bench.tasks import Task
from margin.cli import main

TASKS = [Task(id=TASK_ENTRY, split="calibration", repo="https://github.com/o/r", base_commit="aaa", fix_commit="bbb",
              issue_url="https://github.com/o/r/issues/1", issue_file="bench/issues/x.md",
              target_tests=["tests/test_x.py::test_x"], test_files=["tests/test_x.py"])]


def job(task, run_id, *, solved, cost, hi, verdict_detail=""):
    price = hi * 1.5
    return {
        "task": task, "run_id": run_id, "repo": "owner/project", "issue_url": "https://github.com/owner/project/issues/7",
        "title": "A `thing` is wrong", "quote": {"lo": hi / 6, "p50": hi / 3, "hi": hi}, "price": price, "cost": cost,
        "margin": price - cost if solved else -cost, "solved": solved,
        "features": {"issue_tokens": 300, "impact_files": 2, "repo_loc": 4000, "baseline_seconds": 2.5},
        "neighbours": {"picked": [{"task": "t1", "cost": hi / 5}, {"task": "t2", "cost": hi / 3}, {"task": "t3", "cost": hi / 2}],
                       "pool": 15},
        "cli": {"quote": f"{task}: cost band", "run": f"{run_id}: solved={solved} cost=${cost:.4f}"},
        "receipt": {"title": f"Receipt: {task} (arm E)", "items": [["Price", f"${price:.4f}"], ["Verdict", "verified"]]},
        "verdict": {"kind": "solved" if solved else "regression", "detail": verdict_detail},
    }


def mini():
    """Just the fields the guide reads from the console's data: two jobs on version E and the summaries."""
    intake = {"kind": "intake", "after": 0, "note": "accept: injection 0.03, actionable 0.99"}
    coach = {"kind": "coach", "after": 3, "note": "no progress in 8 turns", "detail": "Diagnosis: look in parse.py"}
    return {
        "n": 12, "markup": 0.5,
        "jobs": {"E": [job(PASS_TASK, "run-pass", solved=True, cost=0.07, hi=0.12),
                       job(FAIL_TASK, "run-fail", solved=False, cost=0.11, hi=0.15,
                           verdict_detail="tests.test_validate::test_url_rejects_invalid[file://]")]},
        "replays": {
            "run-pass": {"turns": [{"cum": 0.02}, {"cum": 0.04}, {"cum": 0.05}, {"cum": 0.07}], "marks": [intake, coach]},
            "run-fail": {"turns": [{"cum": 0.03}, {"cum": 0.06}, {"cum": 0.09}, {"cum": 0.11}],
                         "marks": [intake, coach, {"kind": "abort", "after": 4, "note": "the next call reaches the cap"}]},
        },
        "summaries": {a: {"verified": 11, "n": 12, "gross_margin": m, "over_cap": 0}
                      for a, m in zip("ABCDE", (0.13, 0.64, 0.63, 0.70, 0.69), strict=True)},
    }


def blob(page):
    return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.DOTALL).group(1))


def test_the_guide_fills_every_token_and_is_deterministic():
    page = render_guide(mini(), TASKS)
    assert "{{" not in page and "__DATA__" not in page
    assert page == render_guide(mini(), TASKS)


def test_the_embedded_data_carries_the_recorded_numbers():
    examples = blob(render_guide(mini(), TASKS))["examples"]
    assert examples["pass"]["curve"] == [0.02, 0.04, 0.05, 0.07] and examples["pass"]["turns"] == 4
    assert examples["pass"]["gov"] == [{"kind": "coach", "after": 3, "at": 0.05}]
    assert examples["fail"]["stop"] == {"after": 4} and examples["fail"]["short_test"] == "test_url_rejects_invalid[file://]"
    assert examples["pass"]["intake"] == {"injection": 0.03, "actionable": 0.99}
    assert examples["pass"]["title_plain"] == "A thing is wrong"  # backticks are for the console's code styling, not the guide's
    assert examples["pass"]["price"] == pytest.approx(0.18) and examples["pass"]["margin"] == pytest.approx(0.11)


def test_the_versions_strip_and_the_cost_range_come_from_the_data():
    page = render_guide(mini(), TASKS)
    assert page.count('class="vrow"') == 5 and "70%" in page and "11 of 12 fixed" in page
    assert "$0.07 to $0.11" in page  # the cheapest and the dearest of the runs the data holds


def test_the_two_pages_link_to_each_other_where_they_are_told_to():
    repo = render_guide(mini(), TASKS)
    assert 'href="console.html#proof"' in repo and 'href="guide.html" aria-current="page"' in repo
    site = render_guide(mini(), TASKS, console_href="./", guide_href="guide")
    assert 'href="./#proof"' in site and 'href="guide" aria-current="page"' in site


def test_the_example_task_file_is_a_real_manifest_entry():
    page = render_guide(mini(), TASKS)
    assert f'id = "{TASK_ENTRY}"' in page and 'base_commit = "aaa"' in page and "the known fix" in page


def test_a_title_cannot_break_out_of_the_data_block():
    data = mini()
    data["jobs"]["E"][0]["title"] = "</script><script>alert(1)</script>"
    page = render_guide(data, TASKS)
    assert page.count("<script") == render_guide(mini(), TASKS).count("<script")
    assert blob(page)["examples"]["pass"]["title_plain"] == "</script><script>alert(1)</script>"


def test_the_page_names_no_absolute_path():
    assert "/Users/" not in render_guide(mini(), TASKS)


def lower_arm_d_cap(data):
    data["summaries"]["D"]["over_cap"] = 1


def make_e_differ(data):
    data["summaries"]["E"]["verified"] = 12


def change_markup(data):
    data["markup"] = 0.25


def drop_version(data):
    del data["summaries"]["B"]


def pass_job_failed(data):
    data["jobs"]["E"][0]["solved"] = False


def remove_the_stop(data):
    data["replays"]["run-fail"]["marks"] = [m for m in data["replays"]["run-fail"]["marks"] if m["kind"] != "abort"]


def remove_the_job(data):
    data["jobs"]["E"] = data["jobs"]["E"][:1]


def remove_intake(data):
    data["replays"]["run-pass"]["marks"] = [m for m in data["replays"]["run-pass"]["marks"] if m["kind"] != "intake"]


def lose_the_quote_explanation(data):
    data["jobs"]["E"][0]["neighbours"] = None


@pytest.mark.parametrize(("change", "words"), [
    (lower_arm_d_cap, "over its cap"), (make_e_differ, "level with"), (change_markup, "50%"), (drop_version, "no version B"),
    (pass_job_failed, "passes"), (remove_the_stop, "stop"), (remove_the_job, "no such job"), (remove_intake, "intake"),
    (lose_the_quote_explanation, "similar-jobs"),
])
def test_the_guide_refuses_to_say_what_the_data_does_not_support(change, words):
    data = copy.deepcopy(mini())
    change(data)
    with pytest.raises(GuideError, match=words):
        render_guide(data, TASKS)


def test_the_guide_needs_the_example_task_in_the_manifest():
    with pytest.raises(GuideError, match="manifest"):
        render_guide(mini(), [])


@pytest.fixture
def with_data(monkeypatch):
    monkeypatch.setattr("margin.cli._console_page_data", lambda args, settings, with_links: (mini(), ""))


def test_the_command_writes_then_checks_the_page_and_notices_when_it_is_stale(tmp_path, with_data, capsys):
    out = tmp_path / "guide.html"
    tasks = tmp_path / "tasks.toml"
    tasks.write_text(
        f'[[task]]\nid = "{TASK_ENTRY}"\nsplit = "calibration"\nrepo = "https://github.com/o/r"\nbase_commit = "aaa"\n'
        'fix_commit = "bbb"\nissue_url = "u"\nissue_file = "f"\ntarget_tests = ["t"]\ntest_files = ["t.py"]\n')
    assert main(["guide", "--out", str(out), "--tasks-file", str(tasks)]) == 0 and out.exists()
    assert main(["guide", "--out", str(out), "--tasks-file", str(tasks), "--check"]) == 0
    out.write_text(out.read_text() + "\n<!-- edited by hand -->")
    assert main(["guide", "--out", str(out), "--tasks-file", str(tasks), "--check"]) == 1
    assert "is stale" in capsys.readouterr().out


def test_the_command_says_which_claim_failed(tmp_path, monkeypatch, capsys):
    data = mini()
    data["summaries"]["C"]["over_cap"] = 2
    monkeypatch.setattr("margin.cli._console_page_data", lambda args, settings, with_links: (data, ""))
    tasks = tmp_path / "tasks.toml"
    tasks.write_text("")
    assert main(["guide", "--out", str(tmp_path / "g.html"), "--tasks-file", str(tasks)]) == 1
    assert "over its cap" in capsys.readouterr().out and not (tmp_path / "g.html").exists()


def test_the_command_says_what_to_run_when_an_input_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("margin.cli._console_page_data", lambda args, settings, with_links: (None, "replays.json is missing"))
    assert main(["guide", "--out", str(tmp_path / "g.html")]) == 1
    assert "replays.json is missing" in capsys.readouterr().out
