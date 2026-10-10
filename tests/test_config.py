import os

from margin.config import Settings, load_dotenv


def test_defaults():
    s = Settings()
    assert s.target_markup == 0.5
    assert s.main_model == "claude-sonnet-5-5"
    assert s.fallback_model == "claude-haiku-5-5"
    assert (s.downgrade_at, s.narrow_at) == (0.6, 0.85)
    assert s.max_turns == 30
    assert s.expected_output_tokens == 4000


def test_from_env_overrides():
    s = Settings.from_env(
        {"MARGIN_TARGET_MARKUP": "0.8", "MARGIN_BENCH_BUDGET_USD": "12.5", "MARGIN_FAULT": "tool_timeout"}
    )
    assert s.target_markup == 0.8
    assert s.bench_budget_usd == 12.5
    assert s.fault == "tool_timeout"


def test_empty_env_values_are_ignored():
    assert Settings.from_env({"MARGIN_TARGET_MARKUP": ""}).target_markup == 0.5


def test_paths_are_under_root():
    s = Settings()
    assert s.ledger_path == s.root / "runs" / "ledger.jsonl"
    assert s.pricing_path == s.root / "pricing.toml"


def test_load_dotenv_does_not_override_and_skips_blanks(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nA_KEY=from_file\nB_KEY=\nC_KEY=\"quoted\"\n\nnot a pair\n")
    monkeypatch.setenv("A_KEY", "already")
    monkeypatch.delenv("B_KEY", raising=False)
    monkeypatch.delenv("C_KEY", raising=False)
    load_dotenv(env)
    assert os.environ["A_KEY"] == "already"
    assert "B_KEY" not in os.environ
    assert os.environ["C_KEY"] == "quoted"
