import pytest

from margin.context import grep_search, naive_context


def test_grep_search_finds_lines_case_insensitively(repo):
    out = grep_search(repo, "ADD")
    assert "pkg/mathy.py:1:" in out


def test_grep_search_reports_no_matches_and_rejects_empty_queries(repo):
    assert grep_search(repo, "zzz-not-there") == "no matches"
    with pytest.raises(ValueError):
        grep_search(repo, "  ")


def test_naive_context_includes_source_but_not_tests(repo):
    ctx = naive_context(repo, 10_000)
    assert "### pkg/mathy.py" in ctx
    assert "tests/test_mathy.py" not in ctx


def test_naive_context_respects_the_character_budget(repo):
    assert naive_context(repo, 10) == ""
