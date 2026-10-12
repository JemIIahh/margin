"""Settings and .env loading. Every tunable lives here so tests can override it."""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    runs_dir: Path = ROOT / "runs"
    ledger_path: Path = ROOT / "runs" / "ledger.jsonl"
    cache_dir: Path = ROOT / "bench" / "cache"
    pricing_path: Path = ROOT / "pricing.toml"
    target_markup: float = 0.5
    provider: str = "anthropic"  # anthropic | litellm (the event proxy)
    main_model: str = "claude-sonnet-5-5"
    fallback_model: str = "claude-haiku-5-5"
    main_effort: str = "medium"
    fallback_effort: str = "low"
    max_tokens: int = 16000
    max_turns: int = 30
    expected_output_tokens: int = 4000
    run_hard_cap_usd: float = 5.0
    cap_multiple: float = 1.0  # tests only: the governor's cap as a multiple of the quote's top; the price never changes
    bench_budget_usd: float = 50.0
    default_cost_usd: float = 1.0
    downgrade_at: float = 0.6
    narrow_at: float = 0.85
    narrow_turns: int = 4
    naive_context_chars: int = 120_000
    test_timeout_s: int = 120
    run_timeout_s: int = 7200  # one benchmark run, as a subprocess; a hung run must not block the batch
    fault: str | None = None
    # arm D: a coach model instead of the downgrade, stop-when-verified, run_python, lessons from past runs
    coach_model: str = ""  # empty: the main model coaches
    coach_max_notes: int = 2
    coach_stall_turns: int = 8
    stop_after_green_turns: int = 2
    python_timeout_s: int = 20
    lessons_path: Path = ROOT / "bench" / "lessons.jsonl"
    lessons_max: int = 5
    # arm E: Jev (TypeSafe) judges each turn; thresholds are code, chosen on the calibration runs only
    # (docs/notes/judge-calibration.md): only readiness to edit separated stuck runs from working ones
    judge_warmup_turns: int = 8
    judge_unready_below: float = 0.40  # coach: the agent still does not know what to change
    judge_ready_at: float = 0.65  # nudge: it knows what to change but keeps exploring
    judge_min_gap: int = 4
    judge_fallback_after: int = 3  # failed Jev calls in a row before arm D's stall rule takes over

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        overrides: dict[str, Any] = {}
        for env_name, field_name, cast in _ENV_FIELDS:
            value = env.get(env_name, "")
            if value != "":
                overrides[field_name] = cast(value)
        return cls(**overrides)


_ENV_FIELDS = [
    ("MARGIN_TARGET_MARKUP", "target_markup", float),
    ("MARGIN_BENCH_BUDGET_USD", "bench_budget_usd", float),
    ("MARGIN_RUN_HARD_CAP_USD", "run_hard_cap_usd", float),
    ("MARGIN_CAP_MULTIPLE", "cap_multiple", float),
    ("MARGIN_DOWNGRADE_AT", "downgrade_at", float),
    ("MARGIN_NARROW_AT", "narrow_at", float),
    ("MARGIN_MAX_TURNS", "max_turns", int),
    ("MARGIN_RUN_TIMEOUT_S", "run_timeout_s", int),
    ("MARGIN_PROVIDER", "provider", str),
    ("MARGIN_MAIN_MODEL", "main_model", str),
    ("MARGIN_FALLBACK_MODEL", "fallback_model", str),
    ("MARGIN_FAULT", "fault", str),
    ("MARGIN_COACH_MODEL", "coach_model", str),
    ("MARGIN_COACH_STALL_TURNS", "coach_stall_turns", int),
]


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE lines into os.environ without overriding existing values."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
