from collections import Counter

from margin.bench.tasks import load_tasks
from margin.config import ROOT

TASKS = load_tasks(ROOT / "bench" / "tasks.toml")


def test_manifest_has_the_agreed_split():
    assert len(TASKS) == 16
    assert Counter(t.split for t in TASKS) == {"calibration": 4, "evaluation": 12}
    assert len({t.id for t in TASKS}) == 16


def test_every_task_has_pinned_commits_issue_text_and_targets():
    for t in TASKS:
        assert len(t.base_commit) == 40 and len(t.fix_commit) == 40, t.id
        assert (ROOT / t.issue_file).read_text().strip(), t.id
        assert t.target_tests and t.test_files, t.id
        assert t.repo.startswith("https://github.com/"), t.id


def test_tasks_span_several_repositories():
    assert len({t.repo for t in TASKS}) >= 5
