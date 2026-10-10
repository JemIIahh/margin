# Margin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Margin: an issue-fixing agent that quotes a price band before it works, enforces a budget while it works, and proves its margin afterwards, with public evidence from neatlogs, Entire and cfo.ai.

**Architecture:** A Python 3.12 package (`src/margin`) whose agent loop calls the Anthropic SDK directly. Small single-purpose units (pricing, ledger, state, sandbox, verifier, tools, governor, quoter, graph adapter) are composed by `margin.run.execute_run`. A benchmark runner launches one subprocess per run so neatlogs tags are per-run, and a report module regenerates every published number from the JSONL ledger.

**Tech Stack:** Python 3.12 via `uv`, `anthropic` SDK, `neatlogs[anthropic]`, `pytest`, `ruff`, Entire CLI 0.11.4 + entire-graph v0.4.0, git worktrees.

**Spec:** `docs/superpowers/specs/2026-10-10-margin-design.md` (executors read it alongside this plan).

## Global Constraints

Copied from the spec unless marked *(plan)*.

- Python **3.12** pinned with `uv` (neatlogs supports 3.10–3.13; the machine default is 3.14).
- Models: main `claude-sonnet-5-5`, fallback `claude-haiku-5-5`. Prices live in `pricing.toml` and are verified before the first benchmark run.
- API rules for these two models *(plan, from the Claude API reference)*: never send `temperature`/`top_p`/`top_k`, `thinking: {"type": "disabled"}`, `budget_tokens`, forced `tool_choice` (`any`/`tool`), or assistant prefill (each returns 400). Omit `thinking` (adaptive is the default). Set effort with `output_config={"effort": ...}`. Append `response.content` to history unchanged and never edit earlier turns.
- Cost per job = model usage from `response.usage` (including cache-read and cache-write tokens) priced from `pricing.toml`.
- Economics: revenue = `price` if the verifier passes else `0`; flat price = mean cost of arm A's calibration runs × (1 + `TARGET_MARKUP`); quoted price = band upper cost × (1 + `TARGET_MARKUP`); `TARGET_MARKUP` default **0.5**, identical across arms.
- Quoter: k = **3** nearest rows, **arm B rows only**; band = `[p50·e^(−q), p50·e^(+q)]` with `q` = 90th percentile of `|ln(actual/predicted)|` over leave-one-out residuals; "p90" means the band's upper bound; fewer than **5** rows → median of all rows with the same `q`.
- Governor: cap = quote upper bound; at spend ≥ **0.6C** with no progress switch the edit/repair loop to Haiku; at ≥ **0.85C** narrow (stop exploring, cap remaining turns); abort when spend + next-call estimate ≥ **C**.
- Benchmark: **16 tasks = 4 calibration + 12 evaluation**; arm A on all 16, arm B on all 16, arm C on the 12 evaluation tasks plus a few calibration runs for tuning; run order A → B → C.
- Verifier: baseline suite run twice, ids that differ are flaky and excluded; verdict = target tests pass ∧ no new failing non-flaky ids.
- Sandbox: no free shell; file tools confined to the worktree; scrubbed subprocess environments (no API keys); repos pinned to a commit.
- neatlogs: call `neatlogs.init` **before** `import anthropic`; use the **project** API key (not the `nlw_` HTTP ingest key) in `NEATLOGS_API_KEY`; `python -m neatlogs doctor --probe` must pass (`TRACE_VISIBLE`, `TRACE_FINALIZED`). Tags are set once per process.
- Entire: enabled before the first commit; `push_sessions` stays `false` until the privacy gate in Task 20 passes.
- Git: repo-local identity `JemIIahh <275022204+JemIIahh@users.noreply.github.com>`; **no AI attribution trailers** in commits (standing user rule); never commit `.env` or any key.
- Execute this plan from a Claude Code session started inside `~/Desktop/margin`, so Entire records the build sessions.

## Decisions made while planning

These resolve gaps the spec left open. Each is visible to the reviewer.

1. **Visible test patch.** A task is the issue text plus the repo at `base_commit` with the fix commit's *test-file changes already applied and committed* in the worktree. The agent sees the failing tests. The verifier restores the protected test files before judging, and the tools reject edits to them.
2. **Narrow does not change the model.** Rung 2 (downgrade) is the only model switch, matching the spec literally. Jumping straight from rung 1 to rung 3 therefore stays on Sonnet.
3. **Downgrade restarts from a digest.** On downgrade the loop discards history and starts Haiku from a built-in digest (issue, current diff, latest test output). This avoids replaying Sonnet's thinking blocks to another model and shrinks the context. The digest is built by code, with no model call.
4. **One subprocess per run.** `margin bench` launches `python -m margin run ...` per task and arm, because neatlogs tags are fixed at `init`.
5. **Flat price at report time.** Arms A and B record `price_usd = 0`; the report applies the flat price (computed once from arm A calibration costs) so the number exists only after those runs finish.
6. **Cap check estimates the next call** as warm-cache prompt reads plus `expected_output_tokens` (default 4000). This is optimistic by the cache-miss amount, which the spec's "plus at most one in-flight call" allowance covers.
7. **Hard safety cap.** Arms A and B have no governor, so `run_hard_cap_usd` (default 5.0) aborts a runaway run. Such a run counts as unsolved.
8. **Spend estimate is unmeasured.** Roughly 60 runs at $0.3–1.5 each would be $20–90. Task 11's smoke run measures real cost; set `MARGIN_BENCH_BUDGET_USD` from that, not from this guess.
9. **A shared, frozen core.** Arms A, B and C differ only in context source, verifier feedback and the quote and governor. Defects found in the shared core (tools, prompts, sandbox, verifier) are fixed during Task 13's calibration step, then the core is frozen before any evaluation run.

## Review Focus

Input classes the spec implies but no feature task exercises by default. Each has a test in the task that owns the code.

1. A model reply with a missing, extra or wrongly typed tool argument, or an unknown tool name: the run continues with an error `tool_result` (Task 9).
2. The agent tries to edit a protected test file, write outside the worktree, or touch `.git` (Tasks 6 and 9).
3. A ledger or event-log file whose last line was cut off by a killed process: readers skip it with a warning (Tasks 4 and 5).
4. A quote requested with an empty ledger, fewer than 5 rows, or all-equal costs: a finite, non-degenerate band, no division by zero (Task 14).
5. A baseline or final suite run that fails to collect, writes no JUnit file, or times out: the verdict is "not solved" with a reason, never a crash (Task 7).

## File Structure

```
pyproject.toml, Makefile, .env.example, pricing.toml
src/margin/
  __init__.py, __main__.py, cli.py        entry points
  config.py                               Settings, load_dotenv
  telemetry.py                            neatlogs shim (no-op without a key)
  errors.py                               TransientModelError, SimulatedCrash
  pricing.py                              Usage, PriceTable, SpendMeter
  ledger.py                               RunRecord, Ledger, settle, render_receipt
  state.py                                RunState: event log + checkpoint
  sandbox.py                              Sandbox: worktree file tools, scrubbed pytest
  verify.py                               junit parsing, Baseline, judge, final_verdict
  context.py                              GraphContext (entire graph), naive_context, path/identifier regexes
  quote.py                                Features, Quote, Quoter, evaluate_loo
  governor.py                             Rung, Decision, Governor, NullGovernor
  faults.py                               FaultInjector
  model.py                                build_request, AnthropicModel, is_transient
  run.py                                  execute_run (one task, one arm)
  agent/{prompts,tools,loop}.py
  bench/{tasks,runner,report,cfo}.py
bench/                                    data: tasks.toml, issues/, patches/ (code lives in src/margin/bench)
scripts/{hello_trace,make_smoke_repo}.py
tests/                                    mirrors src; tests/fakes.py, tests/conftest.py
docs/{evidence,business,notes}/, EVIDENCE.md
```

---

### Task 1: Scaffold, settings and telemetry shim

**Files:**
- Create: `pyproject.toml` (via `uv init`), `.python-version`, `Makefile`, `.env.example`
- Create: `src/margin/__init__.py`, `src/margin/config.py`, `src/margin/telemetry.py`
- Test: `tests/test_config.py`, `tests/test_telemetry.py`

**Interfaces:**
- Produces: `margin.config.ROOT: Path`; `Settings` (frozen dataclass; fields listed in Step 3) with `Settings.from_env(env=None)`; `load_dotenv(path=None)`.
- Produces: `margin.telemetry.init_telemetry(workflow_name: str, tags: list[str]) -> bool`; `shutdown_telemetry() -> None`; `span(kind: str, name: str | None = None, **kwargs)` decorator; `trace(name: str, kind: str, **attrs)` context manager yielding an object with `set_attribute(key, value)`; `coerce(value)`.

- [ ] **Step 1: Create the project**

```bash
cd ~/Desktop/margin
uv init --package --name margin --python 3.12 --no-readme .
uv add anthropic "neatlogs[anthropic]" defusedxml
uv add --dev pytest ruff
sed -i '' 's/^margin = .*/margin = "margin.cli:main"/' pyproject.toml
cat >> pyproject.toml <<'EOF'

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
src = ["src", "tests"]
EOF
printf '__version__ = "0.1.0"\n' > src/margin/__init__.py
uv run python -c "import sys; print(sys.version)"
```

Expected: a `3.12.x` version string and no errors.

- [ ] **Step 2: Write the failing tests**

`tests/test_config.py`:

```python
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
```

`tests/test_telemetry.py`:

```python
from margin import telemetry


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("NEATLOGS_API_KEY", raising=False)
    assert telemetry.init_telemetry("margin", ["arm:A"]) is False


def test_trace_is_a_noop_when_disabled():
    with telemetry.trace("x", kind="TOOL", **{"margin.n": 1}) as sp:
        sp.set_attribute("margin.y", "z")


def test_span_decorator_passes_through():
    @telemetry.span(kind="TOOL", name="f")
    def f(a, b=2):
        return a + b

    assert f(1) == 3


def test_coerce_attribute_values():
    assert telemetry.coerce(True) is True
    assert telemetry.coerce(3) == 3
    assert telemetry.coerce("s") == "s"
    assert telemetry.coerce(0.123456789) == "0.123457"
    assert telemetry.coerce({"a": 1}) == '{"a": 1}'
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py tests/test_telemetry.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.config'` (and `margin.telemetry`).

- [ ] **Step 4: Implement `config.py`**

```python
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
    main_model: str = "claude-sonnet-5-5"
    fallback_model: str = "claude-haiku-5-5"
    main_effort: str = "medium"
    fallback_effort: str = "low"
    max_tokens: int = 16000
    max_turns: int = 30
    expected_output_tokens: int = 4000
    run_hard_cap_usd: float = 5.0
    bench_budget_usd: float = 50.0
    default_cost_usd: float = 1.0
    downgrade_at: float = 0.6
    narrow_at: float = 0.85
    narrow_turns: int = 4
    naive_context_chars: int = 120_000
    test_timeout_s: int = 120
    fault: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
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
    ("MARGIN_DOWNGRADE_AT", "downgrade_at", float),
    ("MARGIN_NARROW_AT", "narrow_at", float),
    ("MARGIN_MAX_TURNS", "max_turns", int),
    ("MARGIN_MAIN_MODEL", "main_model", str),
    ("MARGIN_FALLBACK_MODEL", "fallback_model", str),
    ("MARGIN_FAULT", "fault", str),
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
```

- [ ] **Step 5: Implement `telemetry.py`**

```python
"""neatlogs shim. Without NEATLOGS_API_KEY every call is a no-op, so tests and dry runs need no network.

neatlogs.init must run before `anthropic` is imported (auto-instrumentation attaches at import),
so nothing in this package imports anthropic at module level.
"""
from __future__ import annotations

import contextlib
import functools
import json
import os
from collections.abc import Callable, Iterator
from typing import Any

_enabled = False


def init_telemetry(workflow_name: str, tags: list[str]) -> bool:
    global _enabled
    key = os.environ.get("NEATLOGS_API_KEY")
    if not key:
        return False
    import neatlogs

    neatlogs.init(api_key=key, workflow_name=workflow_name, instrumentations=["anthropic"], tags=tags)
    _enabled = True
    return True


def shutdown_telemetry() -> None:
    if not _enabled:
        return
    import neatlogs

    neatlogs.flush()
    neatlogs.shutdown()


def coerce(value: Any) -> Any:
    """neatlogs documents str, int and bool attribute values; everything else becomes a string."""
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return f"{value:.6f}"
    return json.dumps(value, sort_keys=True, default=str)


class _NullSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        return None


def span(kind: str, name: str | None = None, **kwargs: Any) -> Callable:
    """Decorator: a neatlogs span when telemetry is on, otherwise a pass-through."""

    def decorate(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kw: Any) -> Any:
            if not _enabled:
                return fn(*args, **kw)
            import neatlogs

            return neatlogs.span(kind=kind, name=name or fn.__name__, **kwargs)(fn)(*args, **kw)

        return wrapper

    return decorate


@contextlib.contextmanager
def trace(name: str, kind: str, **attrs: Any) -> Iterator[Any]:
    if not _enabled:
        yield _NullSpan()
        return
    import neatlogs

    with neatlogs.trace(name, kind=kind) as sp:
        for key, value in attrs.items():
            sp.set_attribute(key, coerce(value))
        yield sp
```

- [ ] **Step 6: Add `Makefile` and `.env.example`**

`Makefile`:

```make
.PHONY: test lint
test:
	uv run pytest
lint:
	uv run ruff check src tests
```

`.env.example`:

```
# Copy to .env (gitignored). Never commit real keys.
ANTHROPIC_API_KEY=
# neatlogs PROJECT api key from Settings -> API keys (not the nlw_ HTTP ingest key)
NEATLOGS_API_KEY=
MARGIN_BENCH_BUDGET_USD=50
```

- [ ] **Step 7: Run tests and lint**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 9 passed; ruff reports no errors (fix any import-order or line-length findings it prints).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock .python-version Makefile .env.example src tests
git commit -m "chore: scaffold project, settings and telemetry shim"
```

---

### Task 2: neatlogs hello-trace (M0)

Requires the builder's `NEATLOGS_API_KEY` (project key) and `ANTHROPIC_API_KEY` in `.env`. If either is missing, stop and ask. Tasks 3–10 do not need the keys, so they can proceed while the builder gets them.

**Files:**
- Create: `scripts/hello_trace.py`, `docs/notes/neatlogs-findings.md`
- Modify: `.gitignore` (add `.mcp.json`)

**Interfaces:**
- Consumes: `margin.config.load_dotenv`, `margin.telemetry` (Task 1).
- Produces: a recorded decision, in `docs/notes/neatlogs-findings.md`, on which span kinds, attribute keys and error rendering work. Later tasks follow it.

- [ ] **Step 1: Create `.env` and confirm it is ignored**

```bash
cd ~/Desktop/margin
cp .env.example .env     # the builder fills in both keys
git check-ignore .env && echo "ignored: ok"
```

Expected: prints `.env` then `ignored: ok`.

- [ ] **Step 2: Run the local and probe doctors**

```bash
uv run python -m neatlogs doctor --local --json
set -a; source .env; set +a
uv run python -m neatlogs doctor --probe --json
```

Expected: local doctor passes; probe output shows `TRACE_VISIBLE` and `TRACE_FINALIZED` as PASS. If the probe returns 401, the wrong key was used (the `nlw_` ingest key); swap in the project key.

- [ ] **Step 3: Write `scripts/hello_trace.py`**

```python
"""Hello-trace: proves neatlogs receives our span kinds, attributes and a failing span."""
from margin.config import load_dotenv

load_dotenv()

from margin import telemetry  # noqa: E402

telemetry.init_telemetry("margin", ["arm:hello", "version:v0"])

import anthropic  # noqa: E402  (must come after init so it is auto-instrumented)


@telemetry.span(kind="WORKFLOW", name="hello.run")
def run() -> str:
    reply = ""
    with telemetry.trace("turn-0", kind="AGENT", **{"margin.turn": 0, "margin.model": "claude-haiku-5-5"}):
        client = anthropic.Anthropic(max_retries=0)
        msg = client.messages.create(
            model="claude-haiku-5-5",
            max_tokens=1024,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Reply with the single word: pong"}],
        )
        reply = next((b.text for b in msg.content if b.type == "text"), "")
        with telemetry.trace("read_file", kind="TOOL", **{"margin.path": "README.md"}):
            pass
        with telemetry.trace(
            "governor", kind="GUARDRAIL", **{"margin.rung": "CONTINUE", "margin.spend_usd": 0.0001}
        ):
            pass
        try:
            with telemetry.trace("injected-failure", kind="TOOL"):
                raise RuntimeError("injected failure to check error rendering")
        except RuntimeError:
            pass
    return reply


if __name__ == "__main__":
    print(run())
    telemetry.shutdown_telemetry()
```

- [ ] **Step 4: Run it**

Run: `uv run python scripts/hello_trace.py`
Expected: prints a reply containing `pong` and exits 0. The model call costs well under one cent.

- [ ] **Step 5: Inspect the trace in the dashboard (manual, builder present)**

At app.neatlogs.com → Traces, open the newest `margin` trace and record in `docs/notes/neatlogs-findings.md`:
- whether the span tree shows WORKFLOW → AGENT → (LLM, TOOL, GUARDRAIL) with the right kinds;
- whether the `margin.*` attributes appear on spans;
- whether the `injected-failure` span renders as an error;
- whether the tags `arm:hello` and `version:v0` are filterable;
- whether the LLM span shows token usage and cost.

- [ ] **Step 6: Apply fallbacks if anything differs**

- If `trace(kind="AGENT")` or `kind="GUARDRAIL"` raises `ValueError`, change the shim: replace the body of `trace()` with an inner function decorated by `neatlogs.span(kind=..., name=...)` and call it inside `with`-like helper; keep the same public signature. Record the change in the findings file.
- If `margin.*` attributes do not show up, rename them to `neatlogs.guardrail.<field>` (for governor spans) and `neatlogs.tool.<field>` (for tool spans) in one place: a `ATTR_PREFIX` constant added to `telemetry.py`, applied inside `trace()`.
- If the failing span is not marked as an error, set `span.set_attribute("error", True)` and `("error.message", str(exc))` inside the shim's `trace()` except-branch.

- [ ] **Step 7: Connect the neatlogs MCP server to Claude Code (local scope; the key never enters the repo)**

```bash
cd ~/Desktop/margin
set -a; source .env; set +a
printf '\n# local MCP config can embed a key\n.mcp.json\n' >> .gitignore
claude mcp add --transport http --scope local neatlogs https://ingest.neatlogs.com/mcp \
  --header "Authorization: Bearer $NEATLOGS_API_KEY"
claude mcp list
git status --short
```

Expected: `neatlogs` appears in the list and `git status` shows only the `.gitignore` change. If the builder prefers the wizard (`npx @neatlogs/wizard mcp --api-key KEY`) and it writes a `.mcp.json` into the repo, move that entry into local scope with the command above and delete the file. Never commit a file containing the key.

- [ ] **Step 8: Check the MCP tools work (needs a new Claude Code session in this repo)**

Start a fresh session in `~/Desktop/margin`, ask it to call the neatlogs `whoami` tool and then `search_traces` for "hello". Expected: the project is identified and the hello trace is found. Record the result, and the tool names that appeared, in `docs/notes/neatlogs-findings.md`. If the tools are missing, the session was started before the server was added: restart it.

- [ ] **Step 9: Commit**

```bash
git add scripts/hello_trace.py docs/notes/neatlogs-findings.md src/margin/telemetry.py .gitignore
git commit -m "feat: neatlogs hello-trace, recorded findings and local MCP connection"
```

---

### Task 3: Pricing and spend meter

**Files:**
- Create: `pricing.toml`, `src/margin/pricing.py`
- Test: `tests/test_pricing.py`

**Interfaces:**
- Produces: `Usage(input_tokens=0, output_tokens=0, cache_write_tokens=0, cache_read_tokens=0)` (frozen dataclass) with `.prompt_tokens`, `Usage.from_api(obj)`, `.to_dict()`, `Usage.from_dict(d)`, `+`.
- Produces: `ModelPrice(input, output, cache_write, cache_read, long_prompt_threshold=None, long_prompt_multiplier=1.0).cost(usage) -> float`.
- Produces: `PriceTable.load(path)`, `.cost(model: str, usage: Usage) -> float`, `.estimate_next_call(model, prompt_tokens: int, expected_output_tokens: int) -> float`.
- Produces: `SpendMeter(prices)` with `.record(model, usage) -> float`, `.total_usd`, `.total_tokens`, `.usage_by_model: dict[str, Usage]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_pricing.py`:

```python
from types import SimpleNamespace

import pytest

from margin.config import ROOT
from margin.pricing import PriceTable, SpendMeter, Usage


@pytest.fixture(scope="module")
def prices():
    return PriceTable.load(ROOT / "pricing.toml")


def test_sonnet_cost_all_components(prices):
    u = Usage(input_tokens=1000, output_tokens=2000, cache_write_tokens=500, cache_read_tokens=10_000)
    assert prices.cost("claude-sonnet-5-5", u) == pytest.approx(0.02525)


def test_haiku_long_prompt_multiplier_applies_above_threshold(prices):
    u = Usage(input_tokens=150_000, output_tokens=1000)
    assert prices.cost("claude-haiku-5-5", u) == pytest.approx(0.0775)


def test_haiku_at_threshold_is_not_long(prices):
    u = Usage(input_tokens=100_000, output_tokens=1000)
    assert prices.cost("claude-haiku-5-5", u) == pytest.approx((100_000 * 0.10 + 1000 * 0.50) / 1e6)


def test_unknown_model_raises(prices):
    with pytest.raises(KeyError, match="no price for model"):
        prices.cost("nope", Usage())


def test_usage_from_api_handles_none_fields():
    api = SimpleNamespace(
        input_tokens=10, output_tokens=5, cache_creation_input_tokens=None, cache_read_input_tokens=None
    )
    assert Usage.from_api(api) == Usage(10, 5, 0, 0)


def test_estimate_next_call_assumes_warm_cache(prices):
    est = prices.estimate_next_call("claude-sonnet-5-5", prompt_tokens=100_000, expected_output_tokens=4000)
    assert est == pytest.approx(100_000 * 0.20 / 1e6 + 4000 * 10 / 1e6)


def test_meter_accumulates_per_model(prices):
    m = SpendMeter(prices)
    m.record("claude-sonnet-5-5", Usage(input_tokens=1_000_000))
    m.record("claude-haiku-5-5", Usage(output_tokens=1_000_000))
    assert m.total_usd == pytest.approx(2.0 + 0.5)
    assert m.total_tokens == 2_000_000
    assert set(m.usage_by_model) == {"claude-sonnet-5-5", "claude-haiku-5-5"}


def test_usage_add_and_roundtrip():
    a, b = Usage(1, 2, 3, 4), Usage(10, 20, 30, 40)
    assert a + b == Usage(11, 22, 33, 44)
    assert Usage.from_dict(a.to_dict()) == a
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_pricing.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.pricing'`.

- [ ] **Step 3: Create `pricing.toml`**

```toml
# USD per million tokens.
# Source: Anthropic published pricing as cached in the claude-api skill on 2026-10-06.
# Step 6 of Task 3 re-verifies these against the live pricing page and updates this comment.

[models."claude-sonnet-5-5"]
input = 2.00
output = 10.00
cache_write = 2.50     # 1.25x input (5-minute TTL)
cache_read = 0.20      # stated by Anthropic

[models."claude-haiku-5-5"]
input = 0.10
output = 0.50
cache_write = 0.125    # assumed 1.25x input; verify
cache_read = 0.01      # assumed 0.1x input; verify
long_prompt_threshold = 100000   # prompts above 100K tokens: $0.50 / $2.50
long_prompt_multiplier = 5.0     # assumed to scale cache rates too; verify
```

- [ ] **Step 4: Implement `pricing.py`**

```python
"""Token usage, price table and the live spend meter used by the governor and the ledger."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

M = 1_000_000


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @classmethod
    def from_api(cls, usage: Any) -> "Usage":
        def n(name: str) -> int:
            return int(getattr(usage, name, 0) or 0)

        return cls(
            n("input_tokens"), n("output_tokens"), n("cache_creation_input_tokens"), n("cache_read_input_tokens")
        )

    @classmethod
    def from_dict(cls, d: dict) -> "Usage":
        return cls(**{k: int(d.get(k, 0)) for k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
        )


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_write: float
    cache_read: float
    long_prompt_threshold: int | None = None
    long_prompt_multiplier: float = 1.0

    def cost(self, u: Usage) -> float:
        mult = 1.0
        if self.long_prompt_threshold is not None and u.prompt_tokens > self.long_prompt_threshold:
            mult = self.long_prompt_multiplier
        raw = (
            u.input_tokens * self.input
            + u.output_tokens * self.output
            + u.cache_write_tokens * self.cache_write
            + u.cache_read_tokens * self.cache_read
        )
        return mult * raw / M


class PriceTable:
    def __init__(self, models: dict[str, ModelPrice]):
        self.models = models

    @classmethod
    def load(cls, path: Path) -> "PriceTable":
        data = tomllib.loads(Path(path).read_text())
        return cls({name: ModelPrice(**fields) for name, fields in data["models"].items()})

    def _price(self, model: str) -> ModelPrice:
        try:
            return self.models[model]
        except KeyError:
            raise KeyError(f"no price for model {model!r}; add it to pricing.toml") from None

    def cost(self, model: str, usage: Usage) -> float:
        return self._price(model).cost(usage)

    def estimate_next_call(self, model: str, prompt_tokens: int, expected_output_tokens: int) -> float:
        """Optimistic: the prompt is read from a warm cache, output is the expected length."""
        return self.cost(model, Usage(output_tokens=expected_output_tokens, cache_read_tokens=prompt_tokens))


class SpendMeter:
    def __init__(self, prices: PriceTable):
        self.prices = prices
        self.total_usd = 0.0
        self.usage_by_model: dict[str, Usage] = {}

    def record(self, model: str, usage: Usage) -> float:
        cost = self.prices.cost(model, usage)
        self.total_usd += cost
        self.usage_by_model[model] = self.usage_by_model.get(model, Usage()) + usage
        return cost

    @property
    def total_tokens(self) -> int:
        return sum(u.total_tokens for u in self.usage_by_model.values())
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_pricing.py`
Expected: 8 passed.

- [ ] **Step 6: Verify the prices against the live page**

Open `https://platform.claude.com/docs/en/about-claude/pricing` (if it has moved, use the Pricing row in the claude-api skill's `shared/live-sources.md`). Confirm the Sonnet 5.5 and Haiku 5.5 rows, including Haiku's cache-write, cache-read and long-prompt rates. Correct `pricing.toml` where it differs, remove the "assumed" and "verify" notes you confirmed, and replace the header comment with the verification date. Update test expectations only if a rate changed.

- [ ] **Step 7: Commit**

```bash
git add pricing.toml src/margin/pricing.py tests/test_pricing.py
git commit -m "feat: price table, usage and spend meter"
```

---

### Task 4: Ledger, settlement and receipts

**Files:**
- Create: `src/margin/ledger.py`
- Test: `tests/test_ledger.py`

**Interfaces:**
- Produces: `RunRecord` dataclass with fields `run_id, task_id, arm, split, solved, cost_usd, price_usd, revenue_usd, margin_usd, tokens_total` (required) and `features: dict`, `quote: dict | None`, `rung_events: list`, `abort_reason: str | None`, `duration_s: float`, `fault: str | None`, `recoveries: int`, `started_at: str`, `trace_tags: list`, `verdict_reason: str` (all defaulted); `.to_dict()`, `RunRecord.from_dict(d)`.
- Produces: `settle(price_usd: float, solved: bool, cost_usd: float) -> tuple[float, float]` returning `(revenue, margin)`.
- Produces: `Ledger(path)` with `.append(rec)`, `.rows(arm=None) -> list[RunRecord]`, `.latest(arm) -> dict[str, RunRecord]` (last benchmark row per task wins; rows with `fault` set or a `version:demo*` tag are ignored).
- Produces: `render_receipt(rec) -> str` (markdown).

- [ ] **Step 1: Write the failing tests**

`tests/test_ledger.py`:

```python
import pytest

from margin.ledger import Ledger, RunRecord, render_receipt, settle


def rec(run_id="r1", task="t1", arm="A", solved=True, cost=1.0, price=1.5, **kw):
    revenue, margin = settle(price, solved, cost)
    return RunRecord(
        run_id=run_id, task_id=task, arm=arm, split="evaluation", solved=solved, cost_usd=cost,
        price_usd=price, revenue_usd=revenue, margin_usd=margin, tokens_total=1000, **kw,
    )


def test_settle_pays_only_for_verified_fixes():
    assert settle(1.5, True, 1.0) == (1.5, 0.5)
    assert settle(1.5, False, 1.0) == (0.0, -1.0)


def test_append_and_read_roundtrip(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(rec(features={"issue_tokens": 10}, quote={"p50": 1.0, "lo": 0.5, "hi": 2.0}))
    rows = ledger.rows()
    assert len(rows) == 1
    assert rows[0].features == {"issue_tokens": 10}
    assert rows[0].quote["hi"] == 2.0


def test_latest_keeps_last_row_per_task_and_filters_arm(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(rec(run_id="r1", task="t1", arm="A", cost=1.0))
    ledger.append(rec(run_id="r2", task="t1", arm="A", cost=2.0))
    ledger.append(rec(run_id="r3", task="t1", arm="B", cost=3.0))
    latest = ledger.latest("A")
    assert set(latest) == {"t1"}
    assert latest["t1"].run_id == "r2"


def test_latest_ignores_fault_and_demo_runs(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(rec(run_id="real", task="t1", arm="C", cost=1.0))
    ledger.append(rec(run_id="fault", task="t1", arm="C", cost=9.0, fault="flaky_tests"))
    ledger.append(rec(run_id="demo", task="t1", arm="C", cost=9.0, trace_tags=["version:demo-x"]))
    assert ledger.latest("C")["t1"].run_id == "real"


def test_truncated_last_line_is_skipped_with_a_warning(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append(rec(run_id="ok"))
    with path.open("a") as f:
        f.write('{"run_id": "cut", "task_id": ')
    with pytest.warns(UserWarning, match="unreadable ledger line"):
        rows = ledger.rows()
    assert [r.run_id for r in rows] == ["ok"]


def test_missing_file_reads_as_empty(tmp_path):
    assert Ledger(tmp_path / "nope.jsonl").rows() == []


def test_receipt_shows_quote_verdict_and_margin():
    r = rec(
        quote={"p50": 1.0, "lo": 0.5, "hi": 2.0},
        rung_events=[{"turn": 3, "rung": "DOWNGRADE", "reason": "no progress at 60% of cap"}],
        verdict_reason="solved",
    )
    text = render_receipt(r)
    assert "$0.5000 – $2.0000" in text
    assert "DOWNGRADE" in text
    assert "verified" in text
    assert "$0.5000" in text  # margin


def test_receipt_for_flat_priced_failure():
    text = render_receipt(rec(solved=False, abort_reason="over budget", verdict_reason="target tests still failing"))
    assert "none (flat price)" in text
    assert "not verified" in text
    assert "over budget" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ledger.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.ledger'`.

- [ ] **Step 3: Implement `ledger.py`**

```python
"""Append-only JSONL ledger of runs, settlement arithmetic and the markdown receipt."""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class RunRecord:
    run_id: str
    task_id: str
    arm: str
    split: str
    solved: bool
    cost_usd: float
    price_usd: float
    revenue_usd: float
    margin_usd: float
    tokens_total: int
    features: dict = field(default_factory=dict)
    quote: dict | None = None
    rung_events: list = field(default_factory=list)
    abort_reason: str | None = None
    duration_s: float = 0.0
    fault: str | None = None
    recoveries: int = 0
    started_at: str = ""
    trace_tags: list = field(default_factory=list)
    verdict_reason: str = ""

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "RunRecord":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def settle(price_usd: float, solved: bool, cost_usd: float) -> tuple[float, float]:
    """Pay-per-verified-fix: revenue is the price if solved, else zero."""
    revenue = price_usd if solved else 0.0
    return revenue, revenue - cost_usd


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, rec: RunRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec.to_dict(), sort_keys=True) + "\n")
            f.flush()

    def rows(self, arm: str | None = None) -> list[RunRecord]:
        if not self.path.exists():
            return []
        out: list[RunRecord] = []
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = RunRecord.from_dict(json.loads(line))
            except (json.JSONDecodeError, TypeError, KeyError):
                warnings.warn(f"skipping unreadable ledger line {n}", stacklevel=2)
                continue
            if arm is None or row.arm == arm:
                out.append(row)
        return out

    def latest(self, arm: str) -> dict[str, RunRecord]:
        """Last benchmark row per task. Fault-injection and demo runs never replace benchmark rows."""
        out: dict[str, RunRecord] = {}
        for row in self.rows(arm):
            if row.fault or any(tag.startswith("version:demo") for tag in row.trace_tags):
                continue
            out[row.task_id] = row
        return out


def render_receipt(r: RunRecord) -> str:
    if r.quote:
        quote = f"${r.quote['lo']:.4f} – ${r.quote['hi']:.4f} (p50 ${r.quote['p50']:.4f})"
    else:
        quote = "none (flat price)"
    rungs = "\n".join(f"- turn {e['turn']}: **{e['rung']}**: {e['reason']}" for e in r.rung_events) or "- none"
    verdict = "verified" if r.solved else "not verified"
    lines = [
        f"# Receipt: {r.task_id} (arm {r.arm})",
        "",
        f"- Quoted cost band: {quote}",
        f"- Price: ${r.price_usd:.4f}",
        f"- Actual cost: ${r.cost_usd:.4f} ({r.tokens_total} tokens)",
        f"- Verdict: **{verdict}** ({r.verdict_reason or 'n/a'})",
        f"- Revenue: ${r.revenue_usd:.4f}",
        f"- Margin: ${r.margin_usd:.4f}",
    ]
    if r.abort_reason:
        lines.append(f"- Stopped early: {r.abort_reason}")
    lines += ["", "## Governor decisions", rungs, ""]
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_ledger.py`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/margin/ledger.py tests/test_ledger.py
git commit -m "feat: run ledger, settlement and receipts"
```

---

### Task 5: Run state (event log, checkpoint, resume primitives)

**Files:**
- Create: `src/margin/errors.py`, `src/margin/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `margin.errors.TransientModelError(Exception)`, `margin.errors.SimulatedCrash(Exception)`.
- Produces: `RunState(run_dir)` with `.dir`, `.log(event: str, **data)`, `.events(event: str | None = None) -> list[dict]`, `.usage_events() -> list[tuple[str, Usage]]`, `.restore_meter(meter)`, `.save_checkpoint(*, turn, messages, model, effort, rung, extra) -> None`, `.load_checkpoint() -> dict | None`; `CorruptCheckpoint(Exception)`.
- The checkpoint dict has keys `turn, messages, model, effort, rung, extra, digest`.

- [ ] **Step 1: Write the failing tests**

`tests/test_state.py`:

```python
import json

import pytest

from margin.pricing import PriceTable, SpendMeter, Usage
from margin.config import ROOT
from margin.state import CorruptCheckpoint, RunState


def test_log_and_read_events(tmp_path):
    s = RunState(tmp_path / "run")
    s.log("model_usage", model="m", usage={"input_tokens": 1})
    s.log("retry", attempt=1)
    assert [e["type"] for e in s.events()] == ["model_usage", "retry"]
    assert len(s.events("retry")) == 1


def test_truncated_last_event_is_skipped(tmp_path):
    s = RunState(tmp_path / "run")
    s.log("a")
    with s.events_path.open("a") as f:
        f.write('{"type": "b", "x":')
    assert [e["type"] for e in s.events()] == ["a"]


def test_usage_events_restore_the_meter(tmp_path):
    s = RunState(tmp_path / "run")
    u = Usage(input_tokens=1_000_000)
    s.log("model_usage", model="claude-sonnet-5-5", usage=u.to_dict(), cost=2.0)
    meter = SpendMeter(PriceTable.load(ROOT / "pricing.toml"))
    s.restore_meter(meter)
    assert meter.total_usd == pytest.approx(2.0)


def test_checkpoint_roundtrip(tmp_path):
    s = RunState(tmp_path / "run")
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": [{"type": "text", "text": "yo"}]}]
    s.save_checkpoint(turn=2, messages=msgs, model="claude-sonnet-5-5", effort="medium", rung="CONTINUE", extra={"k": 1})
    ck = s.load_checkpoint()
    assert ck["turn"] == 2
    assert ck["messages"] == msgs
    assert ck["extra"] == {"k": 1}
    assert not list(s.dir.glob("*.tmp"))


def test_no_checkpoint_returns_none(tmp_path):
    assert RunState(tmp_path / "run").load_checkpoint() is None


def test_tampered_checkpoint_is_rejected(tmp_path):
    s = RunState(tmp_path / "run")
    s.save_checkpoint(turn=1, messages=[{"role": "user", "content": "hi"}], model="m", effort="low", rung="CONTINUE", extra={})
    data = json.loads(s.checkpoint_path.read_text())
    data["messages"][0]["content"] = "tampered"
    s.checkpoint_path.write_text(json.dumps(data))
    with pytest.raises(CorruptCheckpoint):
        s.load_checkpoint()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_state.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.state'`.

- [ ] **Step 3: Implement `errors.py` and `state.py`**

`src/margin/errors.py`:

```python
class TransientModelError(Exception):
    """A model-call failure worth retrying (overload, rate limit, dropped connection)."""


class SimulatedCrash(Exception):
    """Raised by tests and the resume demo to emulate a killed process after a checkpoint."""
```

`src/margin/state.py`:

```python
"""Append-only event log plus an atomic per-turn checkpoint under runs/<id>/."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from margin.pricing import SpendMeter, Usage


class CorruptCheckpoint(Exception):
    pass


def _digest(messages: list) -> str:
    blob = json.dumps(messages, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


class RunState:
    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "events.jsonl"
        self.checkpoint_path = self.dir / "checkpoint.json"

    def log(self, event: str, **data: Any) -> None:
        line = {"t": round(time.time(), 3), "type": event, **data}
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, sort_keys=True, default=str) + "\n")
            f.flush()

    def events(self, event: str | None = None) -> list[dict]:
        if not self.events_path.exists():
            return []
        out = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a killed process can leave a partial last line
            if event is None or row.get("type") == event:
                out.append(row)
        return out

    def usage_events(self) -> list[tuple[str, Usage]]:
        return [(e["model"], Usage.from_dict(e["usage"])) for e in self.events("model_usage")]

    def restore_meter(self, meter: SpendMeter) -> None:
        for model, usage in self.usage_events():
            meter.record(model, usage)

    def save_checkpoint(
        self, *, turn: int, messages: list, model: str, effort: str, rung: str, extra: dict
    ) -> None:
        payload = {
            "turn": turn, "messages": messages, "model": model, "effort": effort,
            "rung": rung, "extra": extra, "digest": _digest(messages),
        }
        tmp = self.checkpoint_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.checkpoint_path)

    def load_checkpoint(self) -> dict | None:
        if not self.checkpoint_path.exists():
            return None
        data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        if data.get("digest") != _digest(data.get("messages", [])):
            raise CorruptCheckpoint(f"{self.checkpoint_path} failed its digest check")
        return data
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_state.py`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/margin/errors.py src/margin/state.py tests/test_state.py
git commit -m "feat: run state with event log and verified checkpoints"
```

---

### Task 6: Sandbox (confined file tools, scrubbed pytest)

**Files:**
- Create: `src/margin/sandbox.py`, `tests/conftest.py`
- Test: `tests/test_sandbox.py`

**Interfaces:**
- Produces: `PathEscape`, `EditError`, `SuiteTimeout` (exceptions).
- Produces: `Sandbox(root, venv_python, pythonpath, home, test_timeout_s=120)` with `.root: Path` (resolved), `.home: Path`, `.resolve(rel) -> Path` (raises `PathEscape`), `.relpath(rel) -> str` (posix, relative to root), `.read_file(rel, start_line=None, end_line=None, max_chars=20000) -> str` (numbered lines), `.write_file(rel, content)`, `.edit_file(rel, old, new)` (exactly one match), `.git_diff() -> str` (stages everything, returns the staged diff vs HEAD), `.restore_paths(paths)`, `.exclude(patterns)`, `.scrubbed_env() -> dict`, `.run_pytest(args, junit_path, timeout_s=None) -> CompletedProcess` (raises `SuiteTimeout`).
- Produces: pytest fixtures `repo` (a git repo with a failing `test_add`) and `sandbox` in `tests/conftest.py`, and `git(cwd, *args)`.

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import subprocess
import sys
from pathlib import Path

import pytest

from margin.sandbox import Sandbox

BUGGY = "def add(a, b):\n    return a - b\n"
TESTS = (
    "from pkg.mathy import add\n\n\n"
    "def test_add():\n    assert add(1, 2) == 3\n\n\n"
    "def test_other():\n    assert True\n"
)


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "mathy.py").write_text(BUGGY)
    (root / "tests" / "test_mathy.py").write_text(TESTS)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture
def sandbox(repo, tmp_path) -> Sandbox:
    return Sandbox(
        root=repo, venv_python=Path(sys.executable), pythonpath=["."],
        home=tmp_path / "home", test_timeout_s=60,
    )
```

- [ ] **Step 2: Write the failing tests**

`tests/test_sandbox.py`:

```python
import subprocess
import sys

import pytest

from margin.sandbox import EditError, PathEscape, Sandbox, SuiteTimeout


def test_read_file_numbers_lines_and_honours_ranges(sandbox):
    assert sandbox.read_file("pkg/mathy.py").splitlines()[0] == "1\tdef add(a, b):"
    assert sandbox.read_file("pkg/mathy.py", start_line=2, end_line=2) == "2\t    return a - b"


@pytest.mark.parametrize("bad", ["../outside.txt", "/etc/passwd", ".git/config", "pkg/../../x", ""])
def test_paths_outside_or_in_git_are_rejected(sandbox, bad):
    with pytest.raises(PathEscape):
        sandbox.resolve(bad)


def test_symlink_escape_is_rejected(sandbox, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    (sandbox.root / "link").symlink_to(outside)
    with pytest.raises(PathEscape):
        sandbox.resolve("link")


def test_edit_requires_exactly_one_match(sandbox):
    sandbox.edit_file("pkg/mathy.py", "a - b", "a + b")
    assert "a + b" in sandbox.read_file("pkg/mathy.py")
    with pytest.raises(EditError, match="not found"):
        sandbox.edit_file("pkg/mathy.py", "zzz", "q")
    sandbox.write_file("dup.txt", "x\nx\n")
    with pytest.raises(EditError, match="2 places"):
        sandbox.edit_file("dup.txt", "x", "y")
    with pytest.raises(EditError, match="empty"):
        sandbox.edit_file("dup.txt", "", "y")


def test_write_file_creates_parent_directories(sandbox):
    sandbox.write_file("pkg/sub/new.py", "X = 1\n")
    assert (sandbox.root / "pkg" / "sub" / "new.py").read_text() == "X = 1\n"


def test_git_diff_includes_new_and_changed_files(sandbox):
    sandbox.edit_file("pkg/mathy.py", "a - b", "a + b")
    sandbox.write_file("pkg/new.py", "X = 1\n")
    diff = sandbox.git_diff()
    assert "-    return a - b" in diff and "+    return a + b" in diff
    assert "pkg/new.py" in diff


def test_restore_paths_resets_protected_files(sandbox):
    sandbox.write_file("tests/test_mathy.py", "broken")
    sandbox.restore_paths(["tests/test_mathy.py"])
    assert "def test_add" in sandbox.read_file("tests/test_mathy.py")


def test_scrubbed_env_contains_no_secrets(sandbox, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("NEATLOGS_API_KEY", "nl-secret")
    env = sandbox.scrubbed_env()
    assert "ANTHROPIC_API_KEY" not in env and "NEATLOGS_API_KEY" not in env
    out = subprocess.run(
        [sys.executable, "-c", "import os; print(sorted(k for k in os.environ if 'KEY' in k))"],
        env=env, capture_output=True, text=True,
    )
    assert out.stdout.strip() == "[]"


def test_run_pytest_writes_junit_and_reports_failure(sandbox, tmp_path):
    junit = tmp_path / "j.xml"
    proc = sandbox.run_pytest(["tests"], junit)
    assert junit.exists()
    assert proc.returncode == 1  # test_add fails on the buggy base


def test_run_pytest_times_out(sandbox, tmp_path):
    sandbox.write_file("tests/test_slow.py", "import time\n\n\ndef test_slow():\n    time.sleep(5)\n")
    with pytest.raises(SuiteTimeout):
        sandbox.run_pytest(["tests/test_slow.py"], tmp_path / "j.xml", timeout_s=1)


def test_exclude_keeps_artifacts_out_of_the_diff(sandbox):
    sandbox.exclude([".entire/"])
    sandbox.write_file(".entire/cache", "1")
    assert ".entire" not in sandbox.git_diff()


def test_sandbox_root_is_resolved(repo, tmp_path):
    sb = Sandbox(repo / ".." / "repo", sys.executable, ["."], tmp_path / "h")
    assert sb.root == repo.resolve()
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_sandbox.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.sandbox'`.

- [ ] **Step 4: Implement `sandbox.py`**

```python
"""One worktree per run: confined file tools, git helpers and a scrubbed pytest runner.

The agent never gets a shell. File tools resolve every path inside the worktree and refuse .git.
Subprocess environments are rebuilt from scratch so API keys cannot reach repository code.
Network access is not blocked (vetted tasks need none); evidence docs state this limit.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

DEFAULT_EXCLUDES = ["__pycache__/", "*.pyc"]


class PathEscape(Exception):
    pass


class EditError(Exception):
    pass


class SuiteTimeout(Exception):
    pass


class Sandbox:
    def __init__(
        self,
        root: Path,
        venv_python: Path,
        pythonpath: list[str],
        home: Path,
        test_timeout_s: int = 120,
    ):
        self.root = Path(root).resolve()
        self.venv_python = Path(venv_python)
        self.pythonpath = list(pythonpath)
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.test_timeout_s = test_timeout_s

    # --- paths -----------------------------------------------------------------
    def resolve(self, rel: str) -> Path:
        if not isinstance(rel, str) or not rel.strip():
            raise PathEscape("path must be a non-empty string")
        path = (self.root / rel).resolve()
        try:
            parts = path.relative_to(self.root).parts
        except ValueError:
            raise PathEscape(f"{rel!r} is outside the repository") from None
        if ".git" in parts:
            raise PathEscape("the .git directory is off limits")
        return path

    def relpath(self, rel: str) -> str:
        return self.resolve(rel).relative_to(self.root).as_posix()

    # --- file tools ------------------------------------------------------------
    def read_file(
        self, rel: str, start_line: int | None = None, end_line: int | None = None, max_chars: int = 20_000
    ) -> str:
        lines = self.resolve(rel).read_text(encoding="utf-8", errors="replace").splitlines()
        lo = max(1, start_line or 1)
        hi = min(len(lines), end_line or len(lines))
        numbered = "\n".join(f"{i}\t{lines[i - 1]}" for i in range(lo, hi + 1))
        if len(numbered) > max_chars:
            numbered = numbered[:max_chars] + "\n[truncated: use start_line/end_line]"
        return numbered

    def write_file(self, rel: str, content: str) -> None:
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def edit_file(self, rel: str, old: str, new: str) -> None:
        if old == "":
            raise EditError("old must not be empty")
        path = self.resolve(rel)
        text = path.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0:
            raise EditError("old text not found; read the file again and copy it exactly")
        if count > 1:
            raise EditError(f"old text matches {count} places; include more context so it matches once")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    # --- git -------------------------------------------------------------------
    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True
        )

    def git_diff(self) -> str:
        self._git("add", "-A")
        return self._git("diff", "--cached", "--no-color").stdout

    def restore_paths(self, paths: list[str]) -> None:
        if paths:
            self._git("checkout", "HEAD", "--", *paths)

    def exclude(self, patterns: list[str]) -> None:
        path = Path(self._git("rev-parse", "--git-path", "info/exclude").stdout.strip())
        if not path.is_absolute():
            path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text() if path.exists() else ""
        have = set(existing.splitlines())
        add = [p for p in patterns if p not in have]
        if add:
            sep = "" if not existing or existing.endswith("\n") else "\n"
            path.write_text(existing + sep + "\n".join(add) + "\n")

    # --- running tests -----------------------------------------------------------
    def scrubbed_env(self) -> dict[str, str]:
        return {
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(self.home),
            "LANG": "en_US.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": os.pathsep.join(str(self.root / p) for p in self.pythonpath),
        }

    def run_pytest(
        self, args: list[str], junit_path: Path, timeout_s: int | None = None
    ) -> subprocess.CompletedProcess:
        limit = timeout_s or self.test_timeout_s
        cmd = [
            str(self.venv_python), "-m", "pytest", "-q", "-p", "no:cacheprovider",
            f"--junitxml={junit_path}", *args,
        ]
        try:
            return subprocess.run(
                cmd, cwd=self.root, env=self.scrubbed_env(), capture_output=True, text=True, timeout=limit
            )
        except subprocess.TimeoutExpired as exc:
            raise SuiteTimeout(f"tests exceeded {limit}s") from exc
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_sandbox.py`
Expected: 16 passed (the parametrized path test counts as 5).

- [ ] **Step 6: Commit**

```bash
git add src/margin/sandbox.py tests/conftest.py tests/test_sandbox.py
git commit -m "feat: sandbox with confined file tools and scrubbed pytest"
```

---

### Task 7: Verifier (baseline, flaky exclusion, verdict)

**Files:**
- Create: `src/margin/verify.py`
- Test: `tests/test_verify.py`

**Interfaces:**
- Consumes: `Sandbox`, `SuiteTimeout` (Task 6).
- Produces: `NoJunit(Exception)`; `SuiteRun(passed: frozenset[str], failed: frozenset[str])`; `nodeid_to_junit(nodeid) -> str`; `parse_junit(path) -> SuiteRun`; `run_suite(sandbox, args, junit_path) -> SuiteRun`.
- Produces: `Baseline(failing: frozenset, flaky: frozenset)` with `.to_dict()` / `Baseline.from_dict(d)`; `make_baseline(run1, run2) -> Baseline`.
- Produces: `Verdict(solved: bool, target_failing: list[str], new_failures: list[str], reason: str)`; `judge(baseline, after, target_junit_ids) -> Verdict`; `final_verdict(sandbox, baseline, target_junit_ids, test_args, junit_path) -> Verdict` (never raises for timeouts or missing results).

- [ ] **Step 1: Write the failing tests**

`tests/test_verify.py`:

```python
import pytest

from margin.sandbox import Sandbox
from margin.verify import (
    Baseline, NoJunit, SuiteRun, final_verdict, judge, make_baseline, nodeid_to_junit, parse_junit, run_suite,
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_verify.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.verify'`.

- [ ] **Step 3: Implement `verify.py`**

```python
"""Baseline-aware verification from pytest JUnit output.

A fix counts only if every target test passes and no test that was passing at the base commit
(and is not flaky) now fails. Ids are `classname::name`, as written by pytest's junit writer.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree as ET  # JUnit files are written by third-party test code: no entity expansion

from margin.sandbox import Sandbox, SuiteTimeout


class NoJunit(Exception):
    pass


@dataclass(frozen=True)
class SuiteRun:
    passed: frozenset
    failed: frozenset


@dataclass(frozen=True)
class Baseline:
    failing: frozenset
    flaky: frozenset

    def to_dict(self) -> dict:
        return {"failing": sorted(self.failing), "flaky": sorted(self.flaky)}

    @classmethod
    def from_dict(cls, d: dict) -> "Baseline":
        return cls(frozenset(d["failing"]), frozenset(d["flaky"]))


@dataclass(frozen=True)
class Verdict:
    solved: bool
    target_failing: list
    new_failures: list
    reason: str


def nodeid_to_junit(nodeid: str) -> str:
    parts = nodeid.split("::")
    if len(parts) < 2:
        raise ValueError(f"not a pytest node id (needs '::test_name'): {nodeid!r}")
    path = parts[0][:-3] if parts[0].endswith(".py") else parts[0]
    classname = ".".join([path.replace("/", "."), *parts[1:-1]])
    return f"{classname}::{parts[-1]}"


def parse_junit(path: Path) -> SuiteRun:
    path = Path(path)
    if not path.exists():
        raise NoJunit(f"{path} was not written")
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, ValueError) as exc:  # ValueError covers defusedxml's DefusedXmlException
        raise NoJunit(f"unreadable junit xml: {exc}") from exc
    passed: set[str] = set()
    failed: set[str] = set()
    for case in root.iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        if case.find("failure") is not None or case.find("error") is not None:
            failed.add(test_id)
        elif case.find("skipped") is None:
            passed.add(test_id)
    return SuiteRun(frozenset(passed), frozenset(failed))


def run_suite(sandbox: Sandbox, args: list[str], junit_path: Path) -> SuiteRun:
    junit_path = Path(junit_path)
    junit_path.parent.mkdir(parents=True, exist_ok=True)
    if junit_path.exists():
        junit_path.unlink()
    proc = sandbox.run_pytest(args, junit_path)
    try:
        return parse_junit(junit_path)
    except NoJunit as exc:
        tail = (proc.stdout[-400:] + proc.stderr[-400:]).strip()
        raise NoJunit(f"{exc}; pytest exit {proc.returncode}: {tail}") from exc


def make_baseline(run1: SuiteRun, run2: SuiteRun) -> Baseline:
    return Baseline(
        failing=frozenset(run1.failed & run2.failed), flaky=frozenset(run1.failed ^ run2.failed)
    )


def judge(baseline: Baseline, after: SuiteRun, target_junit_ids: list[str]) -> Verdict:
    target_failing = [t for t in target_junit_ids if t not in after.passed]
    allowed = baseline.failing | baseline.flaky | set(target_junit_ids)
    new_failures = sorted(after.failed - allowed)
    if target_failing:
        reason = "target tests still failing: " + ", ".join(target_failing[:5])
    elif new_failures:
        reason = "new failures vs baseline: " + ", ".join(new_failures[:5])
    else:
        reason = "solved"
    return Verdict(not target_failing and not new_failures, target_failing, new_failures, reason)


def final_verdict(
    sandbox: Sandbox,
    baseline: Baseline,
    target_junit_ids: list[str],
    test_args: list[str],
    junit_path: Path,
) -> Verdict:
    try:
        after = run_suite(sandbox, test_args, junit_path)
    except SuiteTimeout as exc:
        return Verdict(False, list(target_junit_ids), [], f"final test run timed out: {exc}")
    except NoJunit as exc:
        return Verdict(False, list(target_junit_ids), [], f"final test run produced no results: {exc}")
    return judge(baseline, after, target_junit_ids)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_verify.py`
Expected: 14 passed. If `test_end_to_end_on_fixture_repo` fails on the id format, print `parse_junit` output once and adjust `nodeid_to_junit`'s classname rule to match what pytest wrote.

- [ ] **Step 5: Commit**

```bash
git add src/margin/verify.py tests/test_verify.py
git commit -m "feat: baseline-aware verifier"
```

---

### Task 8: Governor (spend rungs)

**Files:**
- Create: `src/margin/governor.py`
- Test: `tests/test_governor.py`

**Interfaces:**
- Produces: `Rung(IntEnum)`: `CONTINUE=1, DOWNGRADE=2, NARROW=3, ABORT=4`.
- Produces: `Decision(rung: Rung, changed: bool, reason: str = "")`.
- Produces: `Governor(cap_usd, downgrade_at=0.6, narrow_at=0.85)` with `.rung`, `.check(spend, est_next, progress_events) -> Decision`, `.restore(rung_name)`. `NullGovernor` has the same surface and always returns `CONTINUE`.

- [ ] **Step 1: Write the failing tests**

`tests/test_governor.py`:

```python
from margin.governor import Governor, NullGovernor, Rung


def test_continue_below_thresholds():
    g = Governor(cap_usd=1.0)
    d = g.check(spend=0.3, est_next=0.05, progress_events=0)
    assert d.rung == Rung.CONTINUE and not d.changed


def test_downgrade_at_sixty_percent_without_progress():
    g = Governor(cap_usd=1.0)
    d = g.check(spend=0.62, est_next=0.05, progress_events=0)
    assert d.rung == Rung.DOWNGRADE and d.changed
    assert "no progress" in d.reason


def test_no_downgrade_while_making_progress():
    g = Governor(cap_usd=1.0)
    assert g.check(0.62, 0.05, progress_events=1).rung == Rung.CONTINUE
    assert g.check(0.62, 0.05, progress_events=1).rung == Rung.DOWNGRADE  # next check: none since


def test_narrow_at_eighty_five_percent():
    g = Governor(cap_usd=1.0)
    g.check(0.62, 0.05, 0)
    d = g.check(0.86, 0.05, 0)
    assert d.rung == Rung.NARROW and d.changed


def test_jump_straight_to_narrow_skips_downgrade():
    g = Governor(cap_usd=1.0)
    d = g.check(0.9, 0.05, 0)
    assert d.rung == Rung.NARROW


def test_abort_when_next_call_would_reach_the_cap():
    g = Governor(cap_usd=1.0)
    d = g.check(0.9, 0.11, 0)
    assert d.rung == Rung.ABORT and d.changed
    assert "cap" in d.reason


def test_rungs_never_decrease():
    g = Governor(cap_usd=1.0)
    g.check(0.9, 0.05, 0)
    d = g.check(0.1, 0.01, progress_events=5)
    assert d.rung == Rung.NARROW and not d.changed


def test_cap_smaller_than_one_call_aborts_immediately():
    g = Governor(cap_usd=0.01)
    assert g.check(0.0, 0.04, 0).rung == Rung.ABORT


def test_restore_sets_the_rung():
    g = Governor(cap_usd=1.0)
    g.restore("DOWNGRADE")
    assert g.rung == Rung.DOWNGRADE
    assert not g.check(0.62, 0.05, 0).changed


def test_null_governor_never_intervenes():
    g = NullGovernor()
    d = g.check(spend=999.0, est_next=999.0, progress_events=0)
    assert d.rung == Rung.CONTINUE and not d.changed
    g.restore("ABORT")
    assert g.rung == Rung.CONTINUE
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_governor.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.governor'`.

- [ ] **Step 3: Implement `governor.py`**

```python
"""Budget governor: a monotonic ladder driven by spend, progress and the next-call estimate."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Rung(IntEnum):
    CONTINUE = 1
    DOWNGRADE = 2
    NARROW = 3
    ABORT = 4


@dataclass(frozen=True)
class Decision:
    rung: Rung
    changed: bool
    reason: str = ""


class NullGovernor:
    """Used by arms A and B: no budget control (the run hard cap still applies in the loop)."""

    rung = Rung.CONTINUE

    def check(self, spend: float, est_next: float, progress_events: int) -> Decision:
        return Decision(Rung.CONTINUE, False)

    def restore(self, rung_name: str) -> None:
        return None


class Governor:
    def __init__(self, cap_usd: float, downgrade_at: float = 0.6, narrow_at: float = 0.85):
        self.cap = cap_usd
        self.downgrade_at = downgrade_at
        self.narrow_at = narrow_at
        self.rung = Rung.CONTINUE
        self._seen_progress = 0

    def restore(self, rung_name: str) -> None:
        self.rung = Rung[rung_name]

    def check(self, spend: float, est_next: float, progress_events: int) -> Decision:
        progressed = progress_events > self._seen_progress
        self._seen_progress = progress_events
        target, reason = self.rung, ""
        if spend + est_next >= self.cap:
            target = Rung.ABORT
            reason = f"spend ${spend:.4f} plus next call ${est_next:.4f} reaches the cap ${self.cap:.4f}"
        elif spend >= self.narrow_at * self.cap:
            target = Rung.NARROW
            reason = f"spend ${spend:.4f} is at {spend / self.cap:.0%} of the cap"
        elif spend >= self.downgrade_at * self.cap and not progressed:
            target = Rung.DOWNGRADE
            reason = f"no progress at {spend / self.cap:.0%} of the cap"
        target = max(self.rung, target)
        changed = target > self.rung
        self.rung = target
        return Decision(self.rung, changed, reason if changed else "")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_governor.py`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/margin/governor.py tests/test_governor.py
git commit -m "feat: governor rung ladder"
```

---

### Task 9: Agent tools and basic code context

**Files:**
- Create: `src/margin/context.py` (basic parts), `src/margin/agent/__init__.py`, `src/margin/agent/tools.py`, `src/margin/faults.py` (hook stubs, completed in Task 17), `tests/fakes.py`
- Test: `tests/test_context.py`, `tests/test_tools.py`

**Interfaces:**
- Consumes: `Sandbox`, `PathEscape`, `EditError`, `SuiteTimeout` (Task 6); `Baseline`, `run_suite`, `NoJunit` (Task 7); `RunState` (Task 5); `trace` (Task 1).
- Produces (`context.py`): `GraphError(Exception)`; `grep_search(root, query, max_hits=40) -> str`; `naive_context(root, max_chars) -> str`.
- Produces (`tools.py`): `ToolOutput(text, is_error=False)`; `ProgressTracker` with `.events: int`, `.note_edit()`, `.note_tests(failing_targets: int)`, `.to_dict()`, `.restore(d)`; `ARM_TOOLS: dict[str, list[str]]`; `tool_schemas(arm) -> list[dict]`; `ToolExecutor(*, sandbox, arm, baseline, target_nodeids, target_junit_ids, test_args, protected_paths, issue_text, graph=None, faults=None, state=None)` with `.execute(name, args) -> ToolOutput`, `.digest() -> {"diff", "tests"}`, `.progress`, `.issue_text`, `.target_nodeids`, `.faults`.
- The `graph` object needs `.search(query: str) -> str` and `.impact(symbol: str) -> str`. The `faults` object needs `.before_tests()` and `.corrupt_run(run) -> SuiteRun` (Task 17).

- [ ] **Step 1: Write `tests/fakes.py`**

```python
"""Test doubles shared across loop, tools and run tests."""
import copy
from types import SimpleNamespace

from margin.agent.tools import ProgressTracker, ToolOutput


class FakeBlock:
    def __init__(self, type_, **kw):
        self.type = type_
        self.__dict__.update(kw)

    def to_dict(self):
        return dict(self.__dict__)


def text(t):
    return FakeBlock("text", text=t)


def tool_use(id_, name, input_):
    return FakeBlock("tool_use", id=id_, name=name, input=input_)


def reply(blocks, stop="end_turn", input_tokens=100, output_tokens=50):
    usage = SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )
    return SimpleNamespace(content=blocks, stop_reason=stop, usage=usage)


class ScriptedClient:
    """Replays canned replies; an Exception instance in the script is raised instead."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **params):
        self.calls.append(copy.deepcopy(params))
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeExecutor:
    def __init__(self, outputs=None):
        self.progress = ProgressTracker()
        self.faults = None
        self.issue_text = "the issue"
        self.target_nodeids = ["tests/test_x.py::test_y"]
        self.calls = []
        self.outputs = outputs or {}

    def execute(self, name, args):
        self.calls.append((name, args))
        return ToolOutput(self.outputs.get(name, "ok"))

    def digest(self):
        return {"diff": "DIFF", "tests": "TESTS"}


class FakeGraph:
    def search(self, query):
        return f"GRAPH-SEARCH:{query}"

    def impact(self, symbol):
        return f"GRAPH-IMPACT:{symbol}"
```

- [ ] **Step 2: Write the failing tests**

`tests/test_context.py`:

```python
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
```

`tests/test_tools.py`:

```python
import pytest
from fakes import FakeGraph

from margin.agent.tools import ARM_TOOLS, ToolExecutor, tool_schemas
from margin.verify import make_baseline, run_suite

TARGET_NODEID = "tests/test_mathy.py::test_add"
TARGET_JUNIT = "tests.test_mathy::test_add"


def make_executor(sandbox, tmp_path, arm="B", graph=None, **extra):
    base = make_baseline(
        run_suite(sandbox, ["tests"], tmp_path / "b1.xml"), run_suite(sandbox, ["tests"], tmp_path / "b2.xml")
    )
    return ToolExecutor(
        sandbox=sandbox, arm=arm, baseline=base, target_nodeids=[TARGET_NODEID],
        target_junit_ids=[TARGET_JUNIT], test_args=["tests"], protected_paths=["tests/test_mathy.py"],
        issue_text="add subtracts", graph=graph, **extra,
    )


def test_tool_schemas_per_arm():
    assert [t["name"] for t in tool_schemas("A")] == ARM_TOOLS["A"]
    assert "graph_impact" in ARM_TOOLS["B"] and "graph_impact" in ARM_TOOLS["C"]
    assert "graph_impact" not in ARM_TOOLS["A"]
    for tool in tool_schemas("B"):
        assert tool["input_schema"]["additionalProperties"] is False


def test_read_edit_and_run_tests_flow(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path)
    assert "return a - b" in ex.execute("read_file", {"path": "pkg/mathy.py"}).text
    first = ex.execute("run_tests", {})
    assert "Target tests: 1 failing of 1" in first.text
    assert not first.is_error
    assert ex.execute("edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"}).text == "edited pkg/mathy.py"
    second = ex.execute("run_tests", {})
    assert "Target tests: 0 failing of 1" in second.text
    assert "New failures vs baseline: none" in second.text
    assert ex.progress.events >= 2  # first edit + target failures dropped


def test_arm_a_runs_only_the_target_tests(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path, arm="A")
    out = ex.execute("run_tests", {})
    assert "Target tests" in out.text and "New failures" not in out.text


def test_protected_test_files_cannot_be_edited(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path)
    out = ex.execute("edit_file", {"path": "tests/test_mathy.py", "old": "assert", "new": "pass"})
    assert out.is_error and "protected" in out.text
    out = ex.execute("write_file", {"path": "./tests/test_mathy.py", "content": ""})
    assert out.is_error and "protected" in out.text


@pytest.mark.parametrize("path", ["../x.py", "/etc/passwd", ".git/config"])
def test_paths_outside_the_worktree_are_errors_not_crashes(sandbox, tmp_path, path):
    out = make_executor(sandbox, tmp_path).execute("read_file", {"path": path})
    assert out.is_error


def test_bad_tool_calls_become_error_results(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path)
    assert ex.execute("nope", {}).is_error
    assert ex.execute("read_file", {}).is_error                      # missing argument
    assert ex.execute("read_file", {"path": "x", "bogus": 1}).is_error  # unexpected argument
    assert ex.execute("read_file", {"path": "pkg/mathy.py", "start_line": "a"}).is_error  # wrong type
    assert ex.execute("read_file", "not-a-dict").is_error
    assert ex.execute("edit_file", {"path": "pkg/mathy.py", "old": "zzz", "new": "q"}).is_error


def test_search_uses_the_graph_only_when_one_is_attached(sandbox, tmp_path):
    assert "pkg/mathy.py" in make_executor(sandbox, tmp_path, arm="A").execute("search_code", {"query": "add"}).text
    ex = make_executor(sandbox, tmp_path, arm="B", graph=FakeGraph())
    assert ex.execute("search_code", {"query": "add"}).text == "GRAPH-SEARCH:add"
    assert ex.execute("graph_impact", {"symbol": "add"}).text == "GRAPH-IMPACT:add"
    assert make_executor(sandbox, tmp_path, arm="A").execute("graph_impact", {"symbol": "add"}).is_error


def test_git_diff_and_digest(sandbox, tmp_path):
    ex = make_executor(sandbox, tmp_path)
    assert ex.execute("git_diff", {}).text == "(no changes)"
    ex.execute("edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})
    ex.execute("run_tests", {})
    digest = ex.digest()
    assert "+    return a + b" in digest["diff"]
    assert "Target tests: 0 failing" in digest["tests"]


def test_long_output_is_clipped(sandbox, tmp_path):
    sandbox.write_file("big.txt", "x" * 50_000)
    out = make_executor(sandbox, tmp_path).execute("read_file", {"path": "big.txt"})
    assert len(out.text) < 13_000
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_context.py tests/test_tools.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.context'`.

- [ ] **Step 4: Implement `context.py` (basic parts)**

```python
"""Code context for the agent: plain search and whole-file stuffing (arm A).

The entire-graph adapter (arms B and C) is added to this module in Task 14.
"""
from __future__ import annotations

from pathlib import Path

SKIP_DIRS = {"tests", "test", "docs", "build", "dist", "venv", "node_modules"}


class GraphError(RuntimeError):
    pass


def _is_source(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    for part in rel.parts[:-1]:
        if part.startswith(".") or part in SKIP_DIRS or part.endswith(".egg-info"):
            return False
    name = rel.name
    return not (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py")


def grep_search(root: Path, query: str, max_hits: int = 40) -> str:
    if not query.strip():
        raise ValueError("query must not be empty")
    needle = query.lower()
    hits: list[str] = []
    for path in sorted(Path(root).rglob("*.py")):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if needle in line.lower():
                hits.append(f"{rel.as_posix()}:{number}: {line.strip()[:160]}")
                if len(hits) >= max_hits:
                    return "\n".join(hits)
    return "\n".join(hits) or "no matches"


def naive_context(root: Path, max_chars: int) -> str:
    """Arm A: stuff whole source files into the prompt, smallest first, up to a character budget."""
    root = Path(root)
    files = [p for p in root.rglob("*.py") if _is_source(p, root)]
    files.sort(key=lambda p: (p.stat().st_size, str(p)))
    chosen: list[tuple[str, str]] = []
    used = 0
    for path in files:
        rel = path.relative_to(root).as_posix()
        body = path.read_text(encoding="utf-8", errors="replace")
        block = f"### {rel}\n```python\n{body}\n```\n"
        if used + len(block) <= max_chars:
            chosen.append((rel, block))
            used += len(block)
    return "\n".join(block for _, block in sorted(chosen))
```

- [ ] **Step 5: Implement `agent/tools.py` and the fault-hook stub**

`src/margin/agent/__init__.py`: empty file.

`src/margin/faults.py` (stub; Task 17 replaces the body):

```python
"""Fault injection. Task 17 implements the injector; the tool executor only needs these hook names."""
from __future__ import annotations

from margin.verify import SuiteRun


class FaultInjector:
    def __init__(self, kind: str | None = None):
        self.kind = kind

    def before_model_call(self) -> None:
        return None

    def before_tests(self) -> None:
        return None

    def corrupt_run(self, run: SuiteRun, protect: frozenset | set = frozenset()) -> SuiteRun:
        return run
```

`src/margin/agent/tools.py`:

```python
"""The agent's tools. Arms A, B and C share one executor; only the backends differ."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from margin.context import GraphError, grep_search
from margin.sandbox import EditError, PathEscape, Sandbox, SuiteTimeout
from margin.telemetry import trace
from margin.verify import Baseline, NoJunit, SuiteRun, run_suite

MAX_OUTPUT_CHARS = 12_000


@dataclass(frozen=True)
class ToolOutput:
    text: str
    is_error: bool = False


class ProgressTracker:
    """Counts progress events the governor can see: a first applied edit, or fewer failing targets."""

    def __init__(self) -> None:
        self.events = 0
        self.best_failing: int | None = None
        self.patch_applied = False

    def note_edit(self) -> None:
        if not self.patch_applied:
            self.patch_applied = True
            self.events += 1

    def note_tests(self, failing_targets: int) -> None:
        if self.best_failing is None:
            self.best_failing = failing_targets  # the first measurement is a baseline, not progress
        elif failing_targets < self.best_failing:
            self.best_failing = failing_targets
            self.events += 1

    def to_dict(self) -> dict:
        return {"events": self.events, "best_failing": self.best_failing, "patch_applied": self.patch_applied}

    def restore(self, d: dict) -> None:
        self.events = d.get("events", 0)
        self.best_failing = d.get("best_failing")
        self.patch_applied = d.get("patch_applied", False)


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object", "properties": properties, "required": required, "additionalProperties": False,
        },
    }


_STR = {"type": "string"}
SCHEMAS = {
    "read_file": _schema(
        "read_file",
        "Read a UTF-8 text file in the repository with numbered lines; optional 1-based inclusive range.",
        {"path": _STR, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
        ["path"],
    ),
    "search_code": _schema(
        "search_code", "Find code relevant to a plain-language query or an identifier.", {"query": _STR}, ["query"]
    ),
    "graph_impact": _schema(
        "graph_impact",
        "Show callers, callees and co-changing files for a symbol before changing it.",
        {"symbol": _STR},
        ["symbol"],
    ),
    "edit_file": _schema(
        "edit_file",
        "Replace exactly one occurrence of `old` with `new` in a file. `old` must match exactly once.",
        {"path": _STR, "old": _STR, "new": _STR},
        ["path", "old", "new"],
    ),
    "write_file": _schema(
        "write_file", "Create or overwrite a file with the given content.", {"path": _STR, "content": _STR}, ["path", "content"]
    ),
    "run_tests": _schema("run_tests", "Run the tests and report the results.", {}, []),
    "git_diff": _schema("git_diff", "Show the current patch against the starting commit.", {}, []),
}
_BASE = ["read_file", "search_code", "edit_file", "write_file", "run_tests", "git_diff"]
ARM_TOOLS = {"A": list(_BASE), "B": [*_BASE, "graph_impact"], "C": [*_BASE, "graph_impact"]}


def tool_schemas(arm: str) -> list[dict]:
    return [SCHEMAS[name] for name in ARM_TOOLS[arm]]


def _clip(out: ToolOutput) -> ToolOutput:
    if len(out.text) <= MAX_OUTPUT_CHARS:
        return out
    return ToolOutput(out.text[:MAX_OUTPUT_CHARS] + "\n[output truncated]", out.is_error)


class ToolExecutor:
    def __init__(
        self,
        *,
        sandbox: Sandbox,
        arm: str,
        baseline: Baseline,
        target_nodeids: list[str],
        target_junit_ids: list[str],
        test_args: list[str],
        protected_paths: list[str],
        issue_text: str,
        graph: Any = None,
        faults: Any = None,
        state: Any = None,
    ):
        self.sandbox = sandbox
        self.arm = arm
        self.baseline = baseline
        self.target_nodeids = list(target_nodeids)
        self.target_junit_ids = list(target_junit_ids)
        self.test_args = list(test_args)
        self.protected = {sandbox.relpath(p) for p in protected_paths}
        self.issue_text = issue_text
        self.graph = graph
        self.faults = faults
        self.state = state
        self.progress = ProgressTracker()
        self.last_tests_text = ""
        self._test_runs = 0

    # --- dispatch ----------------------------------------------------------------
    def execute(self, name: str, args: Any) -> ToolOutput:
        if self.state is not None:
            self.state.log("tool_call", name=name)
        with trace(name, kind="TOOL", **{"margin.tool": name}):
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None or name not in ARM_TOOLS[self.arm]:
                return ToolOutput(f"error: unknown tool {name!r}", True)
            if not isinstance(args, dict):
                return ToolOutput("error: tool input must be a JSON object", True)
            try:
                return _clip(handler(**args))
            except (
                PathEscape, EditError, GraphError, SuiteTimeout, NoJunit,
                KeyError, TypeError, ValueError, OSError,
            ) as exc:
                return ToolOutput(f"error: {type(exc).__name__}: {exc}", True)

    def digest(self) -> dict:
        return {"diff": self.sandbox.git_diff()[:20_000], "tests": self.last_tests_text or "(tests not run yet)"}

    def _recovery(self, kind: str, detail: str) -> None:
        if self.state is not None:
            self.state.log("recovery", kind=kind, detail=detail)

    def _guard_write(self, path: str) -> None:
        if self.sandbox.relpath(path) in self.protected:
            raise PathEscape(f"{path} is a protected test file; fix the code, not the test")

    # --- tools -------------------------------------------------------------------
    def _tool_read_file(self, path, start_line=None, end_line=None) -> ToolOutput:
        return ToolOutput(self.sandbox.read_file(path, start_line, end_line))

    def _tool_search_code(self, query) -> ToolOutput:
        if self.graph is not None:
            return ToolOutput(self.graph.search(query))
        return ToolOutput(grep_search(self.sandbox.root, query))

    def _tool_graph_impact(self, symbol) -> ToolOutput:
        if self.graph is None:
            return ToolOutput("error: the code graph is not available for this run", True)
        return ToolOutput(self.graph.impact(symbol))

    def _tool_edit_file(self, path, old, new) -> ToolOutput:
        self._guard_write(path)
        self.sandbox.edit_file(path, old, new)
        self.progress.note_edit()
        return ToolOutput(f"edited {path}")

    def _tool_write_file(self, path, content) -> ToolOutput:
        self._guard_write(path)
        self.sandbox.write_file(path, content)
        self.progress.note_edit()
        return ToolOutput(f"wrote {path}")

    def _tool_git_diff(self) -> ToolOutput:
        return ToolOutput(self.sandbox.git_diff() or "(no changes)")

    def _new_failures(self, run: SuiteRun) -> list[str]:
        allowed = self.baseline.failing | self.baseline.flaky | set(self.target_junit_ids)
        return sorted(run.failed - allowed)

    def _tool_run_tests(self) -> ToolOutput:
        full = self.arm in ("B", "C")
        args = list(self.test_args) if full else list(self.target_nodeids)
        junit = self.sandbox.home / f"junit-{self._test_runs}.xml"
        self._test_runs += 1
        try:
            if self.faults is not None:
                self.faults.before_tests()
            run = run_suite(self.sandbox, args, junit)
        except SuiteTimeout:
            self._recovery("tool_timeout", "tests timed out; retrying with the target tests only")
            run = run_suite(self.sandbox, list(self.target_nodeids), junit)
        if self.faults is not None:
            run = self.faults.corrupt_run(run, protect=set(self.target_junit_ids))
        failing_targets = [t for t in self.target_junit_ids if t not in run.passed]
        new = self._new_failures(run) if full else []
        if new:  # suspicious: re-run once and keep only failures that persist
            again = run_suite(self.sandbox, args, junit)
            persistent = [n for n in new if n in again.failed]
            if len(persistent) != len(new):
                self._recovery("flaky_rerun", f"{len(new) - len(persistent)} spurious failure(s) cleared on re-run")
            new = persistent
        self.progress.note_tests(len(failing_targets))
        lines = [f"Target tests: {len(failing_targets)} failing of {len(self.target_junit_ids)}"]
        lines += [f"  FAIL {t}" for t in failing_targets]
        if full:
            lines.append("New failures vs baseline: " + ("none" if not new else ""))
            lines += [f"  FAIL {t}" for t in new[:20]]
            lines.append(
                f"Full suite: {len(run.passed)} passed, {len(run.failed)} failed "
                f"({len(self.baseline.failing)} already failing at the base commit)"
            )
        self.last_tests_text = "\n".join(lines)
        return ToolOutput(self.last_tests_text)
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_context.py tests/test_tools.py`
Expected: 15 passed.

- [ ] **Step 7: Commit**

```bash
git add src/margin/context.py src/margin/faults.py src/margin/agent tests/fakes.py tests/test_context.py tests/test_tools.py
git commit -m "feat: agent tools, plain search and naive context"
```

---

### Task 10: Prompts, model client and agent loop (M1 core)

**Files:**
- Create: `src/margin/agent/prompts.py`, `src/margin/model.py`, `src/margin/agent/loop.py`
- Test: `tests/test_model.py`, `tests/test_loop.py`

**Interfaces:**
- Consumes: `Settings` (Task 1); `PriceTable`, `SpendMeter`, `Usage` (Task 3); `RunState`, `errors` (Task 5); `Rung`, `Governor`, `NullGovernor` (Task 8); `ToolExecutor`, `tool_schemas` (Task 9).
- Produces (`prompts.py`): `SYSTEM_PROMPT: str`; `first_prompt(issue, context, target_nodeids) -> str`; `digest_prompt(issue, diff, tests, target_nodeids) -> str`; `narrow_notice(turns) -> str`.
- Produces (`model.py`): `build_request(*, model, effort, system, tools, messages, max_tokens) -> dict`; `AnthropicModel(client).create(**params)`; `make_model_client(settings) -> AnthropicModel`; `is_transient(exc) -> bool`.
- Produces (`loop.py`): `AgentResult(stop, turns, abort_reason=None, final_text="", rung_events=[], messages=[])`; `call_with_retry(client, params, *, state, faults, sleep, retries=4)`; `run_agent(*, first_prompt, arm, client, meter, governor, executor, state, prices, settings, faults=None, resume=None, sleep=time.sleep, after_turn_hook=None) -> AgentResult`.
- `AgentResult.stop` is one of `end_turn, abort, narrow_exhausted, max_turns, refusal, error`.

- [ ] **Step 1: Write the failing tests**

`tests/test_model.py`:

```python
from margin.errors import TransientModelError
from margin.model import build_request, is_transient


def test_request_shape_avoids_parameters_the_models_reject():
    params = build_request(
        model="claude-sonnet-5-5", effort="medium", system="SYS", tools=[{"name": "t"}],
        messages=[{"role": "user", "content": "hi"}], max_tokens=16000,
    )
    for forbidden in ("temperature", "top_p", "top_k", "thinking", "tool_choice"):
        assert forbidden not in params
    assert params["output_config"] == {"effort": "medium"}
    assert params["cache_control"] == {"type": "ephemeral"}
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["system"][0]["text"] == "SYS"


def test_transient_classification():
    assert is_transient(TransientModelError("overloaded"))
    assert not is_transient(ValueError("bad"))
```

`tests/test_loop.py`:

```python
import pytest
from fakes import FakeExecutor, ScriptedClient, reply, text, tool_use

from margin.config import ROOT, Settings
from margin.errors import SimulatedCrash, TransientModelError
from margin.governor import Governor, NullGovernor
from margin.pricing import PriceTable, SpendMeter
from margin.agent.loop import run_agent
from margin.state import RunState

PRICES = PriceTable.load(ROOT / "pricing.toml")


def go(tmp_path, replies, *, governor=None, settings=None, arm="A", resume=None, hook=None, meter=None, state=None, client=None):
    client = client or ScriptedClient(replies)
    meter = meter or SpendMeter(PRICES)
    state = state or RunState(tmp_path / "run")
    sleeps = []
    result = run_agent(
        first_prompt="FIRST", arm=arm, client=client, meter=meter, governor=governor or NullGovernor(),
        executor=FakeExecutor(), state=state, prices=PRICES, settings=settings or Settings(),
        resume=resume, sleep=sleeps.append, after_turn_hook=hook,
    )
    return result, client, meter, state, sleeps


def test_tool_turn_then_finish(tmp_path):
    replies = [
        reply([text("looking"), tool_use("t1", "read_file", {"path": "a.py"})], stop="tool_use"),
        reply([text("done")]),
    ]
    result, client, meter, state, _ = go(tmp_path, replies)
    assert result.stop == "end_turn" and result.turns == 2
    assert result.final_text == "done"
    second = client.calls[1]["messages"]
    assert second[-1]["content"] == [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]
    assert second[-2]["content"][1] == {"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "a.py"}}
    assert meter.total_usd > 0
    assert len(state.events("model_usage")) == 2


def test_request_parameters_follow_the_model_rules(tmp_path):
    _, client, *_ = go(tmp_path, [reply([text("x")])])
    params = client.calls[0]
    assert params["model"] == "claude-sonnet-5-5"
    assert params["output_config"] == {"effort": "medium"}
    assert "temperature" not in params and "thinking" not in params
    assert [t["name"] for t in params["tools"]][:2] == ["read_file", "search_code"]
    assert params["messages"] == [{"role": "user", "content": "FIRST"}]


def test_tool_errors_are_marked_on_the_result(tmp_path):
    ex = FakeExecutor()
    ex.execute = lambda name, args: __import__("margin.agent.tools", fromlist=["ToolOutput"]).ToolOutput("boom", True)
    client = ScriptedClient([reply([tool_use("t1", "read_file", {})], stop="tool_use"), reply([text("ok")])])
    run_agent(
        first_prompt="F", arm="A", client=client, meter=SpendMeter(PRICES), governor=NullGovernor(), executor=ex,
        state=RunState(tmp_path / "r"), prices=PRICES, settings=Settings(), sleep=lambda s: None,
    )
    assert client.calls[1]["messages"][-1]["content"][0]["is_error"] is True


def test_abort_before_the_first_call_when_the_cap_is_tiny(tmp_path):
    result, client, *_ = go(tmp_path, [], governor=Governor(cap_usd=0.0001))
    assert result.stop == "abort" and client.calls == []
    assert "cap" in result.abort_reason


def test_downgrade_restarts_on_haiku_from_a_digest(tmp_path):
    replies = [
        reply([tool_use("t1", "read_file", {"path": "a"})], stop="tool_use", input_tokens=100_000, output_tokens=45_000),
        reply([text("done")]),
    ]
    result, client, *_ = go(tmp_path, replies, governor=Governor(cap_usd=1.0))
    assert result.stop == "end_turn"
    assert client.calls[0]["model"] == "claude-sonnet-5-5"
    second = client.calls[1]
    assert second["model"] == "claude-haiku-5-5"
    assert second["output_config"] == {"effort": "low"}
    assert len(second["messages"]) == 1 and "DIFF" in second["messages"][0]["content"]
    assert [e["rung"] for e in result.rung_events] == ["DOWNGRADE"]


def test_narrow_adds_a_notice_then_caps_the_turns(tmp_path):
    cheap = dict(input_tokens=100, output_tokens=10)
    replies = [
        reply([tool_use("t1", "read_file", {"path": "a"})], stop="tool_use", input_tokens=100_000, output_tokens=70_000),
        reply([tool_use("t2", "read_file", {"path": "a"})], stop="tool_use", **cheap),
    ]
    settings = Settings(narrow_turns=1)
    result, client, *_ = go(tmp_path, replies, governor=Governor(cap_usd=1.0), settings=settings)
    assert result.stop == "narrow_exhausted"
    last_block = client.calls[1]["messages"][-1]["content"][-1]
    assert last_block["type"] == "text" and "Budget notice" in last_block["text"]
    assert [e["rung"] for e in result.rung_events] == ["NARROW"]


def test_transient_errors_are_retried_with_backoff(tmp_path):
    replies = [TransientModelError("529"), TransientModelError("529"), reply([text("ok")])]
    result, client, _, state, sleeps = go(tmp_path, replies)
    assert result.stop == "end_turn"
    assert len(state.events("retry")) == 2
    assert sleeps == [1, 2]


def test_non_transient_error_ends_the_run_with_an_error_result(tmp_path):
    result, *_ = go(tmp_path, [ValueError("boom")])
    assert result.stop == "error" and "boom" in result.abort_reason


def test_refusal_stops_the_run(tmp_path):
    result, *_ = go(tmp_path, [reply([text("no")], stop="refusal")])
    assert result.stop == "refusal"


def test_max_tokens_gets_a_continue_nudge(tmp_path):
    replies = [reply([text("cut")], stop="max_tokens"), reply([text("done")])]
    result, client, *_ = go(tmp_path, replies)
    assert result.stop == "end_turn"
    assert "cut off" in client.calls[1]["messages"][-1]["content"]


def test_max_turns_is_enforced(tmp_path):
    replies = [reply([tool_use(f"t{i}", "read_file", {"path": "a"})], stop="tool_use") for i in range(5)]
    result, *_ = go(tmp_path, replies, settings=Settings(max_turns=3))
    assert result.stop == "max_turns" and result.turns == 3


def test_hard_cap_aborts_ungoverned_runs(tmp_path):
    replies = [reply([tool_use("t1", "read_file", {"path": "a"})], stop="tool_use", input_tokens=2_000_000)] * 3
    result, *_ = go(tmp_path, replies, settings=Settings(run_hard_cap_usd=1.0))
    assert result.stop == "abort" and result.abort_reason == "hard cap"


def test_resume_after_a_crash_matches_an_uninterrupted_run(tmp_path):
    def script():
        return [
            reply([tool_use("t1", "read_file", {"path": "a"})], stop="tool_use"),
            reply([tool_use("t2", "read_file", {"path": "b"})], stop="tool_use"),
            reply([text("done")]),
        ]

    full, _, full_meter, *_ = go(tmp_path / "full", script())

    def crash(turn):
        if turn == 1:
            raise SimulatedCrash()

    state = RunState(tmp_path / "crashy" / "run")
    with pytest.raises(SimulatedCrash):
        go(tmp_path, script(), state=state, hook=crash)
    checkpoint = state.load_checkpoint()
    assert checkpoint["turn"] == 1
    meter = SpendMeter(PRICES)
    state.restore_meter(meter)
    resumed, *_ = go(tmp_path, script()[1:], resume=checkpoint, meter=meter, state=state)
    assert resumed.messages == full.messages
    assert meter.total_usd == pytest.approx(full_meter.total_usd)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_model.py tests/test_loop.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.model'`.

- [ ] **Step 3: Implement `agent/prompts.py`**

```python
"""Prompt text. Kept short and stable: the system prompt is the cached prefix."""
from __future__ import annotations

SYSTEM_PROMPT = """You are a careful software engineer fixing one issue in a Python repository.

Rules:
- The working directory is the repository. Use the provided tools; you have no shell.
- The target tests are already failing and must pass. Never edit them; edits to test files are rejected.
- Make the smallest correct change. Do not refactor, reformat or touch unrelated code.
- Call run_tests after each edit and fix what it reports before doing anything else.
- When the target tests pass and there are no new failures, reply with one sentence describing the fix and stop.
- If a tool returns an error, read it and adjust. Do not repeat the same call unchanged."""


def first_prompt(issue: str, context: str, target_nodeids: list[str]) -> str:
    targets = "\n".join(f"- {t}" for t in target_nodeids)
    return (
        "Fix this issue in the repository checked out in the working directory.\n\n"
        f"## Issue\n{issue}\n\n"
        f"## Target tests (currently failing; they must pass)\n{targets}\n\n"
        f"## Repository context\n{context}\n\n"
        "Make the smallest change that makes the target tests pass without breaking other tests. "
        "Use run_tests to check your work."
    )


def digest_prompt(issue: str, diff: str, tests: str, target_nodeids: list[str]) -> str:
    targets = "\n".join(f"- {t}" for t in target_nodeids)
    return (
        "You are continuing a fix that is already in progress. The budget is tight: make the smallest "
        "change that finishes the job.\n\n"
        f"## Issue\n{issue}\n\n"
        f"## Target tests\n{targets}\n\n"
        f"## Current patch (git diff)\n{diff or '(no changes yet)'}\n\n"
        f"## Latest test result\n{tests}\n\n"
        "Continue from here. Use run_tests to verify, then reply with one sentence and stop."
    )


def narrow_notice(turns: int) -> str:
    return (
        "Budget notice: spend is close to the cap. Stop exploring. Make one minimal patch now and "
        f"verify it. You have at most {turns} turns left."
    )
```

- [ ] **Step 4: Implement `model.py`**

```python
"""Request construction and the thin Anthropic wrapper.

`anthropic` is imported lazily so neatlogs.init (which must run first) can attach its instrumentation.
Requests avoid everything Sonnet 5.5 and Haiku 5.5 reject: sampling parameters, disabled thinking,
forced tool choice and prefill. Thinking is left at its adaptive default.
"""
from __future__ import annotations

from typing import Any

from margin.config import Settings
from margin.errors import TransientModelError


def build_request(
    *, model: str, effort: str, system: str, tools: list[dict], messages: list[dict], max_tokens: int
) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "tools": tools,
        "messages": messages,
        "cache_control": {"type": "ephemeral"},
        "output_config": {"effort": effort},
    }


class AnthropicModel:
    def __init__(self, client: Any):
        self._client = client

    def create(self, **params: Any) -> Any:
        return self._client.messages.create(**params)


def make_model_client(settings: Settings) -> AnthropicModel:
    import anthropic

    return AnthropicModel(anthropic.Anthropic(max_retries=0))  # our loop owns retries so each is visible


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, TransientModelError):
        return True
    import anthropic

    if isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError)):
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500
```

- [ ] **Step 5: Implement `agent/loop.py`**

```python
"""The agent loop: one model call per turn, tools run locally, spend governed before each call."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from margin.agent.prompts import SYSTEM_PROMPT, digest_prompt, narrow_notice
from margin.agent.tools import tool_schemas
from margin.config import Settings
from margin.governor import Rung
from margin.model import build_request, is_transient
from margin.pricing import PriceTable, SpendMeter, Usage
from margin.state import RunState
from margin.telemetry import trace


@dataclass
class AgentResult:
    stop: str  # end_turn | abort | narrow_exhausted | max_turns | refusal | error
    turns: int
    abort_reason: str | None = None
    final_text: str = ""
    rung_events: list = field(default_factory=list)
    messages: list = field(default_factory=list)


def call_with_retry(client: Any, params: dict, *, state: RunState, faults: Any, sleep: Callable, retries: int = 4):
    for attempt in range(retries + 1):
        try:
            if faults is not None:
                faults.before_model_call()
            return client.create(**params)
        except Exception as exc:  # noqa: BLE001 - classified below
            if attempt == retries or not is_transient(exc):
                raise
            delay = min(2**attempt, 8)
            state.log("retry", attempt=attempt + 1, error=type(exc).__name__, delay=delay)
            sleep(delay)


def _append_notice(messages: list, text: str) -> None:
    last = messages[-1]
    if last["role"] != "user":
        messages.append({"role": "user", "content": text})
    elif isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}, {"type": "text", "text": text}]
    else:
        last["content"].append({"type": "text", "text": text})


def run_agent(
    *,
    first_prompt: str,
    arm: str,
    client: Any,
    meter: SpendMeter,
    governor: Any,
    executor: Any,
    state: RunState,
    prices: PriceTable,
    settings: Settings,
    faults: Any = None,
    resume: dict | None = None,
    sleep: Callable = time.sleep,
    after_turn_hook: Callable[[int], None] | None = None,
) -> AgentResult:
    model, effort = settings.main_model, settings.main_effort
    rung_events: list[dict] = []
    narrow_until: int | None = None
    if resume:
        messages, turn = resume["messages"], resume["turn"]
        model, effort = resume["model"], resume["effort"]
        governor.restore(resume["rung"])
        rung_events = list(resume["extra"].get("rung_events", []))
        narrow_until = resume["extra"].get("narrow_until")
        executor.progress.restore(resume["extra"].get("progress", {}))
    else:
        messages, turn = [{"role": "user", "content": first_prompt}], 0
    last_prompt_tokens = max(1, len(str(messages)) // 3)
    tools = tool_schemas(arm)

    def result(stop: str, reason: str | None = None, final_text: str = "") -> AgentResult:
        return AgentResult(stop, turn, reason, final_text, rung_events, messages)

    while turn < settings.max_turns:
        est = prices.estimate_next_call(model, last_prompt_tokens, settings.expected_output_tokens)
        decision = governor.check(meter.total_usd, est, executor.progress.events)
        if decision.changed:
            event = {
                "turn": turn, "rung": decision.rung.name, "reason": decision.reason,
                "spend": round(meter.total_usd, 6),
            }
            rung_events.append(event)
            state.log("rung", **event)
            with trace(
                "governor", kind="GUARDRAIL",
                **{"margin.rung": decision.rung.name, "margin.spend_usd": meter.total_usd, "margin.reason": decision.reason},
            ):
                pass
        if decision.rung == Rung.ABORT:
            return result("abort", decision.reason)
        if decision.changed and decision.rung == Rung.DOWNGRADE:
            model, effort = settings.fallback_model, settings.fallback_effort
            digest = executor.digest()
            messages = [
                {
                    "role": "user",
                    "content": digest_prompt(
                        executor.issue_text, digest["diff"], digest["tests"], executor.target_nodeids
                    ),
                }
            ]
            last_prompt_tokens = max(1, len(messages[0]["content"]) // 3)
        if decision.changed and decision.rung == Rung.NARROW:
            narrow_until = turn + settings.narrow_turns
            _append_notice(messages, narrow_notice(settings.narrow_turns))
        if narrow_until is not None and turn >= narrow_until:
            return result("narrow_exhausted", "narrowed budget used up")
        if meter.total_usd >= settings.run_hard_cap_usd:
            return result("abort", "hard cap")

        params = build_request(
            model=model, effort=effort, system=SYSTEM_PROMPT, tools=tools, messages=messages,
            max_tokens=settings.max_tokens,
        )
        try:
            with trace(f"turn-{turn}", kind="AGENT", **{"margin.turn": turn, "margin.model": model}):
                response = call_with_retry(client, params, state=state, faults=faults, sleep=sleep)
        except Exception as exc:  # noqa: BLE001 - a failed call ends the run, it must not crash the batch
            message = f"{type(exc).__name__}: {exc}"
            state.log("error", error=message)
            return result("error", message)

        usage = Usage.from_api(response.usage)
        cost = meter.record(model, usage)
        state.log("model_usage", model=model, usage=usage.to_dict(), cost=round(cost, 6), stop=response.stop_reason)
        last_prompt_tokens = max(1, usage.prompt_tokens)
        messages.append({"role": "assistant", "content": [b.to_dict() for b in response.content]})
        turn += 1

        if response.stop_reason == "refusal":
            return result("refusal", "model refusal")
        if response.stop_reason == "end_turn":
            final = "".join(b.text for b in response.content if b.type == "text")
            return result("end_turn", None, final)
        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                out = executor.execute(block.name, block.input)
                item = {"type": "tool_result", "tool_use_id": block.id, "content": out.text}
                if out.is_error:
                    item["is_error"] = True
                results.append(item)
            messages.append({"role": "user", "content": results})
        else:  # max_tokens or anything unexpected: ask the model to carry on
            messages.append(
                {
                    "role": "user",
                    "content": "Your last reply was cut off. Continue with tool calls, or finish with one sentence.",
                }
            )

        state.save_checkpoint(
            turn=turn, messages=messages, model=model, effort=effort, rung=governor.rung.name,
            extra={
                "rung_events": rung_events, "narrow_until": narrow_until,
                "progress": executor.progress.to_dict(),
            },
        )
        if after_turn_hook is not None:
            after_turn_hook(turn)

    return result("max_turns", "turn limit reached")
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_model.py tests/test_loop.py`
Expected: 15 passed. If `test_tool_errors_are_marked_on_the_result` is awkward to read, it is fine to replace the `__import__` line with `from margin.agent.tools import ToolOutput` at the top of the file; behaviour is identical.

- [ ] **Step 7: Run the whole suite and lint, then commit**

```bash
uv run pytest && uv run ruff check src tests
git add src/margin/agent/prompts.py src/margin/model.py src/margin/agent/loop.py tests/test_model.py tests/test_loop.py
git commit -m "feat: model request builder and agent loop with governor hooks"
```

---

### Task 11: Task manifest, run orchestration, CLI and the live smoke run (M1)

**Files:**
- Create: `src/margin/bench/__init__.py`, `src/margin/bench/tasks.py`, `src/margin/run.py`, `src/margin/cli.py`, `src/margin/__main__.py`, `scripts/make_smoke_repo.py`
- Modify: `src/margin/telemetry.py` only if Task 2 recorded a needed change
- Test: `tests/test_tasks.py`, `tests/test_run.py`

**Interfaces:**
- Consumes: everything from Tasks 1–10.
- Produces (`bench/tasks.py`): `Task` (frozen dataclass: `id, split, repo, base_commit, fix_commit, issue_url, issue_file, target_tests, test_files, test_args=["tests"], deps=["pytest"], pythonpath=["."]`) with `.issue_text(root) -> str` and `.target_junit_ids -> list[str]`; `load_tasks(path) -> list[Task]`; `find_task(tasks, task_id) -> Task`; `Prepared(sandbox, baseline, baseline_seconds, bare)`; `prepare_run(task, run_dir, settings, *, venv_python=None, use_baseline_cache=True) -> Prepared`.
- Produces (`run.py`, arm A usable now): `new_run_id(task_id, arm) -> str`; `execute_run(task, arm, settings, *, tasks_root=None, client=None, run_id=None, version="v1", venv_python=None, resume=False, faults=None, after_turn_hook=None, trace_tags=None) -> RunRecord` (also writes `runs/<id>/receipt.md` and appends to the ledger).
- Produces (`cli.py`): `main(argv=None) -> int` with the `run` subcommand; later tasks add subcommands.
- Branches for arms B and C import modules created in Tasks 14 and 15 (`margin.quote`, `GraphContext`); they are not exercised until Task 15.

- [ ] **Step 1: Write the failing tests**

`tests/test_tasks.py`:

```python
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import git

from margin.bench.tasks import Task, find_task, load_tasks, prepare_run
from margin.config import Settings


def make_source_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A repo whose fix commit repairs pkg/mathy.py and adds the failing test."""
    src = tmp_path / "src_repo"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "__init__.py").write_text("")
    (src / "pkg" / "mathy.py").write_text("def add(a, b):\n    return a - b\n")
    git(src, "init", "-q", "-b", "main")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "base")
    base = git(src, "rev-parse", "HEAD")
    (src / "pkg" / "mathy.py").write_text("def add(a, b):\n    return a + b\n")
    (src / "tests").mkdir()
    (src / "tests" / "test_mathy.py").write_text(
        "from pkg.mathy import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "fix add")
    return src, base, git(src, "rev-parse", "HEAD")


def make_task(tmp_path: Path) -> Task:
    src, base, fix = make_source_repo(tmp_path)
    issue = tmp_path / "issue.md"
    issue.write_text("add(1, 2) returns -1")
    return Task(
        id="t-add", split="calibration", repo=str(src), base_commit=base, fix_commit=fix, issue_url="local",
        issue_file=str(issue), target_tests=["tests/test_mathy.py::test_add"], test_files=["tests/test_mathy.py"],
    )


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        root=tmp_path, runs_dir=tmp_path / "runs", ledger_path=tmp_path / "runs" / "ledger.jsonl",
        cache_dir=tmp_path / "cache",
    )


def test_load_tasks_and_find(tmp_path):
    manifest = tmp_path / "tasks.toml"
    manifest.write_text(
        '[[task]]\nid = "x"\nsplit = "evaluation"\nrepo = "r"\nbase_commit = "b"\nfix_commit = "f"\n'
        'issue_url = "u"\nissue_file = "i.md"\ntarget_tests = ["tests/t.py::test_a"]\ntest_files = ["tests/t.py"]\n'
    )
    tasks = load_tasks(manifest)
    assert tasks[0].test_args == ["tests"] and tasks[0].pythonpath == ["."]
    assert tasks[0].target_junit_ids == ["tests.t::test_a"]
    assert find_task(tasks, "x") is tasks[0]
    with pytest.raises(KeyError):
        find_task(tasks, "nope")


def test_prepare_run_builds_a_worktree_with_the_test_patch_and_baseline(tmp_path):
    task = make_task(tmp_path)
    prep = prepare_run(task, tmp_path / "run1", settings_for(tmp_path), venv_python=Path(sys.executable))
    sb = prep.sandbox
    assert "def test_add" in sb.read_file("tests/test_mathy.py")          # visible failing test
    assert "return a - b" in sb.read_file("pkg/mathy.py")                 # still the buggy base
    assert prep.baseline.failing == frozenset({"tests.test_mathy::test_add"})
    assert sb.git_diff() == ""                                            # test patch is committed, diff is empty
    assert prep.baseline_seconds > 0
    again = prepare_run(task, tmp_path / "run2", settings_for(tmp_path), venv_python=Path(sys.executable))
    assert again.baseline == prep.baseline                                # served from the baseline cache
    assert (tmp_path / "cache" / "baselines" / "t-add.json").exists()


def test_prepare_run_rejects_a_fix_commit_without_test_changes(tmp_path):
    task = make_task(tmp_path)
    bad = Task(**{**task.__dict__, "test_files": ["pkg/__init__.py"]})
    with pytest.raises(ValueError, match="changes none of test_files"):
        prepare_run(bad, tmp_path / "run3", settings_for(tmp_path), venv_python=Path(sys.executable))
```

`tests/test_run.py`:

```python
import sys
from pathlib import Path

from fakes import ScriptedClient, reply, text, tool_use
from test_tasks import make_task, settings_for

from margin.ledger import Ledger
from margin.run import execute_run


def test_execute_run_arm_a_solves_the_fixture_task(tmp_path):
    task = make_task(tmp_path)
    settings = settings_for(tmp_path)
    client = ScriptedClient(
        [
            reply([tool_use("t1", "edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})], stop="tool_use"),
            reply([tool_use("t2", "run_tests", {})], stop="tool_use"),
            reply([text("fixed add")]),
        ]
    )
    rec = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=client, run_id="r-a", venv_python=Path(sys.executable)
    )
    assert rec.solved and rec.arm == "A" and rec.task_id == "t-add"
    assert rec.cost_usd > 0 and rec.price_usd == 0.0     # flat price is applied at report time
    assert rec.margin_usd == -rec.cost_usd
    rows = Ledger(settings.ledger_path).rows()
    assert [r.run_id for r in rows] == ["r-a"]
    receipt = (settings.runs_dir / "r-a" / "receipt.md").read_text()
    assert "arm A" in receipt and "verified" in receipt


def test_a_failing_run_is_recorded_not_raised(tmp_path):
    task = make_task(tmp_path)
    settings = settings_for(tmp_path)
    client = ScriptedClient([reply([text("I give up")])])
    rec = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=client, run_id="r-fail", venv_python=Path(sys.executable)
    )
    assert not rec.solved
    assert "target tests still failing" in rec.verdict_reason


def test_cheating_by_editing_the_test_is_undone_before_judging(tmp_path):
    task = make_task(tmp_path)
    settings = settings_for(tmp_path)
    client = ScriptedClient(
        [
            reply([tool_use("t1", "edit_file", {"path": "tests/test_mathy.py", "old": "== 3", "new": "== -1"})], stop="tool_use"),
            reply([text("done")]),
        ]
    )
    rec = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=client, run_id="r-cheat", venv_python=Path(sys.executable)
    )
    assert not rec.solved
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tasks.py tests/test_run.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.bench'`.

- [ ] **Step 3: Implement `bench/tasks.py`**

`src/margin/bench/__init__.py`: empty file.

```python
"""Task manifest, repo preparation (bare clone, worktree, venv) and the cached baseline snapshot."""
from __future__ import annotations

import json
import subprocess
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from margin.config import Settings
from margin.sandbox import DEFAULT_EXCLUDES, Sandbox
from margin.verify import Baseline, make_baseline, nodeid_to_junit, run_suite


@dataclass(frozen=True)
class Task:
    id: str
    split: str
    repo: str
    base_commit: str
    fix_commit: str
    issue_url: str
    issue_file: str
    target_tests: list
    test_files: list
    test_args: list = field(default_factory=lambda: ["tests"])
    deps: list = field(default_factory=lambda: ["pytest"])
    pythonpath: list = field(default_factory=lambda: ["."])

    def issue_text(self, root: Path) -> str:
        return (Path(root) / self.issue_file).read_text(encoding="utf-8")[:20_000]

    @property
    def target_junit_ids(self) -> list[str]:
        return [nodeid_to_junit(n) for n in self.target_tests]


def load_tasks(path: Path) -> list[Task]:
    data = tomllib.loads(Path(path).read_text())
    return [Task(**t) for t in data.get("task", [])]


def find_task(tasks: list[Task], task_id: str) -> Task:
    for task in tasks:
        if task.id == task_id:
            return task
    raise KeyError(f"no task with id {task_id!r}")


@dataclass
class Prepared:
    sandbox: Sandbox
    baseline: Baseline
    baseline_seconds: float
    bare: Path


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def ensure_bare_clone(task: Task, cache_dir: Path) -> Path:
    bare = Path(cache_dir) / "repos" / f"{task.id}.git"
    if not bare.exists():
        bare.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--bare", "--quiet", task.repo, str(bare)])
    return bare


def ensure_venv(task: Task, cache_dir: Path) -> Path:
    venv = Path(cache_dir) / "venvs" / task.id
    python = venv / "bin" / "python"
    if not python.exists():
        venv.parent.mkdir(parents=True, exist_ok=True)
        _run(["uv", "venv", "--python", "3.12", "--quiet", str(venv)])
        _run(["uv", "pip", "install", "--quiet", "--python", str(python), *task.deps])
    return python


def make_worktree(bare: Path, run_dir: Path, base_commit: str) -> tuple[Path, bool]:
    work = Path(run_dir) / "work"
    if work.exists():
        return work, False
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    _run(["git", "-C", str(bare), "worktree", "add", "--detach", "--quiet", str(work), base_commit])
    return work, True


def apply_test_patch(bare: Path, work: Path, task: Task, run_dir: Path) -> None:
    patch = _run(
        ["git", "-C", str(bare), "diff", "--binary", task.base_commit, task.fix_commit, "--", *task.test_files]
    ).stdout
    if not patch.strip():
        raise ValueError(f"{task.id}: the fix commit changes none of test_files {task.test_files}")
    patch_file = Path(run_dir) / "test.patch"
    patch_file.write_text(patch)
    _run(["git", "-C", str(work), "apply", str(patch_file)])
    _run(["git", "-C", str(work), "add", "-A"])
    _run(
        ["git", "-C", str(work), "-c", "user.name=margin", "-c", "user.email=margin@local",
         "commit", "--quiet", "-m", "apply test patch"]
    )


def snapshot_baseline(
    task: Task, sandbox: Sandbox, cache_dir: Path, run_dir: Path, *, use_cache: bool = True
) -> tuple[Baseline, float]:
    cache = Path(cache_dir) / "baselines" / f"{task.id}.json"
    if use_cache and cache.exists():
        data = json.loads(cache.read_text())
        return Baseline.from_dict(data["baseline"]), data["seconds"]
    started = time.time()
    first = run_suite(sandbox, task.test_args, Path(run_dir) / "baseline-1.xml")
    second = run_suite(sandbox, task.test_args, Path(run_dir) / "baseline-2.xml")
    seconds = max((time.time() - started) / 2, 0.001)
    baseline = make_baseline(first, second)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"baseline": baseline.to_dict(), "seconds": seconds}))
    return baseline, seconds


def prepare_run(
    task: Task, run_dir: Path, settings: Settings, *, venv_python: Path | None = None, use_baseline_cache: bool = True
) -> Prepared:
    bare = ensure_bare_clone(task, settings.cache_dir)
    work, created = make_worktree(bare, run_dir, task.base_commit)
    if created:
        apply_test_patch(bare, work, task, run_dir)
    python = venv_python or ensure_venv(task, settings.cache_dir)
    sandbox = Sandbox(work, python, task.pythonpath, Path(run_dir) / "home", settings.test_timeout_s)
    sandbox.exclude(DEFAULT_EXCLUDES)
    baseline, seconds = snapshot_baseline(task, sandbox, settings.cache_dir, run_dir, use_cache=use_baseline_cache)
    return Prepared(sandbox, baseline, seconds, bare)
```

- [ ] **Step 4: Implement `run.py`**

```python
"""One task, one arm, start to finish: prepare, (quote), run the agent, verify, settle, record."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from margin.agent.loop import run_agent
from margin.agent.prompts import first_prompt
from margin.agent.tools import ToolExecutor
from margin.bench.tasks import Task, prepare_run
from margin.config import Settings
from margin.context import naive_context
from margin.governor import Governor, NullGovernor
from margin.ledger import Ledger, RunRecord, render_receipt, settle
from margin.model import make_model_client
from margin.pricing import PriceTable, SpendMeter
from margin.state import RunState
from margin.telemetry import span
from margin.verify import final_verdict


def new_run_id(task_id: str, arm: str) -> str:
    return f"{task_id}-{arm}-{time.strftime('%Y%m%d-%H%M%S')}"


@span(kind="WORKFLOW", name="margin.run")
def execute_run(
    task: Task,
    arm: str,
    settings: Settings,
    *,
    tasks_root: Path | None = None,
    client: Any = None,
    run_id: str | None = None,
    version: str = "v1",
    venv_python: Path | None = None,
    resume: bool = False,
    faults: Any = None,
    after_turn_hook: Any = None,
    trace_tags: list[str] | None = None,
) -> RunRecord:
    if arm not in ("A", "B", "C"):
        raise ValueError(f"unknown arm {arm!r}")
    prices = PriceTable.load(settings.pricing_path)
    ledger = Ledger(settings.ledger_path)
    run_id = run_id or new_run_id(task.id, arm)
    run_dir = settings.runs_dir / run_id
    state = RunState(run_dir)
    (run_dir / "meta.json").write_text(json.dumps({"task_id": task.id, "arm": arm, "version": version}))
    started = time.time()

    prep = prepare_run(task, run_dir, settings, venv_python=venv_python)
    sandbox = prep.sandbox
    issue = task.issue_text(tasks_root or settings.root)

    graph = None
    features: dict = {}
    quote: dict | None = None
    price = 0.0  # arms A and B are priced at report time (flat price)
    governor: Any = NullGovernor()
    if arm in ("B", "C"):
        from margin.context import GraphContext  # added in Task 15
        from margin.quote import extract_features  # added in Task 14

        graph = GraphContext(sandbox.root)
        feats = extract_features(issue, sandbox.root, prep.baseline_seconds, graph)
        features = feats.to_dict()
        state.log("features", **features)
        if arm == "C":
            from margin.quote import Quoter, training_rows  # added in Task 14

            saved = state.events("quote") if resume else []
            if saved:  # a resumed run keeps its original quote, even if the ledger has grown since
                quote = {k: saved[-1][k] for k in ("p50", "lo", "hi")}
                price = saved[-1]["price"]
            else:
                quoted = Quoter(training_rows(ledger, exclude=task.id), prior_cost=settings.default_cost_usd).quote(feats)
                quote = {"p50": quoted.p50, "lo": quoted.lo, "hi": quoted.hi}
                price = quoted.price(settings.target_markup)
                state.log("quote", price=price, **quote)
            governor = Governor(quote["hi"], settings.downgrade_at, settings.narrow_at)

    meter = SpendMeter(prices)
    executor = ToolExecutor(
        sandbox=sandbox, arm=arm, baseline=prep.baseline, target_nodeids=task.target_tests,
        target_junit_ids=task.target_junit_ids, test_args=task.test_args, protected_paths=task.test_files,
        issue_text=issue, graph=graph, faults=faults, state=state,
    )
    context = graph.search(issue[:2000]) if graph is not None else naive_context(sandbox.root, settings.naive_context_chars)
    checkpoint = state.load_checkpoint() if resume else None
    if checkpoint:
        state.restore_meter(meter)
    result = run_agent(
        first_prompt=first_prompt(issue, context, task.target_tests), arm=arm,
        client=client or make_model_client(settings), meter=meter, governor=governor, executor=executor,
        state=state, prices=prices, settings=settings, faults=faults, resume=checkpoint,
        after_turn_hook=after_turn_hook,
    )

    sandbox.restore_paths(task.test_files)  # undo any edits to protected tests before judging
    verdict = final_verdict(sandbox, prep.baseline, task.target_junit_ids, task.test_args, run_dir / "final.xml")
    revenue, margin = settle(price, verdict.solved, meter.total_usd)
    record = RunRecord(
        run_id=run_id, task_id=task.id, arm=arm, split=task.split, solved=verdict.solved,
        cost_usd=meter.total_usd, price_usd=price, revenue_usd=revenue, margin_usd=margin,
        tokens_total=meter.total_tokens, features=features, quote=quote, rung_events=result.rung_events,
        abort_reason=None if result.stop == "end_turn" else (result.abort_reason or result.stop),
        duration_s=round(time.time() - started, 1), fault=settings.fault,
        recoveries=len(state.events("recovery")) + len(state.events("retry")),
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        trace_tags=trace_tags or [], verdict_reason=verdict.reason,
    )
    ledger.append(record)
    (run_dir / "receipt.md").write_text(render_receipt(record))
    return record
```

- [ ] **Step 5: Implement `cli.py` and `__main__.py`**

`src/margin/__main__.py`:

```python
from margin.cli import main

raise SystemExit(main())
```

`src/margin/cli.py`:

```python
"""Command line entry point. Subcommands are added task by task."""
from __future__ import annotations

import argparse
from pathlib import Path

from margin.bench.tasks import find_task, load_tasks
from margin.config import Settings, load_dotenv
from margin.telemetry import init_telemetry, shutdown_telemetry


def _tasks_path(args: argparse.Namespace, settings: Settings) -> Path:
    return Path(args.tasks_file) if args.tasks_file else settings.root / "bench" / "tasks.toml"


def cmd_run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    task = find_task(load_tasks(_tasks_path(args, settings)), args.task)
    tags = [f"arm:{args.arm}", f"task:{task.id}", f"split:{task.split}", f"version:{args.version}"]
    init_telemetry("margin", tags)  # must precede the first `import anthropic`
    try:
        from margin.run import execute_run

        rec = execute_run(
            task, args.arm, settings, run_id=args.run_id, version=args.version, trace_tags=tags
        )
        print(f"{rec.run_id}: solved={rec.solved} cost=${rec.cost_usd:.4f} margin=${rec.margin_usd:.4f}")
        print(f"receipt: {settings.runs_dir / rec.run_id / 'receipt.md'}")
        return 0 if rec.solved else 1
    finally:
        shutdown_telemetry()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="margin")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one task with one arm")
    run.add_argument("--task", required=True)
    run.add_argument("--arm", required=True, choices=["A", "B", "C"])
    run.add_argument("--tasks-file", default=None)
    run.add_argument("--run-id", default=None)
    run.add_argument("--version", default="v1")
    run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    return args.func(args)
```

- [ ] **Step 6: Write `scripts/make_smoke_repo.py`**

```python
"""Create a throwaway local repo and manifest for the live smoke run.

Everything lands in bench/cache, which is gitignored.
"""
import shutil
import subprocess

from margin.config import ROOT

CACHE = ROOT / "bench" / "cache"
SRC = CACHE / "smoke-src"


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=smoke", "-c", "user.email=smoke@local", *args],
        cwd=SRC, check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def main() -> None:
    shutil.rmtree(SRC, ignore_errors=True)
    (SRC / "pkg").mkdir(parents=True)
    (SRC / "pkg" / "__init__.py").write_text("")
    (SRC / "pkg" / "mathy.py").write_text("def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n")
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    (SRC / "pkg" / "mathy.py").write_text("def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
    (SRC / "tests").mkdir()
    (SRC / "tests" / "test_mathy.py").write_text(
        "from pkg.mathy import add, mul\n\n\ndef test_add():\n    assert add(1, 2) == 3\n\n\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n"
    )
    git("add", "-A")
    git("commit", "-q", "-m", "fix add")
    fix = git("rev-parse", "HEAD")
    issue = CACHE / "smoke-issue.md"
    issue.write_text("`add(1, 2)` returns -1 instead of 3. It looks like subtraction is used instead of addition.\n")
    manifest = CACHE / "smoke.toml"
    manifest.write_text(
        f'[[task]]\nid = "smoke-add"\nsplit = "calibration"\nrepo = "{SRC}"\nbase_commit = "{base}"\n'
        f'fix_commit = "{fix}"\nissue_url = "local"\nissue_file = "{issue}"\n'
        'target_tests = ["tests/test_mathy.py::test_add"]\ntest_files = ["tests/test_mathy.py"]\n'
        'test_args = ["tests"]\ndeps = ["pytest"]\npythonpath = ["."]\n'
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_tasks.py tests/test_run.py`
Expected: 6 passed.

- [ ] **Step 8: Live smoke run (needs both keys; costs a few cents)**

```bash
uv run python scripts/make_smoke_repo.py
uv run margin run --tasks-file bench/cache/smoke.toml --task smoke-add --arm A --version v0
cat runs/smoke-add-A-*/receipt.md
```

Expected: exit 0, `solved=True`, a receipt with a non-zero cost, and a `margin` workflow trace tagged `arm:A`, `task:smoke-add`, `version:v0` in neatlogs showing AGENT turns, TOOL spans and LLM spans with token counts.

- [ ] **Step 9: Measure and record real cost**

From the receipt, record the cost of this one tiny run in `docs/notes/neatlogs-findings.md` under "Smoke run cost", then ask the builder to set `MARGIN_BENCH_BUDGET_USD` in `.env` from it. Do not guess the budget from the planning estimate.

- [ ] **Step 10: Run everything and commit**

```bash
uv run pytest && uv run ruff check src tests scripts
git add src/margin/bench src/margin/run.py src/margin/cli.py src/margin/__main__.py scripts/make_smoke_repo.py tests/test_tasks.py tests/test_run.py docs/notes
git commit -m "feat: task preparation, run orchestration and CLI (M1 walking skeleton)"
```

---

### Task 12: Task validation and curation of the 16 benchmark tasks (M3a)

**Files:**
- Modify: `src/margin/bench/tasks.py` (append `remove_worktree`, `validate_task`), `src/margin/cli.py` (add `tasks validate`)
- Create: `bench/tasks.toml`, `bench/issues/<task-id>.md` (16 files)
- Test: `tests/test_validate.py`, `tests/test_manifest.py`

**Interfaces:**
- Consumes: `Task`, `prepare_run`, `ensure_bare_clone` (Task 11); `final_verdict` (Task 7).
- Produces: `remove_worktree(bare, work)`; `validate_task(task, settings, *, venv_python=None, max_seconds=60, max_source_files=3) -> dict` with keys `id, ok, problems, baseline_seconds, source_files, target_failing_before` (also written to `bench/cache/validation/<id>.json`).
- Produces: `bench/tasks.toml` with 16 tasks (4 `calibration`, 12 `evaluation`), each passing `margin tasks validate`.

- [ ] **Step 1: Write the failing tests**

`tests/test_validate.py`:

```python
import sys
from pathlib import Path

from test_tasks import make_task, settings_for

from margin.bench.tasks import Task, validate_task


def test_validate_accepts_a_good_task(tmp_path):
    result = validate_task(make_task(tmp_path), settings_for(tmp_path), venv_python=Path(sys.executable))
    assert result["ok"], result["problems"]
    assert result["source_files"] == ["pkg/mathy.py"]
    assert result["target_failing_before"] == 1


def test_validate_flags_a_target_that_never_failed(tmp_path):
    task = make_task(tmp_path)
    bad = Task(**{**task.__dict__, "target_tests": ["tests/test_mathy.py::test_nonexistent"]})
    result = validate_task(bad, settings_for(tmp_path), venv_python=Path(sys.executable))
    assert not result["ok"]
    assert any("do not fail before the fix" in p for p in result["problems"])


def test_validate_flags_slow_suites(tmp_path):
    result = validate_task(
        make_task(tmp_path), settings_for(tmp_path), venv_python=Path(sys.executable), max_seconds=0.0001
    )
    assert not result["ok"] and any("seconds" in p for p in result["problems"])
```

`tests/test_manifest.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_validate.py tests/test_manifest.py`
Expected: `test_validate.py` fails with `ImportError: cannot import name 'validate_task'`; `test_manifest.py` fails with `FileNotFoundError: ... bench/tasks.toml` (it is satisfied only in Step 7).

- [ ] **Step 3: Implement validation (append to `src/margin/bench/tasks.py`)**

Add these imports at the top of the file (merge with the existing ones): `import shutil` and `from margin.verify import final_verdict`. Then append:

```python
def remove_worktree(bare: Path, work: Path) -> None:
    subprocess.run(["git", "-C", str(bare), "worktree", "remove", "--force", str(work)], capture_output=True)
    shutil.rmtree(work, ignore_errors=True)
    subprocess.run(["git", "-C", str(bare), "worktree", "prune"], capture_output=True)


def validate_task(
    task: Task,
    settings: Settings,
    *,
    venv_python: Path | None = None,
    max_seconds: float = 60,
    max_source_files: int = 3,
) -> dict:
    """Prove a task is usable: its tests fail before the real fix, pass after it, and it is small and fast."""
    run_dir = Path(settings.cache_dir) / "validation" / task.id
    bare = ensure_bare_clone(task, settings.cache_dir)
    remove_worktree(bare, run_dir / "work")
    shutil.rmtree(run_dir, ignore_errors=True)

    problems: list[str] = []
    prep = prepare_run(task, run_dir, settings, venv_python=venv_python, use_baseline_cache=False)
    missing = [t for t in task.target_junit_ids if t not in prep.baseline.failing]
    if missing:
        problems.append(f"target tests do not fail before the fix: {missing}")

    changed = _run(["git", "-C", str(bare), "diff", "--name-only", task.base_commit, task.fix_commit]).stdout.split()
    source_files = [f for f in changed if f not in task.test_files]
    if not source_files:
        problems.append("the fix commit changes no source files")
    if len(source_files) > max_source_files:
        problems.append(f"the fix touches {len(source_files)} source files (limit {max_source_files})")
    if prep.baseline_seconds > max_seconds:
        problems.append(f"the suite takes {prep.baseline_seconds:.1f} seconds (limit {max_seconds})")

    excludes = [f":(exclude){f}" for f in task.test_files]
    fix = _run(
        ["git", "-C", str(bare), "diff", "--binary", task.base_commit, task.fix_commit, "--", ".", *excludes]
    ).stdout
    fix_file = run_dir / "fix.patch"
    fix_file.write_text(fix)
    _run(["git", "-C", str(prep.sandbox.root), "apply", str(fix_file)])
    verdict = final_verdict(prep.sandbox, prep.baseline, task.target_junit_ids, task.test_args, run_dir / "after.xml")
    if not verdict.solved:
        problems.append(f"the real fix does not satisfy the verifier: {verdict.reason}")

    result = {
        "id": task.id,
        "ok": not problems,
        "problems": problems,
        "baseline_seconds": round(prep.baseline_seconds, 2),
        "source_files": source_files,
        "target_failing_before": len(prep.baseline.failing),
    }
    out = Path(settings.cache_dir) / "validation" / f"{task.id}.json"
    out.write_text(json.dumps(result, indent=2))
    remove_worktree(bare, prep.sandbox.root)
    return result
```

- [ ] **Step 4: Add the `tasks validate` command to `cli.py`**

Add the function above `build_parser`:

```python
def cmd_tasks_validate(args: argparse.Namespace) -> int:
    from margin.bench.tasks import validate_task

    settings = Settings.from_env()
    tasks = load_tasks(_tasks_path(args, settings))
    chosen = [find_task(tasks, i) for i in args.ids] if args.ids else tasks
    failures = 0
    for task in chosen:
        result = validate_task(task, settings)
        status = "ok  " if result["ok"] else "FAIL"
        print(f"{status} {task.id} ({result['baseline_seconds']}s) {'; '.join(result['problems'])}")
        failures += 0 if result["ok"] else 1
    return 1 if failures else 0
```

and inside `build_parser`, before `return parser`:

```python
    tasks = sub.add_parser("tasks", help="inspect and validate the benchmark tasks")
    tasks_sub = tasks.add_subparsers(dest="tasks_command", required=True)
    validate = tasks_sub.add_parser("validate", help="check tasks are usable")
    validate.add_argument("--ids", nargs="*", default=None)
    validate.add_argument("--tasks-file", default=None)
    validate.set_defaults(func=cmd_tasks_validate)
```

- [ ] **Step 5: Run the validation tests**

Run: `uv run pytest tests/test_validate.py`
Expected: 3 passed.

- [ ] **Step 6: Curate the 16 tasks (research work; one subagent per candidate repo is a good fit)**

Selection criteria (all must hold): the fix is one squash-merged commit with a single parent (`base = fix^`); it touches ≤ 3 non-test files and changes at least one test file; the changed or added test fails at `base` and passes at `fix`; the whole suite runs in under 60 s with no network; dependencies are pure Python and install with `uv pip install`; the issue text is self-contained; the licence is permissive (MIT, BSD or Apache-2.0); the tests need no compiled extension.

Screen a candidate repo with:

```bash
gh search prs --repo OWNER/REPO --merged --label bug --limit 40 --json number,title,url,closedAt
gh pr view NUMBER --repo OWNER/REPO --json number,title,url,mergeCommit,closingIssuesReferences,files
gh issue view ISSUE --repo OWNER/REPO --json title,body --jq '"# " + .title + "\n\n" + .body' > bench/issues/<task-id>.md
git ls-remote https://github.com/OWNER/REPO   # confirm the repo is reachable
```

Candidate repositories to screen first (names recalled from memory; **none is confirmed to qualify**, and some may fail the criteria): `python-slugify`, `more-itertools`, `boltons`, `cachetools`, `tabulate`, `humanize`, `tomli`, `pyjwt`, `marshmallow`. Replace any that fail. Aim for at least 5 repositories, with the 4 calibration tasks spread across at least 3 of them and the 12 evaluation tasks spread across all.

For each chosen task, add an entry to `bench/tasks.toml`:

```toml
[[task]]
id = "slugify-123"
split = "evaluation"            # or "calibration"
repo = "https://github.com/OWNER/REPO"
base_commit = "<40-char sha of fix^>"
fix_commit = "<40-char sha of the squash-merge commit>"
issue_url = "https://github.com/OWNER/REPO/issues/123"
issue_file = "bench/issues/slugify-123.md"
target_tests = ["tests/test_slugify.py::test_regression_123"]
test_files = ["tests/test_slugify.py"]
test_args = ["tests"]
deps = ["pytest"]               # add the repo's pure-Python test dependencies here
pythonpath = ["."]              # use ["src"] for src-layout projects
```

Then validate each and fix or replace any failure:

```bash
uv run margin tasks validate
```

Expected: 16 lines starting `ok`. Ask the builder to review the final list before committing, since the choice of tasks shapes every number that follows.

- [ ] **Step 7: Run the manifest tests**

Run: `uv run pytest tests/test_manifest.py`
Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add src/margin/bench/tasks.py src/margin/cli.py bench/tasks.toml bench/issues tests/test_validate.py tests/test_manifest.py
git commit -m "feat: task validation and the 16-task benchmark manifest"
```

---

### Task 13: Batch runner, report metrics and arm A runs (M3b)

**Files:**
- Create: `src/margin/bench/runner.py`, `src/margin/bench/report.py`
- Modify: `src/margin/cli.py` (add `bench`, `calibrate-flat`)
- Test: `tests/test_runner.py`, `tests/test_report.py`

**Interfaces:**
- Consumes: `Ledger`, `RunRecord`, `settle` (Task 4); `new_run_id` (Task 11); `Task`, `load_tasks` (Task 11).
- Produces (`runner.py`): `BudgetExceeded(RuntimeError)`; `run_batch(tasks, arm, settings, *, version, tasks_file=None, runner=subprocess.run, python=sys.executable, only_missing=False) -> list[str]` (raises `BudgetExceeded` before launching a run once ledger spend ≥ `settings.bench_budget_usd`).
- Produces (`report.py`): `calibrate_flat_price(rows_a: dict[str, RunRecord], markup) -> dict` (`flat_price_usd, mean_cost_usd, n, markup`); `apply_flat_price(rows, flat_price) -> list[RunRecord]` (arms A and B only); `summarize(rows) -> dict` (`n, solve_rate, profitable_share, gross_margin, wasted_spend_usd, tokens_per_solved, cost_total_usd, revenue_total_usd`); `compare_table(summaries: dict[str, dict]) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_runner.py`:

```python
from types import SimpleNamespace

import pytest
from test_ledger import rec

from margin.bench.runner import BudgetExceeded, run_batch
from margin.bench.tasks import Task
from margin.config import Settings
from margin.ledger import Ledger


def task(i):
    return Task(
        id=f"t{i}", split="evaluation", repo="r", base_commit="b", fix_commit="f", issue_url="u",
        issue_file="i.md", target_tests=["tests/t.py::test_a"], test_files=["tests/t.py"],
    )


def fake_runner(ledger, cost):
    def run(cmd, **kwargs):
        value = lambda flag: cmd[cmd.index(flag) + 1]  # noqa: E731
        ledger.append(rec(run_id=value("--run-id"), task=value("--task"), arm=value("--arm"), cost=cost))
        return SimpleNamespace(returncode=0, stderr="")

    return run


def test_batch_launches_one_subprocess_per_task(tmp_path):
    settings = Settings(ledger_path=tmp_path / "ledger.jsonl", bench_budget_usd=100.0, root=tmp_path)
    ledger = Ledger(settings.ledger_path)
    ids = run_batch([task(1), task(2)], "A", settings, version="v1", runner=fake_runner(ledger, 0.5))
    assert len(ids) == 2
    assert [r.task_id for r in ledger.rows()] == ["t1", "t2"]


def test_batch_stops_before_the_next_run_once_the_budget_is_spent(tmp_path):
    settings = Settings(ledger_path=tmp_path / "ledger.jsonl", bench_budget_usd=1.0, root=tmp_path)
    ledger = Ledger(settings.ledger_path)
    with pytest.raises(BudgetExceeded, match="t4"):
        run_batch([task(i) for i in range(1, 6)], "A", settings, version="v1", runner=fake_runner(ledger, 0.4))
    assert len(ledger.rows()) == 3


def test_only_missing_skips_tasks_that_already_have_a_row(tmp_path):
    settings = Settings(ledger_path=tmp_path / "ledger.jsonl", bench_budget_usd=100.0, root=tmp_path)
    ledger = Ledger(settings.ledger_path)
    ledger.append(rec(run_id="old", task="t1", arm="A"))
    ids = run_batch([task(1), task(2)], "A", settings, version="v1", runner=fake_runner(ledger, 0.1), only_missing=True)
    assert len(ids) == 1


def test_a_subprocess_that_writes_no_row_is_skipped_not_fatal(tmp_path, capsys):
    settings = Settings(ledger_path=tmp_path / "ledger.jsonl", bench_budget_usd=100.0, root=tmp_path)
    crashed = lambda cmd, **kw: SimpleNamespace(returncode=2, stderr="boom")  # noqa: E731
    assert run_batch([task(1)], "A", settings, version="v1", runner=crashed) == []
    assert "no ledger row" in capsys.readouterr().err
```

`tests/test_report.py`:

```python
import pytest
from test_ledger import rec

from margin.bench.report import apply_flat_price, calibrate_flat_price, compare_table, summarize


def test_summarize_three_runs():
    rows = [
        rec(run_id="1", task="a", solved=True, cost=1.0, price=2.0),
        rec(run_id="2", task="b", solved=True, cost=2.0, price=2.0),
        rec(run_id="3", task="c", solved=False, cost=1.0, price=2.0),
    ]
    s = summarize(rows)
    assert s["n"] == 3
    assert s["solve_rate"] == pytest.approx(2 / 3)
    assert s["profitable_share"] == pytest.approx(1 / 3)   # margins 1.0, 0.0, -1.0
    assert s["gross_margin"] == pytest.approx(0.0)         # revenue 4.0, cost 4.0
    assert s["wasted_spend_usd"] == pytest.approx(1.0)
    assert s["tokens_per_solved"] == pytest.approx(1000)
    assert s["cost_total_usd"] == pytest.approx(4.0)


def test_summarize_empty_and_no_revenue():
    assert summarize([])["n"] == 0
    s = summarize([rec(solved=False, cost=1.0, price=2.0)])
    assert s["gross_margin"] is None and s["tokens_per_solved"] is None


def test_calibrate_flat_price_uses_only_calibration_runs():
    rows = {
        "a": rec(task="a", cost=1.0), "b": rec(task="b", cost=3.0), "c": rec(task="c", cost=100.0),
    }
    rows["a"].split = rows["b"].split = "calibration"
    result = calibrate_flat_price(rows, markup=0.5)
    assert result["mean_cost_usd"] == pytest.approx(2.0)
    assert result["flat_price_usd"] == pytest.approx(3.0)
    assert result["n"] == 2


def test_calibrate_flat_price_requires_calibration_runs():
    with pytest.raises(ValueError, match="no arm A calibration"):
        calibrate_flat_price({"c": rec(task="c")}, markup=0.5)


def test_apply_flat_price_only_reprices_arms_a_and_b():
    rows = [rec(arm="A", cost=1.0, price=0.0), rec(arm="B", cost=1.0, price=0.0, solved=False),
            rec(arm="C", cost=1.0, price=9.0)]
    a, b, c = apply_flat_price(rows, 3.0)
    assert (a.price_usd, a.revenue_usd, a.margin_usd) == (3.0, 3.0, 2.0)
    assert (b.price_usd, b.revenue_usd, b.margin_usd) == (3.0, 0.0, -1.0)
    assert c.price_usd == 9.0


def test_compare_table_orders_arms_and_marks_missing_values():
    table = compare_table({"B": summarize([rec(solved=False)]), "A": summarize([rec()])})
    lines = table.splitlines()
    assert lines[0].startswith("| Arm") and lines[2].startswith("| A") and lines[3].startswith("| B")
    assert "n/a" in lines[3]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_runner.py tests/test_report.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.bench.runner'`.

- [ ] **Step 3: Make run ids collision-proof (edit `src/margin/run.py`)**

Add `import uuid` to the imports and replace `new_run_id`:

```python
def new_run_id(task_id: str, arm: str) -> str:
    return f"{task_id}-{arm}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
```

- [ ] **Step 4: Implement `bench/runner.py`**

```python
"""Batch runner: one subprocess per (task, arm) so neatlogs tags are per run, with a global spend guard."""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable

from margin.bench.tasks import Task
from margin.config import Settings
from margin.ledger import Ledger
from margin.run import new_run_id


class BudgetExceeded(RuntimeError):
    pass


def run_batch(
    tasks: list[Task],
    arm: str,
    settings: Settings,
    *,
    version: str,
    tasks_file: str | None = None,
    runner: Callable = subprocess.run,
    python: str = sys.executable,
    only_missing: bool = False,
) -> list[str]:
    ledger = Ledger(settings.ledger_path)
    spent = sum(r.cost_usd for r in ledger.rows())
    done = {r.task_id for r in ledger.rows(arm)} if only_missing else set()
    run_ids: list[str] = []
    for task in tasks:
        if task.id in done:
            continue
        if spent >= settings.bench_budget_usd:
            raise BudgetExceeded(
                f"spent ${spent:.2f} of the ${settings.bench_budget_usd:.2f} budget before {task.id}"
            )
        run_id = new_run_id(task.id, arm)
        cmd = [python, "-m", "margin", "run", "--task", task.id, "--arm", arm, "--run-id", run_id, "--version", version]
        if tasks_file:
            cmd += ["--tasks-file", tasks_file]
        proc = runner(cmd, cwd=settings.root, capture_output=True, text=True)
        row = next((r for r in ledger.rows() if r.run_id == run_id), None)
        if row is None:
            print(f"{task.id}: no ledger row (exit {proc.returncode}): {proc.stderr[-500:]}", file=sys.stderr)
            continue
        spent += row.cost_usd
        run_ids.append(run_id)
    return run_ids
```

- [ ] **Step 5: Implement `bench/report.py` (metrics only; the results page is added in Task 18)**

```python
"""Metrics and tables. Every published number is computed here from the ledger."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from margin.ledger import RunRecord, settle


def calibrate_flat_price(rows_a: dict[str, RunRecord], markup: float) -> dict:
    calibration = [r for r in rows_a.values() if r.split == "calibration"]
    if not calibration:
        raise ValueError("no arm A calibration runs in the ledger")
    mean_cost = sum(r.cost_usd for r in calibration) / len(calibration)
    return {
        "flat_price_usd": round(mean_cost * (1 + markup), 6),
        "mean_cost_usd": round(mean_cost, 6),
        "n": len(calibration),
        "markup": markup,
    }


def apply_flat_price(rows: Iterable[RunRecord], flat_price: float) -> list[RunRecord]:
    out = []
    for row in rows:
        if row.arm in ("A", "B"):
            revenue, margin = settle(flat_price, row.solved, row.cost_usd)
            row = replace(row, price_usd=flat_price, revenue_usd=revenue, margin_usd=margin)
        out.append(row)
    return out


def summarize(rows: list[RunRecord]) -> dict:
    n = len(rows)
    solved = [r for r in rows if r.solved]
    revenue = sum(r.revenue_usd for r in rows)
    cost = sum(r.cost_usd for r in rows)
    return {
        "n": n,
        "solve_rate": len(solved) / n if n else 0.0,
        "profitable_share": sum(1 for r in rows if r.margin_usd > 0) / n if n else 0.0,
        "gross_margin": (revenue - cost) / revenue if revenue > 0 else None,
        "wasted_spend_usd": sum(r.cost_usd for r in rows if not r.solved),
        "tokens_per_solved": sum(r.tokens_total for r in solved) / len(solved) if solved else None,
        "cost_total_usd": cost,
        "revenue_total_usd": revenue,
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.2f}"


def compare_table(summaries: dict[str, dict]) -> str:
    lines = [
        "| Arm | Runs | Solve rate | Profitable jobs | Gross margin | Wasted spend | Tokens / solved fix |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in sorted(summaries):
        s = summaries[arm]
        tokens = "n/a" if s["tokens_per_solved"] is None else f"{s['tokens_per_solved']:,.0f}"
        lines.append(
            f"| {arm} | {s['n']} | {_pct(s['solve_rate'])} | {_pct(s['profitable_share'])} | "
            f"{_pct(s['gross_margin'])} | {_money(s['wasted_spend_usd'])} | {tokens} |"
        )
    return "\n".join(lines)
```

- [ ] **Step 6: Add `bench` and `calibrate-flat` commands to `cli.py`**

Add above `build_parser`:

```python
def cmd_bench(args: argparse.Namespace) -> int:
    from margin.bench.runner import BudgetExceeded, run_batch

    settings = Settings.from_env()
    tasks = load_tasks(_tasks_path(args, settings))
    chosen = [t for t in tasks if args.split == "all" or t.split == args.split]
    try:
        ids = run_batch(
            chosen, args.arm, settings, version=args.version, tasks_file=args.tasks_file,
            only_missing=args.only_missing,
        )
    except BudgetExceeded as exc:
        print(f"stopped: {exc}")
        return 2
    print(f"{len(ids)} runs recorded in {settings.ledger_path}")
    return 0


def cmd_calibrate_flat(args: argparse.Namespace) -> int:
    import json

    from margin.bench.report import calibrate_flat_price
    from margin.ledger import Ledger

    settings = Settings.from_env()
    result = calibrate_flat_price(Ledger(settings.ledger_path).latest("A"), settings.target_markup)
    path = settings.root / "bench" / "flat_price.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"flat price ${result['flat_price_usd']:.4f} from {result['n']} calibration runs -> {path}")
    return 0
```

and inside `build_parser`, before `return parser`:

```python
    bench = sub.add_parser("bench", help="run one arm over many tasks")
    bench.add_argument("--arm", required=True, choices=["A", "B", "C"])
    bench.add_argument("--split", default="all", choices=["all", "calibration", "evaluation"])
    bench.add_argument("--version", default="v1")
    bench.add_argument("--tasks-file", default=None)
    bench.add_argument("--only-missing", action="store_true")
    bench.set_defaults(func=cmd_bench)

    flat = sub.add_parser("calibrate-flat", help="set the flat price from arm A calibration costs")
    flat.set_defaults(func=cmd_calibrate_flat)
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_runner.py tests/test_report.py`
Expected: 10 passed.

- [ ] **Step 8: Run arm A on the calibration tasks (live; spends money)**

```bash
uv run pytest && uv run ruff check src tests scripts
uv run margin bench --arm A --split calibration --version v1
uv run margin calibrate-flat
```

Expected: 4 runs recorded; `bench/flat_price.json` written. Inspect the four receipts and the four neatlogs traces (tags `arm:A`, `version:v1`). If runs fail for environmental reasons (dependency install, pytest invocation), fix the task entry or `deps`, re-run `margin tasks validate --ids <id>`, and re-run only that task. Record the cost per run and ask the builder to confirm `MARGIN_BENCH_BUDGET_USD` before continuing.

- [ ] **Step 9: Diagnose with traces and stabilise the shared core**

In a Claude Code session with the neatlogs MCP connected (Task 2, Step 7):
1. Use `search_traces` to find the four `arm:A` calibration runs, and `get_trace_context` on any run that was unsolved, unusually costly, or full of tool errors. The span tree carries code locations, which is the path from a failing run to the responsible code.
2. Fix only defects in the **shared core** (tool error messages, prompts, sandbox behaviour, verifier). Never change anything that would favour one arm. One commit per fix, naming the run id and trace in the message; each commit made in-session gets an Entire checkpoint.
3. Re-run the affected calibration task (`uv run margin run --task ID --arm A --version v1`) and add a row to `docs/evidence/fixes.md`: the defect, the trace before, the trace after, and the cost and verdict of each.
4. Stop when the four calibration runs behave sensibly, then re-run `uv run margin calibrate-flat` so the flat price reflects the stabilised core. From here the core is frozen: any later change to shared code means re-running every arm.

- [ ] **Step 10: Run arm A on the evaluation tasks, then commit**

```bash
uv run margin bench --arm A --split evaluation --version v1
git add src/margin bench/flat_price.json tests docs/evidence/fixes.md
git commit -m "feat: batch runner, report metrics and arm A baseline runs"
```

These arm A runs are the "before" evidence: do not delete their traces, and do not re-run arm A later without keeping the originals.

---

### Task 14: Quoter (features, nearest-neighbour band, leave-one-out evaluation)

**Files:**
- Create: `src/margin/quote.py`
- Modify: `src/margin/context.py` (rename `_is_source` to the public `is_source`)
- Test: `tests/test_quote.py`

**Interfaces:**
- Consumes: `is_source` from `margin.context` (Task 9, renamed here).
- Produces: `Features(issue_tokens: int, impact_files: int, repo_loc: int, baseline_seconds: float)` with `.vector()`, `.to_dict()`, `Features.from_dict(d)`; `Quote(p50, lo, hi)` with `.price(markup)`.
- Produces: `Quoter(rows: Sequence[tuple[Features, float]], *, prior_cost: float = 1.0)` with `.q` (band half-width in log space) and `.quote(features) -> Quote`.
- Produces: `LooResult(task_id, actual, quote, inside, abs_log_error)`; `evaluate_loo(rows: Sequence[tuple[str, Features, float]], prior_cost=1.0) -> list[LooResult]` (each row is quoted by a Quoter fit on all the other rows).
- Produces: `count_python_loc(root) -> int`; `extract_features(issue, root, baseline_seconds, graph) -> Features` where `graph` has `.impact_size(issue_text) -> int`.
- Produces: `training_rows(ledger, exclude: str | None = None) -> list[tuple[Features, float]]`: the arm B rows with features, minus one task, which `run.py` feeds to `Quoter`.
- Constants: `K = 3`, `COLD_START_MIN = 5`, `MIN_Q = 0.05`, `DEFAULT_Q = ln 2`.

- [ ] **Step 1: Rename the helper in `context.py`**

In `src/margin/context.py` rename `_is_source` to `is_source` (definition and its use inside `naive_context`). Run `uv run pytest tests/test_context.py` and expect 4 passed.

- [ ] **Step 2: Write the failing tests**

`tests/test_quote.py`:

```python
import math

import pytest
from test_ledger import rec

from margin.ledger import Ledger
from margin.quote import (
    DEFAULT_Q, MIN_Q, Features, Quote, Quoter, count_python_loc, evaluate_loo, extract_features, training_rows,
)


def feat(i=100, f=3, loc=1000, s=2.0):
    return Features(i, f, loc, s)


def test_features_roundtrip_and_vector_is_log_scaled():
    f = feat()
    assert Features.from_dict(f.to_dict()) == f
    assert f.vector()[0] == pytest.approx(math.log1p(100))


def test_empty_ledger_uses_the_prior_with_a_finite_band():
    q = Quoter([], prior_cost=1.0).quote(feat())
    assert q.p50 == 1.0
    assert 0 < q.lo < q.p50 < q.hi < float("inf")
    assert q.hi == pytest.approx(math.exp(DEFAULT_Q))


def test_all_equal_costs_give_a_minimum_width_band():
    rows = [(feat(i=100 + 10 * k), 2.0) for k in range(6)]
    q = Quoter(rows).quote(feat())
    assert q.p50 == 2.0
    assert q.hi == pytest.approx(2.0 * math.exp(MIN_Q))
    assert q.lo == pytest.approx(2.0 * math.exp(-MIN_Q))


def test_few_rows_use_the_median_of_all_of_them():
    rows = [(feat(i=100), 1.0), (feat(i=5000), 9.0), (feat(i=120), 3.0)]
    assert Quoter(rows).quote(feat(i=110)).p50 == 3.0


def test_the_nearest_three_neighbours_drive_the_estimate():
    small = [(feat(i=100 + k, f=2, loc=500, s=1.0), 0.2) for k in range(5)]
    large = [(feat(i=3000 + k, f=40, loc=50_000, s=30.0), 4.0) for k in range(5)]
    quoter = Quoter(small + large)
    assert quoter.quote(feat(i=102, f=2, loc=500, s=1.0)).p50 == pytest.approx(0.2)
    assert quoter.quote(feat(i=3002, f=40, loc=50_000, s=30.0)).p50 == pytest.approx(4.0)


def test_price_applies_the_markup_to_the_upper_bound():
    assert Quote(1.0, 0.5, 2.0).price(0.5) == pytest.approx(3.0)


def test_zero_costs_do_not_break_the_logarithms():
    rows = [(feat(i=100 + k), 0.0) for k in range(6)]
    q = Quoter(rows).quote(feat())
    assert q.p50 > 0 and q.lo < q.hi


def test_evaluate_loo_is_out_of_sample_and_self_consistent():
    rows = [(f"t{k}", feat(i=100 + 50 * k), 0.01 * (100 + 50 * k)) for k in range(10)]
    results = evaluate_loo(rows)
    assert [r.task_id for r in results] == [f"t{k}" for k in range(10)]
    for r in results:
        assert r.inside == (r.quote.lo <= r.actual <= r.quote.hi)
        assert r.quote.lo < r.quote.hi
        assert r.abs_log_error >= 0


def test_evaluate_loo_with_identical_costs_is_fully_covered():
    rows = [(f"t{k}", feat(i=100 + 50 * k), 2.0) for k in range(8)]
    assert all(r.inside for r in evaluate_loo(rows))


def test_evaluate_loo_with_one_row_still_returns_a_result():
    (only,) = evaluate_loo([("t", feat(), 1.5)], prior_cost=1.0)
    assert only.quote.p50 == 1.0


def test_count_python_loc_ignores_tests(repo):
    assert count_python_loc(repo) == 2


def test_extract_features_uses_the_graph_for_impact(repo):
    class Graph:
        def impact_size(self, issue):
            return 7

    f = extract_features("x" * 400, repo, 2.5, Graph())
    assert (f.issue_tokens, f.impact_files, f.baseline_seconds) == (100, 7, 2.5)


def test_training_rows_use_arm_b_rows_with_features_and_exclude_the_current_task(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(rec(run_id="1", task="a", arm="B", cost=1.0, features=feat().to_dict()))
    ledger.append(rec(run_id="2", task="b", arm="B", cost=2.0, features=feat(i=500).to_dict()))
    ledger.append(rec(run_id="3", task="c", arm="B", cost=3.0))                              # no features: skipped
    ledger.append(rec(run_id="4", task="d", arm="A", cost=4.0, features=feat().to_dict()))  # wrong arm: skipped
    assert training_rows(ledger, exclude="b") == [(feat(), 1.0)]
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_quote.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.quote'`.

- [ ] **Step 4: Implement `quote.py`**

```python
"""Pre-run cost quote learned from past runs.

Prediction: the median cost of the K nearest past runs (standardised log features), or the median of
all of them when fewer than COLD_START_MIN exist. Spread: the 90th percentile of leave-one-out
|ln(actual / predicted)|. The band is [p50 e^-q, p50 e^+q]; its upper bound is what the spec calls p90.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from margin.context import is_source

EPS = 1e-6
K = 3
COLD_START_MIN = 5
DEFAULT_Q = math.log(2.0)  # a x2 band when there is too little data to estimate the spread
MIN_Q = 0.05               # never a zero-width band


@dataclass(frozen=True)
class Features:
    issue_tokens: int
    impact_files: int
    repo_loc: int
    baseline_seconds: float

    def vector(self) -> list[float]:
        return [
            math.log1p(self.issue_tokens), math.log1p(self.impact_files),
            math.log1p(self.repo_loc), math.log1p(self.baseline_seconds),
        ]

    def to_dict(self) -> dict:
        return {
            "issue_tokens": self.issue_tokens, "impact_files": self.impact_files,
            "repo_loc": self.repo_loc, "baseline_seconds": self.baseline_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Features":
        return cls(int(d["issue_tokens"]), int(d["impact_files"]), int(d["repo_loc"]), float(d["baseline_seconds"]))


@dataclass(frozen=True)
class Quote:
    p50: float
    lo: float
    hi: float

    def price(self, markup: float) -> float:
        return self.hi * (1 + markup)


class Quoter:
    def __init__(self, rows: Sequence[tuple[Features, float]], *, prior_cost: float = 1.0):
        self.rows = [(f, max(cost, EPS)) for f, cost in rows]
        self.prior_cost = prior_cost
        self._sd = self._spreads()
        self.q = self._spread()

    def _spreads(self) -> list[float]:
        if not self.rows:
            return [1.0] * 4
        columns = list(zip(*(f.vector() for f, _ in self.rows)))
        out = []
        for col in columns:
            mean = sum(col) / len(col)
            out.append((sum((x - mean) ** 2 for x in col) / len(col)) ** 0.5 or 1.0)
        return out

    def _distance(self, a: list[float], b: list[float]) -> float:
        return sum(((x - y) / s) ** 2 for x, y, s in zip(a, b, self._sd)) ** 0.5

    def _predict(self, features: Features, exclude: int | None = None) -> float:
        vector = features.vector()
        pool = [
            (self._distance(vector, f.vector()), i, cost)
            for i, (f, cost) in enumerate(self.rows)
            if i != exclude
        ]
        if not pool:
            return self.prior_cost
        costs = [cost for _, _, cost in sorted(pool)]
        if len(pool) < COLD_START_MIN:
            return statistics.median(costs)
        return statistics.median(costs[:K])

    def _spread(self) -> float:
        if len(self.rows) < 2:
            return DEFAULT_Q
        residuals = sorted(
            abs(math.log(cost / self._predict(f, exclude=i))) for i, (f, cost) in enumerate(self.rows)
        )
        index = max(0, math.ceil(0.9 * len(residuals)) - 1)
        return max(residuals[index], MIN_Q)

    def quote(self, features: Features) -> Quote:
        p50 = self._predict(features)
        return Quote(p50, p50 * math.exp(-self.q), p50 * math.exp(self.q))


@dataclass(frozen=True)
class LooResult:
    task_id: str
    actual: float
    quote: Quote
    inside: bool
    abs_log_error: float


def evaluate_loo(rows: Sequence[tuple[str, Features, float]], prior_cost: float = 1.0) -> list[LooResult]:
    """Quote every task using a Quoter fit only on the other tasks, so coverage is out of sample."""
    results = []
    for i, (task_id, features, actual) in enumerate(rows):
        others = [(f, cost) for j, (_, f, cost) in enumerate(rows) if j != i]
        quote = Quoter(others, prior_cost=prior_cost).quote(features)
        results.append(
            LooResult(
                task_id, actual, quote, quote.lo <= actual <= quote.hi,
                abs(math.log(max(actual, EPS) / max(quote.p50, EPS))),
            )
        )
    return results


def count_python_loc(root: Path) -> int:
    root = Path(root)
    total = 0
    for path in root.rglob("*.py"):
        if is_source(path, root):
            with path.open(encoding="utf-8", errors="replace") as handle:
                total += sum(1 for _ in handle)
    return total


def extract_features(issue: str, root: Path, baseline_seconds: float, graph: Any) -> Features:
    return Features(
        issue_tokens=max(1, len(issue) // 4),
        impact_files=graph.impact_size(issue),
        repo_loc=count_python_loc(root),
        baseline_seconds=baseline_seconds,
    )


def training_rows(ledger: Any, exclude: str | None = None) -> list[tuple[Features, float]]:
    """Arm B rows the quoter learns from: unconstrained, graph-scoped runs, minus the task being quoted."""
    return [
        (Features.from_dict(row.features), row.cost_usd)
        for task_id, row in ledger.latest("B").items()
        if task_id != exclude and row.features
    ]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_quote.py`
Expected: 13 passed. The result of `evaluate_loo` with identical costs can only fail if `Quoter` produced a band that excludes `p50`; if so, check `MIN_Q`.

- [ ] **Step 6: Commit**

```bash
git add src/margin/quote.py src/margin/context.py tests/test_quote.py
git commit -m "feat: nearest-neighbour quoter with leave-one-out evaluation"
```

---

### Task 15: entire-graph adapter and arm B runs (M4)

**Files:**
- Modify: `src/margin/context.py` (append the graph adapter), `src/margin/run.py` (graph-failure fallback), `src/margin/sandbox.py` (only if graph artifacts are found)
- Create: `tests/fixtures/graph_search_agent.txt`, `tests/fixtures/graph_impact_text.txt`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: `GraphError`, `is_source` (Tasks 9 and 14).
- Produces: `extract_paths(text) -> list[str]` (distinct repo-relative `.py` paths in order of appearance); `extract_identifiers(text, limit=3) -> list[str]`; `GraphContext(repo, *, binary="entire", timeout=90, runner=subprocess.run, max_context_bytes=12_288)` with `.search(query, top_k=6) -> str`, `.impact(symbol) -> str`, `.impact_size(issue_text) -> int`; failures raise `GraphError`.
- The adapter treats `entire graph` output as text and extracts paths by regex, because the JSON schema is undocumented.

- [ ] **Step 1: Capture real graph output and check for stray artifacts**

```bash
cd ~/Desktop/margin
mkdir -p tests/fixtures
git status --short
entire graph doctor
entire graph search --query "compute the cost of a model call from token usage" --repo . \
  --format agent --profile full --top-k 4 --max-context-bytes 6000 > tests/fixtures/graph_search_agent.txt
entire graph impact --symbol PriceTable --repo . --depth 1 --limit 10 --format text \
  --max-context-bytes 3000 > tests/fixtures/graph_impact_text.txt
head -30 tests/fixtures/graph_search_agent.txt
git status --short
```

Expected: `doctor` confirms no network egress; both fixture files are non-empty and mention `src/margin/pricing.py`; the second `git status` shows only the two new fixture files. Any other new path (for example a cache directory) is a graph artifact: note its pattern for Step 8.

- [ ] **Step 2: Write the failing tests**

`tests/test_graph.py`:

```python
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


@pytest.mark.skipif(shutil.which("entire") is None, reason="entire CLI is not installed")
def test_real_graph_search_finds_code_in_this_repo():
    out = GraphContext(ROOT).search("price table cost of a model call", top_k=3)
    assert ".py" in out
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_graph.py`
Expected: FAIL with `ImportError: cannot import name 'GraphContext' from 'margin.context'`.

- [ ] **Step 4: Implement the adapter (append to `src/margin/context.py`)**

Add `import re` and `import subprocess` to the module's imports, then append:

```python
_PATH_RE = re.compile(r"(?<![\w/.\-])((?:[\w.\-]+/)*[\w.\-]+\.py)(?!\w)")
_BACKTICK = re.compile(r"`([A-Za-z_][\w.]*)`")
_CAMEL = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")
_SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def extract_paths(text: str) -> list[str]:
    """Distinct `.py` paths in order of appearance, whatever format the graph printed them in."""
    seen: dict[str, None] = {}
    for match in _PATH_RE.finditer(text):
        seen.setdefault(match.group(1).removeprefix("./"), None)
    return list(seen)


def extract_identifiers(text: str, limit: int = 3) -> list[str]:
    """Symbol-looking names in an issue: backticked first (dotted names split), then CamelCase, then snake_case."""
    found: list[str] = []

    def add(name: str) -> None:
        if len(name) > 2 and name not in found:
            found.append(name)

    for match in _BACKTICK.finditer(text):
        for part in reversed(match.group(1).split(".")):
            add(part)
    for pattern in (_CAMEL, _SNAKE):
        for match in pattern.finditer(text):
            add(match.group(0))
    return found[:limit]


class GraphContext:
    """Thin adapter over `entire graph`. It runs locally and sends nothing to a model or the network."""

    def __init__(
        self,
        repo: Path,
        *,
        binary: str = "entire",
        timeout: int = 90,
        runner=subprocess.run,
        max_context_bytes: int = 12_288,
    ):
        self.repo = Path(repo).resolve()
        self.binary = binary
        self.timeout = timeout
        self.runner = runner
        self.max_context_bytes = max_context_bytes

    def _run(self, *args: str) -> str:
        cmd = [self.binary, "graph", *args, "--repo", str(self.repo)]
        try:
            proc = self.runner(cmd, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise GraphError(f"entire graph timed out after {self.timeout}s") from exc
        except FileNotFoundError as exc:
            raise GraphError("the entire CLI is not on PATH") from exc
        if proc.returncode != 0:
            raise GraphError((proc.stderr or proc.stdout).strip()[:500] or f"exit {proc.returncode}")
        return proc.stdout.replace(f"{self.repo}/", "")

    def search(self, query: str, top_k: int = 6) -> str:
        return self._run(
            "search", "--query", query, "--top-k", str(top_k), "--format", "agent",
            "--profile", "full", "--max-context-bytes", str(self.max_context_bytes),
        )

    def impact(self, symbol: str) -> str:
        return self._run(
            "impact", "--symbol", symbol, "--depth", "1", "--limit", "10",
            "--format", "text", "--max-context-bytes", "3000",
        )

    def impact_size(self, issue_text: str) -> int:
        """Distinct files touched by the blast radius of the symbols the issue names."""
        files: set[str] = set()
        for identifier in extract_identifiers(issue_text):
            try:
                files.update(extract_paths(self.impact(identifier)))
            except GraphError:
                continue
        if not files:
            try:
                files.update(extract_paths(self.search(issue_text[:2000], top_k=8)))
            except GraphError:
                pass
        return len(files)
```

- [ ] **Step 5: Fall back to plain context if the graph fails at run start (edit `src/margin/run.py`)**

Change the import `from margin.context import naive_context` to `from margin.context import GraphError, naive_context`. Replace the line

```python
    context = graph.search(issue[:2000]) if graph is not None else naive_context(sandbox.root, settings.naive_context_chars)
```

with

```python
    context = _initial_context(graph, issue, sandbox.root, settings, state)
```

and add above `execute_run`:

```python
def _initial_context(graph: Any, issue: str, root: Path, settings: Settings, state: RunState) -> str:
    if graph is not None:
        try:
            return graph.search(issue[:2000])
        except GraphError as exc:
            state.log("graph_error", error=str(exc))  # fall back rather than lose the run
    return naive_context(root, settings.naive_context_chars)
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_graph.py && uv run pytest`
Expected: all graph tests pass (including the real-CLI test), and the whole suite is green.

- [ ] **Step 7: Live smoke run of arm B (needs keys; costs cents)**

```bash
uv run python scripts/make_smoke_repo.py
uv run margin run --tasks-file bench/cache/smoke.toml --task smoke-add --arm B --version v0
git -C runs/smoke-add-B-*/work status --short
```

Expected: `solved=True`; the receipt shows `features` were logged (`runs/<id>/events.jsonl` contains a `features` event); and the final `git status --short` prints nothing.

- [ ] **Step 8: Exclude graph artifacts if Step 7 printed any**

If `git status --short` listed untracked paths created by `entire graph`, add their patterns to `DEFAULT_EXCLUDES` in `src/margin/sandbox.py` (for example `".entire/"`), re-run Step 7 and confirm it prints nothing. Skip this step if it printed nothing.

- [ ] **Step 9: Run arm B on all 16 tasks (live; the ledger rows become the quoter's training data)**

```bash
uv run margin bench --arm B --split calibration --version v1-graph
uv run margin bench --arm B --split evaluation --version v1-graph
```

Expected: 16 runs recorded. Check that every B row has non-empty `features` (`uv run python -c "from margin.ledger import Ledger; from margin.config import Settings; print([r.task_id for r in Ledger(Settings().ledger_path).latest('B').values() if not r.features])"` prints `[]`).

- [ ] **Step 10: First arm A vs arm B comparison**

```bash
uv run python - <<'EOF'
import json
from margin.bench.report import apply_flat_price, compare_table, summarize
from margin.config import Settings
from margin.ledger import Ledger

s = Settings()
flat = json.loads((s.root / "bench" / "flat_price.json").read_text())["flat_price_usd"]
ledger = Ledger(s.ledger_path)
rows = {a: [r for r in apply_flat_price(ledger.latest(a).values(), flat) if r.split == "evaluation"] for a in "AB"}
print(compare_table({a: summarize(r) for a, r in rows.items()}))
EOF
```

Record the output in `hackathon.md` under the build log. The tokens-per-solved-fix column is the measured effect of graph-scoped context.

- [ ] **Step 11: Commit**

```bash
uv run ruff check src tests scripts
git add src/margin tests bench/flat_price.json
git commit -m "feat: entire-graph adapter and graph-scoped context (arm B)"
```

---

### Task 16: Arm C: quote, cap and receipts, plus threshold tuning (M5)

**Files:**
- Modify: `src/margin/cli.py` (add `quote`)
- Create: `tests/test_arm_c.py`, `docs/notes/tuning.md`
- Modify if tuning moves them: `src/margin/config.py` (`downgrade_at`, `narrow_at` defaults), `tests/test_config.py`

**Interfaces:**
- Consumes: `execute_run` (Task 11, whose arm C branch already uses `Quoter`, `training_rows`, `Governor`); `GraphContext` (Task 15).
- Produces: `margin quote --task ID` which prints the band and price for a task without running the agent.

- [ ] **Step 1: Write the failing tests**

`tests/test_arm_c.py`:

```python
import sys
from pathlib import Path

import pytest
from fakes import FakeGraph, ScriptedClient, reply, text, tool_use
from test_ledger import rec
from test_tasks import make_task, settings_for

from margin.ledger import Ledger
from margin.quote import Features
from margin.run import execute_run


class StubGraph(FakeGraph):
    def __init__(self, root):
        self.root = root

    def impact_size(self, issue):
        return 3


def seed_ledger(settings, cost):
    ledger = Ledger(settings.ledger_path)
    for k in range(6):
        features = Features(20 + k, 3, 2, 0.5 + k / 100).to_dict()
        ledger.append(rec(run_id=f"b{k}", task=f"seed{k}", arm="B", cost=cost, features=features))


def solving_client():
    return ScriptedClient(
        [
            reply([tool_use("t1", "edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})], stop="tool_use"),
            reply([tool_use("t2", "run_tests", {})], stop="tool_use"),
            reply([text("fixed")]),
        ]
    )


def test_arm_c_quotes_prices_and_solves(tmp_path, monkeypatch):
    monkeypatch.setattr("margin.context.GraphContext", StubGraph)
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    seed_ledger(settings, cost=5.0)
    result = execute_run(
        task, "C", settings, tasks_root=tmp_path, client=solving_client(), run_id="c1", venv_python=Path(sys.executable)
    )
    assert result.solved
    assert result.quote["lo"] < result.quote["p50"] < result.quote["hi"]
    assert result.price_usd == pytest.approx(result.quote["hi"] * 1.5)
    assert result.features["impact_files"] == 3
    assert result.margin_usd == pytest.approx(result.price_usd - result.cost_usd)


def test_arm_c_aborts_cleanly_when_the_cap_is_below_one_call(tmp_path, monkeypatch):
    monkeypatch.setattr("margin.context.GraphContext", StubGraph)
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    seed_ledger(settings, cost=0.001)
    client = ScriptedClient([])
    result = execute_run(
        task, "C", settings, tasks_root=tmp_path, client=client, run_id="c2", venv_python=Path(sys.executable)
    )
    assert not result.solved and "cap" in result.abort_reason
    assert client.calls == [] and result.cost_usd == 0.0 and result.margin_usd == 0.0
    assert [e["rung"] for e in result.rung_events] == ["ABORT"]


def test_arm_c_with_an_empty_ledger_uses_the_prior_band(tmp_path, monkeypatch):
    monkeypatch.setattr("margin.context.GraphContext", StubGraph)
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    result = execute_run(
        task, "C", settings, tasks_root=tmp_path, client=solving_client(), run_id="c3", venv_python=Path(sys.executable)
    )
    assert result.quote["p50"] == pytest.approx(settings.default_cost_usd)
    assert result.quote["lo"] < result.quote["hi"]
```

- [ ] **Step 2: Run to verify behaviour**

Run: `uv run pytest tests/test_arm_c.py`
Expected: 3 passed. The arm C branch was written in Task 11 and made reachable by Tasks 14 and 15, so these tests pass as soon as they exist. If any fails, fix `run.py`, not the test.

- [ ] **Step 3: Add the `quote` command to `cli.py`**

Add above `build_parser`:

```python
def cmd_quote(args: argparse.Namespace) -> int:
    from margin.bench.tasks import prepare_run
    from margin.context import GraphContext
    from margin.ledger import Ledger
    from margin.quote import Quoter, extract_features, training_rows

    settings = Settings.from_env()
    task = find_task(load_tasks(_tasks_path(args, settings)), args.task)
    prep = prepare_run(task, settings.runs_dir / f"quote-{task.id}", settings)
    features = extract_features(
        task.issue_text(settings.root), prep.sandbox.root, prep.baseline_seconds, GraphContext(prep.sandbox.root)
    )
    rows = training_rows(Ledger(settings.ledger_path), exclude=task.id)
    quote = Quoter(rows, prior_cost=settings.default_cost_usd).quote(features)
    print(
        f"{task.id}: cost band ${quote.lo:.4f} - ${quote.hi:.4f} (p50 ${quote.p50:.4f}) "
        f"from {len(rows)} past runs; price ${quote.price(settings.target_markup):.4f}"
    )
    return 0
```

and inside `build_parser`, before `return parser`:

```python
    quote = sub.add_parser("quote", help="print the price band for a task without running it")
    quote.add_argument("--task", required=True)
    quote.add_argument("--tasks-file", default=None)
    quote.set_defaults(func=cmd_quote)
```

- [ ] **Step 4: Check a quote against real data (live, free)**

Run: `uv run margin quote --task <an-evaluation-task-id>`
Expected: one line with a band, a p50, "from 15 past runs" and a price. Spot-check that the band is not absurdly wide (a band of `$0.0001 - $500` means `q` is huge; look at the LOO residuals before going on).

- [ ] **Step 5: Tune the rung thresholds on the calibration tasks only (live)**

Run arm C on the four calibration tasks under a few threshold pairs, one version tag per pair, and compare. Never run these variants on evaluation tasks.

```bash
uv run margin bench --arm C --split calibration --version v2-tune-default
MARGIN_DOWNGRADE_AT=0.5 MARGIN_NARROW_AT=0.8  uv run margin bench --arm C --split calibration --version v2-tune-early
MARGIN_DOWNGRADE_AT=0.7 MARGIN_NARROW_AT=0.9  uv run margin bench --arm C --split calibration --version v2-tune-late
uv run python - <<'EOF'
from margin.bench.report import summarize
from margin.config import Settings
from margin.ledger import Ledger

rows = Ledger(Settings().ledger_path).rows("C")
for version in ("v2-tune-default", "v2-tune-early", "v2-tune-late"):
    chosen = [r for r in rows if f"version:{version}" in r.trace_tags]
    s = summarize(chosen)
    print(version, f"n={s['n']} solve={s['solve_rate']:.0%} profitable={s['profitable_share']:.0%} "
          f"wasted=${s['wasted_spend_usd']:.2f} cost=${s['cost_total_usd']:.2f} revenue=${s['revenue_total_usd']:.2f}")
EOF
```

Write the three result lines and the decision in `docs/notes/tuning.md`. Choose the pair with the best profit that does not lower the solve rate; with four tasks the difference may be noise, in which case keep the spec defaults (0.6 and 0.85) and say so in the note. If you change the defaults, edit `downgrade_at` and `narrow_at` in `src/margin/config.py` and the matching assertion in `tests/test_config.py::test_defaults`.

- [ ] **Step 6: Run arm C on the 12 evaluation tasks (live)**

Run: `uv run margin bench --arm C --split evaluation --version v2`
Expected: 12 runs recorded. Read at least two receipts: one where the governor intervened, one where it did not.

- [ ] **Step 7: Commit**

```bash
uv run pytest && uv run ruff check src tests scripts
git add src/margin tests docs/notes
git commit -m "feat: arm C quote-and-cap runs, quote command and threshold tuning notes"
```

---

### Task 17: Fault injection, visible failures and resume (M6)

**Files:**
- Modify: `src/margin/faults.py` (full implementation), `src/margin/telemetry.py` (add `record_failure`), `src/margin/agent/tools.py` (`_recovery`), `src/margin/agent/loop.py` (`call_with_retry`), `src/margin/cli.py` (`run` fault wiring, `resume`)
- Create: `scripts/resume_demo.sh`, `tests/test_faults.py`, `tests/test_resume.py`

**Interfaces:**
- Produces: `FAULTS = ("api_overload", "flaky_tests", "tool_timeout")`; `FaultInjector(kind=None, *, overloads=2)` with `.before_model_call()`, `.before_tests()`, `.corrupt_run(run, protect=frozenset())`.
- Produces: `margin.telemetry.record_failure(name, detail, kind="TOOL") -> None`.
- Produces: `margin resume --run-id ID`.

- [ ] **Step 1: Write the failing tests**

`tests/test_faults.py`:

```python
import pytest
from fakes import FakeExecutor, ScriptedClient, reply, text
from test_tools import make_executor

from margin import telemetry
from margin.agent.loop import run_agent
from margin.config import ROOT, Settings
from margin.errors import TransientModelError
from margin.faults import FAULTS, FaultInjector
from margin.governor import NullGovernor
from margin.pricing import PriceTable, SpendMeter
from margin.sandbox import SuiteTimeout
from margin.state import RunState
from margin.verify import SuiteRun

PRICES = PriceTable.load(ROOT / "pricing.toml")


def test_unknown_fault_kind_is_rejected():
    with pytest.raises(ValueError):
        FaultInjector("nope")
    assert set(FAULTS) == {"api_overload", "flaky_tests", "tool_timeout"}


def test_api_overload_fails_twice_then_clears():
    fault = FaultInjector("api_overload")
    for _ in range(2):
        with pytest.raises(TransientModelError):
            fault.before_model_call()
    fault.before_model_call()


def test_tool_timeout_fires_once():
    fault = FaultInjector("tool_timeout")
    with pytest.raises(SuiteTimeout):
        fault.before_tests()
    fault.before_tests()


def test_flaky_tests_flips_one_unprotected_passing_test_once():
    fault = FaultInjector("flaky_tests")
    run = SuiteRun(frozenset({"a::t1", "a::t2"}), frozenset())
    flipped = fault.corrupt_run(run, protect={"a::t1"})
    assert flipped.failed == frozenset({"a::t2"}) and flipped.passed == frozenset({"a::t1"})
    assert fault.corrupt_run(run, protect=set()) == run


def test_no_fault_changes_nothing():
    fault = FaultInjector(None)
    fault.before_model_call()
    fault.before_tests()
    run = SuiteRun(frozenset({"a::t1"}), frozenset())
    assert fault.corrupt_run(run) == run


def test_the_flaky_fault_is_cleared_by_the_rerun(sandbox, tmp_path):
    state = RunState(tmp_path / "s")
    executor = make_executor(sandbox, tmp_path, faults=FaultInjector("flaky_tests"), state=state)
    out = executor.execute("run_tests", {})
    assert "New failures vs baseline: none" in out.text
    assert [e["kind"] for e in state.events("recovery")] == ["flaky_rerun"]


def test_a_test_timeout_falls_back_to_the_target_tests(sandbox, tmp_path):
    state = RunState(tmp_path / "s")
    executor = make_executor(sandbox, tmp_path, faults=FaultInjector("tool_timeout"), state=state)
    out = executor.execute("run_tests", {})
    assert "Target tests: 1 failing of 1" in out.text
    assert [e["kind"] for e in state.events("recovery")] == ["tool_timeout"]


def test_api_overload_is_retried_inside_the_loop(tmp_path):
    state = RunState(tmp_path / "s")
    sleeps = []
    result = run_agent(
        first_prompt="F", arm="A", client=ScriptedClient([reply([text("ok")])]), meter=SpendMeter(PRICES),
        governor=NullGovernor(), executor=FakeExecutor(), state=state, prices=PRICES, settings=Settings(),
        faults=FaultInjector("api_overload"), sleep=sleeps.append,
    )
    assert result.stop == "end_turn" and sleeps == [1, 2] and len(state.events("retry")) == 2


def test_record_failure_is_a_noop_when_telemetry_is_off():
    assert telemetry.record_failure("failed:x", "boom") is None
```

`tests/test_resume.py`:

```python
import sys
from pathlib import Path

import pytest
from fakes import ScriptedClient, reply, text, tool_use
from test_tasks import make_task, settings_for

from margin.errors import SimulatedCrash
from margin.ledger import Ledger
from margin.run import execute_run


def script():
    return [
        reply([tool_use("t1", "edit_file", {"path": "pkg/mathy.py", "old": "a - b", "new": "a + b"})], stop="tool_use"),
        reply([tool_use("t2", "run_tests", {})], stop="tool_use"),
        reply([text("fixed")]),
    ]


def test_a_crashed_run_resumes_to_the_same_verified_result(tmp_path):
    task, settings = make_task(tmp_path), settings_for(tmp_path)

    def crash(turn):
        if turn == 1:
            raise SimulatedCrash()

    common = dict(tasks_root=tmp_path, run_id="rz", venv_python=Path(sys.executable))
    with pytest.raises(SimulatedCrash):
        execute_run(task, "A", settings, client=ScriptedClient(script()), after_turn_hook=crash, **common)
    assert Ledger(settings.ledger_path).rows() == []  # a crashed run records nothing
    result = execute_run(task, "A", settings, client=ScriptedClient(script()[1:]), resume=True, **common)
    assert result.solved
    assert len(Ledger(settings.ledger_path).rows()) == 1
    assert result.cost_usd == pytest.approx(3 * (100 * 2.0 + 50 * 10.0) / 1e6)  # all three model calls are paid for
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_faults.py tests/test_resume.py`
Expected: `test_faults.py` fails (`FaultInjector("nope")` does not raise; `record_failure` is missing); `test_resume.py` should already pass because resume was built in Tasks 5, 10 and 11. If it fails, fix `run.py`, not the test.

- [ ] **Step 3: Implement `faults.py`**

Replace the stub with:

```python
"""Deterministic fault injection for the recovery demo. One kind at a time, each firing a fixed number of times."""
from __future__ import annotations

from margin.errors import TransientModelError
from margin.sandbox import SuiteTimeout
from margin.verify import SuiteRun

FAULTS = ("api_overload", "flaky_tests", "tool_timeout")


class FaultInjector:
    def __init__(self, kind: str | None = None, *, overloads: int = 2):
        if kind is not None and kind not in FAULTS:
            raise ValueError(f"unknown fault {kind!r}; choose from {FAULTS}")
        self.kind = kind
        self._overloads_left = overloads if kind == "api_overload" else 0
        self._timeout_pending = kind == "tool_timeout"
        self._flaky_pending = kind == "flaky_tests"

    def before_model_call(self) -> None:
        if self._overloads_left > 0:
            self._overloads_left -= 1
            raise TransientModelError("injected 529: the API is overloaded")

    def before_tests(self) -> None:
        if self._timeout_pending:
            self._timeout_pending = False
            raise SuiteTimeout("injected test-runner timeout")

    def corrupt_run(self, run: SuiteRun, protect: frozenset | set = frozenset()) -> SuiteRun:
        """Report one real, passing, non-target test as failed, once (a spurious failure)."""
        if not self._flaky_pending:
            return run
        candidates = sorted(set(run.passed) - set(protect))
        if not candidates:
            return run
        self._flaky_pending = False
        victim = candidates[0]
        return SuiteRun(run.passed - {victim}, run.failed | {victim})
```

- [ ] **Step 4: Add `record_failure` to `telemetry.py`**

Append:

```python
def record_failure(name: str, detail: str, kind: str = "TOOL") -> None:
    """Emit a span marked as failed for an action that failed and was then recovered from."""
    if not _enabled:
        return
    try:
        with trace(name, kind=kind, **{"margin.detail": detail}):
            raise RuntimeError(detail)
    except RuntimeError:
        pass
```

If Task 2 recorded that error spans need extra attributes to render as failed, apply that same adjustment here.

- [ ] **Step 5: Make failures and recoveries visible in neatlogs**

In `src/margin/agent/tools.py` change the telemetry import to `from margin.telemetry import record_failure, trace` and replace `_recovery`:

```python
    def _recovery(self, kind: str, detail: str) -> None:
        if self.state is not None:
            self.state.log("recovery", kind=kind, detail=detail)
        record_failure(f"failed:{kind}", detail)
        with trace(f"recovery:{kind}", kind="GUARDRAIL", **{"margin.recovery": kind, "margin.detail": detail}):
            pass
```

In `src/margin/agent/loop.py` change the telemetry import to `from margin.telemetry import record_failure, trace` and, inside `call_with_retry`, after the `state.log("retry", ...)` line and before `sleep(delay)`, add:

```python
            record_failure("failed:model_call", f"{type(exc).__name__}: {exc}")
            with trace("retry", kind="GUARDRAIL", **{"margin.attempt": attempt + 1, "margin.delay_s": delay}):
                pass
```

- [ ] **Step 6: Wire faults into `run` and add `resume` (edit `src/margin/cli.py`)**

In `cmd_run`, replace the `execute_run(...)` call with:

```python
        from margin.faults import FaultInjector

        faults = FaultInjector(settings.fault) if settings.fault else None
        rec = execute_run(
            task, args.arm, settings, run_id=args.run_id, version=args.version, trace_tags=tags, faults=faults
        )
```

Add above `build_parser`:

```python
def cmd_resume(args: argparse.Namespace) -> int:
    import json

    from margin.ledger import Ledger

    settings = Settings.from_env()
    if any(r.run_id == args.run_id for r in Ledger(settings.ledger_path).rows()):
        print(f"{args.run_id} already finished; nothing to resume")
        return 1
    meta = json.loads((settings.runs_dir / args.run_id / "meta.json").read_text())
    task = find_task(load_tasks(_tasks_path(args, settings)), meta["task_id"])
    tags = [
        f"arm:{meta['arm']}", f"task:{task.id}", f"split:{task.split}", f"version:{meta['version']}", "resumed:true"
    ]
    init_telemetry("margin", tags)
    try:
        from margin.faults import FaultInjector
        from margin.run import execute_run

        faults = FaultInjector(settings.fault) if settings.fault else None
        rec = execute_run(
            task, meta["arm"], settings, run_id=args.run_id, version=meta["version"], resume=True,
            faults=faults, trace_tags=tags,
        )
        print(f"{rec.run_id}: resumed, solved={rec.solved} cost=${rec.cost_usd:.4f} margin=${rec.margin_usd:.4f}")
        return 0 if rec.solved else 1
    finally:
        shutdown_telemetry()
```

and inside `build_parser`, before `return parser`:

```python
    resume = sub.add_parser("resume", help="continue a killed run from its checkpoint")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--tasks-file", default=None)
    resume.set_defaults(func=cmd_resume)
```

- [ ] **Step 7: Create `scripts/resume_demo.sh`**

```bash
#!/usr/bin/env bash
# Kill a live run mid-flight (after its first checkpoint), then resume it from persisted state.
# Pick a task that takes several turns, or the run may finish before the kill lands.
set -euo pipefail
TASK="${1:?usage: resume_demo.sh TASK_ID [ARM]}"
ARM="${2:-C}"
RUN_ID="demo-resume-$(date +%H%M%S)"

uv run margin run --task "$TASK" --arm "$ARM" --run-id "$RUN_ID" --version demo-resume &
until [ -f "runs/$RUN_ID/checkpoint.json" ]; do sleep 1; done
sleep 2
pkill -9 -f -- "--run-id $RUN_ID" || true
wait 2>/dev/null || true
echo "killed after the first checkpoint; resuming $RUN_ID"
uv run margin resume --run-id "$RUN_ID"
```

Then `chmod +x scripts/resume_demo.sh`.

- [ ] **Step 8: Run tests**

Run: `uv run pytest && uv run ruff check src tests scripts`
Expected: everything passes, including the 9 fault tests and the resume test.

- [ ] **Step 9: Produce the failure-recovery evidence (live; pick one evaluation task)**

```bash
MARGIN_FAULT=flaky_tests  uv run margin run --task <eval-task> --arm C --version demo-fault-flaky
MARGIN_FAULT=tool_timeout uv run margin run --task <eval-task> --arm C --version demo-fault-timeout
MARGIN_FAULT=api_overload uv run margin run --task <eval-task> --arm C --version demo-fault-overload
scripts/resume_demo.sh <eval-task> C
```

In neatlogs, open each trace and confirm: a `failed:*` span, then a `recovery:*` or `retry` span, then the run continuing to a verified result. Save the trace links and the run ids in `docs/evidence/failure-recovery.md` (create the directory if needed). These rows carry a `fault` or `version:demo*` tag, so `Ledger.latest` ignores them and they never replace benchmark rows.

- [ ] **Step 10: Commit**

```bash
git add src/margin scripts tests docs/evidence
git commit -m "feat: fault injection, visible recoveries and resume"
```

---

### Task 18: Results page, receipts page, evidence ledger and `make verify` (M8a)

**Files:**
- Modify: `src/margin/bench/report.py` (append), `src/margin/cli.py` (`report`, `snapshot-ledger`), `Makefile`
- Create: `docs/evidence/ledger.jsonl` (snapshot), `docs/results.md` and `docs/receipts.html` (both generated)
- Test: `tests/test_results.py`

**Interfaces:**
- Consumes: `Ledger`, `RunRecord` (Task 4); `summarize`, `apply_flat_price`, `compare_table` (Task 13); `evaluate_loo`, `Features` (Task 14).
- Produces: `quote_coverage(b_rows) -> {"n", "covered", "coverage", "median_abs_log_error"}`; `render_results(ledger, flat: dict) -> str` (deterministic: no timestamps); `render_receipts_page(rows) -> str` (static HTML, no external resources).
- Produces: `margin report [--ledger P] [--flat P] [--out P] [--html P] [--check]`; `margin snapshot-ledger`; `make verify`.

- [ ] **Step 1: Write the failing tests**

`tests/test_results.py`:

```python
import json

from test_ledger import rec

from margin.bench.report import quote_coverage, render_receipts_page, render_results
from margin.cli import main
from margin.ledger import Ledger
from margin.quote import Features

FLAT = {"flat_price_usd": 3.0, "mean_cost_usd": 2.0, "n": 2, "markup": 0.5}


def feat(i):
    return Features(i, 3, 1000, 2.0).to_dict()


def build_ledger(tmp_path) -> Ledger:
    ledger = Ledger(tmp_path / "ledger.jsonl")
    plan = [("cal1", "calibration"), ("cal2", "calibration"), ("e1", "evaluation"), ("e2", "evaluation")]
    for n, (task, split) in enumerate(plan):
        for arm, cost in (("A", 2.0), ("B", 1.5)):
            row = rec(run_id=f"{arm}{n}", task=task, arm=arm, cost=cost, price=0.0,
                      features=feat(100 + 40 * n) if arm == "B" else {})
            row.split = split
            ledger.append(row)
    for n, task in enumerate(["e1", "e2"]):
        row = rec(run_id=f"C{n}", task=task, arm="C", cost=1.0, price=2.4,
                  quote={"p50": 1.2, "lo": 0.8, "hi": 1.6}, features=feat(180 + 40 * n),
                  rung_events=[{"turn": 2, "rung": "DOWNGRADE", "reason": "no progress"}])
        ledger.append(row)
    return ledger


def test_quote_coverage_counts_out_of_sample_hits(tmp_path):
    b_rows = list(build_ledger(tmp_path).latest("B").values())
    coverage = quote_coverage(b_rows)
    assert coverage["n"] == 4 and 0 <= coverage["covered"] <= 4
    assert quote_coverage([])["coverage"] is None


def test_results_page_has_every_section_and_is_deterministic(tmp_path):
    ledger = build_ledger(tmp_path)
    page = render_results(ledger, FLAT)
    assert page == render_results(ledger, FLAT)
    for needle in (
        "# Results", "Flat price", "## Arms on the evaluation tasks", "| A | 2 |", "| C | 2 |",
        "## Quote accuracy", "## Per task", "| e1 |", "DOWNGRADE",
    ):
        assert needle in page, needle
    assert "$0.80–$1.60" in page


def test_report_command_writes_then_checks(tmp_path):
    ledger = build_ledger(tmp_path)
    flat = tmp_path / "flat.json"
    flat.write_text(json.dumps(FLAT))
    out, html = tmp_path / "results.md", tmp_path / "receipts.html"
    base = ["report", "--ledger", str(ledger.path), "--flat", str(flat), "--out", str(out), "--html", str(html)]
    assert main(base) == 0
    assert out.exists() and html.exists()
    assert main([*base, "--check"]) == 0
    out.write_text(out.read_text() + "tampered")
    assert main([*base, "--check"]) == 1


def test_receipts_page_escapes_task_ids_and_shows_governor_events():
    row = rec(task="<b>x</b>", arm="C", quote={"p50": 1.0, "lo": 0.5, "hi": 2.0},
              rung_events=[{"turn": 1, "rung": "ABORT", "reason": "cap & more"}])
    page = render_receipts_page([row])
    assert "&lt;b&gt;x&lt;/b&gt;" in page and "<b>x</b>" not in page
    assert "ABORT" in page and "cap &amp; more" in page and "verified" in page
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_results.py`
Expected: FAIL with `ImportError: cannot import name 'quote_coverage'`.

- [ ] **Step 3: Implement the report additions (append to `src/margin/bench/report.py`)**

Add to the imports: `import math`, `import statistics`, `from html import escape`, `from margin.ledger import Ledger`, `from margin.quote import Features, evaluate_loo`. Append:

```python
def quote_coverage(b_rows: list[RunRecord]) -> dict:
    usable = [(r.task_id, Features.from_dict(r.features), r.cost_usd) for r in b_rows if r.features]
    results = evaluate_loo(usable)
    if not results:
        return {"n": 0, "covered": 0, "coverage": None, "median_abs_log_error": None}
    covered = sum(1 for r in results if r.inside)
    return {
        "n": len(results),
        "covered": covered,
        "coverage": covered / len(results),
        "median_abs_log_error": statistics.median(r.abs_log_error for r in results),
    }


def _verdict(row: RunRecord) -> str:
    return "verified" if row.solved else "not verified"


def render_results(ledger: Ledger, flat: dict) -> str:
    flat_price = flat["flat_price_usd"]
    latest = {arm: ledger.latest(arm) for arm in ("A", "B", "C")}
    priced = {arm: apply_flat_price(rows.values(), flat_price) for arm, rows in latest.items()}
    evaluation = {
        arm: sorted((r for r in rows if r.split == "evaluation"), key=lambda r: r.task_id)
        for arm, rows in priced.items()
    }
    summaries = {arm: summarize(rows) for arm, rows in evaluation.items() if rows}
    coverage = quote_coverage(sorted(latest["B"].values(), key=lambda r: r.task_id))

    lines = [
        "# Results",
        "",
        "Generated by `margin report` from `docs/evidence/ledger.jsonl`. Do not edit by hand; "
        "`make verify` fails if this file is stale.",
        "",
        "## Setup",
        "",
        f"- Flat price (arms A and B): ${flat_price:.4f} = mean arm A calibration cost "
        f"${flat['mean_cost_usd']:.4f} over {flat['n']} runs x (1 + {flat['markup']})",
        "- Evaluation runs per arm: " + ", ".join(f"{arm}={len(rows)}" for arm, rows in evaluation.items()),
        "",
        "## Arms on the evaluation tasks",
        "",
        compare_table(summaries),
        "",
        "## Quote accuracy (arm B costs, leave-one-out)",
        "",
    ]
    if coverage["n"]:
        factor = math.exp(coverage["median_abs_log_error"])
        lines.append(
            f"{coverage['covered']} of {coverage['n']} tasks fell inside their leave-one-out band "
            f"({coverage['coverage']:.0%}); the median quote was off by a factor of {factor:.2f}."
        )
    else:
        lines.append("No arm B rows with features yet.")
    by_arm = {arm: {r.task_id: r for r in rows} for arm, rows in evaluation.items()}
    ids = sorted({task_id for rows in by_arm.values() for task_id in rows})

    def cell(arm: str, task_id: str, fmt) -> str:
        row = by_arm.get(arm, {}).get(task_id)
        return fmt(row) if row else "n/a"

    lines += [
        "",
        "## Per task",
        "",
        "| Task | A cost | A | B cost | B | C band | C price | C cost | C | C governor |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for task_id in ids:
        band = lambda r: f"${r.quote['lo']:.2f}–${r.quote['hi']:.2f}" if r.quote else "n/a"  # noqa: E731
        governor = lambda r: ", ".join(e["rung"] for e in r.rung_events) or "none"  # noqa: E731
        cost = lambda r: f"${r.cost_usd:.2f}"  # noqa: E731
        price = lambda r: f"${r.price_usd:.2f}"  # noqa: E731
        cells = [
            task_id, cell("A", task_id, cost), cell("A", task_id, _verdict),
            cell("B", task_id, cost), cell("B", task_id, _verdict),
            cell("C", task_id, band), cell("C", task_id, price), cell("C", task_id, cost),
            cell("C", task_id, _verdict), cell("C", task_id, governor),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


_PAGE_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Margin receipts</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1c1b19;--muted:#6b685f;--ok:#1f7a4d;--no:#b3402a;--line:#e2dfd6}
@media (prefers-color-scheme:dark){:root{--bg:#141412;--card:#1d1c19;--ink:#ece9e1;--muted:#a09c90;--ok:#5cc08b;--no:#e8836d;--line:#33312b}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:32px 16px}
h1{font-size:22px;margin:0 0 4px}p.sub{color:var(--muted);margin:0 0 24px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
article{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--no);border-radius:8px;padding:16px}
article.ok{border-left-color:var(--ok)}
article h2{font-size:15px;margin:0 0 8px;word-break:break-all}
dl{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:0 0 8px}dt{color:var(--muted)}dd{margin:0;text-align:right}
ul{margin:0;padding-left:18px;color:var(--muted);font-size:13px}
</style></head><body><main>
<h1>Margin receipts</h1><p class="sub">Quoted band, price, actual cost and margin for each run.</p><div class="grid">
"""
_PAGE_TAIL = "</div></main></body></html>\n"


def render_receipts_page(rows: list[RunRecord]) -> str:
    cards = []
    for row in sorted(rows, key=lambda r: r.task_id):
        band = f"${row.quote['lo']:.2f} – ${row.quote['hi']:.2f}" if row.quote else "flat price"
        events = "".join(
            f"<li><b>{escape(e['rung'])}</b> at turn {e['turn']}: {escape(e['reason'])}</li>" for e in row.rung_events
        ) or "<li>no governor action</li>"
        cards.append(
            f'<article class="{"ok" if row.solved else "no"}"><h2>{escape(row.task_id)}</h2><dl>'
            f"<dt>Quoted cost band</dt><dd>{band}</dd><dt>Price</dt><dd>${row.price_usd:.2f}</dd>"
            f"<dt>Actual cost</dt><dd>${row.cost_usd:.2f}</dd><dt>Result</dt><dd>{_verdict(row)}</dd>"
            f"<dt>Margin</dt><dd>${row.margin_usd:.2f}</dd></dl><ul>{events}</ul></article>"
        )
    return _PAGE_HEAD + "\n".join(cards) + "\n" + _PAGE_TAIL
```

- [ ] **Step 4: Add `report` and `snapshot-ledger` to `cli.py`**

Add above `build_parser`:

```python
def cmd_report(args: argparse.Namespace) -> int:
    import json

    from margin.bench.report import render_receipts_page, render_results
    from margin.ledger import Ledger

    settings = Settings.from_env()
    ledger = Ledger(Path(args.ledger) if args.ledger else settings.root / "docs" / "evidence" / "ledger.jsonl")
    flat = json.loads(Path(args.flat or settings.root / "bench" / "flat_price.json").read_text())
    out = Path(args.out or settings.root / "docs" / "results.md")
    text = render_results(ledger, flat)
    if args.check:
        if not out.exists() or out.read_text() != text:
            print(f"{out} is stale; run `uv run margin report`")
            return 1
        print(f"{out} is up to date")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote {out}")
    html = Path(args.html) if args.html else settings.root / "docs" / "receipts.html"
    html.write_text(render_receipts_page(list(ledger.latest("C").values())))
    print(f"wrote {html}")
    return 0


def cmd_snapshot_ledger(args: argparse.Namespace) -> int:
    import shutil

    settings = Settings.from_env()
    dest = settings.root / "docs" / "evidence" / "ledger.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(settings.ledger_path, dest)
    print(f"copied {settings.ledger_path} -> {dest}")
    return 0
```

and inside `build_parser`, before `return parser`:

```python
    report = sub.add_parser("report", help="regenerate docs/results.md and the receipts page from the ledger")
    report.add_argument("--ledger", default=None)
    report.add_argument("--flat", default=None)
    report.add_argument("--out", default=None)
    report.add_argument("--html", default=None)
    report.add_argument("--check", action="store_true", help="fail if the results file is out of date")
    report.set_defaults(func=cmd_report)

    snap = sub.add_parser("snapshot-ledger", help="copy runs/ledger.jsonl to docs/evidence/ledger.jsonl")
    snap.set_defaults(func=cmd_snapshot_ledger)
```

- [ ] **Step 5: Add `make verify`**

Append to `Makefile`:

```make
.PHONY: verify
verify:
	uv run pytest
	uv run margin report --check
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_results.py && uv run ruff check src tests`
Expected: 4 passed, lint clean.

- [ ] **Step 7: Snapshot the real ledger, generate the pages, look at them**

```bash
uv run margin snapshot-ledger
uv run margin report
uv run margin report --check
open docs/receipts.html
```

Expected: `docs/results.md` and `docs/receipts.html` written, `--check` prints "up to date". Open the receipts page in a browser and screenshot it: confirm it reads clearly, nothing overflows at phone width, and the verified and not-verified cards are distinguishable. Fix the CSS if not. Read `docs/results.md` once and make sure every number matches what the receipts show.

- [ ] **Step 8: Commit**

```bash
git add src/margin Makefile tests docs/evidence/ledger.jsonl docs/results.md docs/receipts.html
git commit -m "feat: results page, receipts page, evidence ledger and make verify"
```

---

### Task 19: cfo.ai business plan from measured numbers (M7)

**Files:**
- Create: `src/margin/bench/cfo.py`, `tests/test_cfo.py`, `docs/business/` (generated inputs and the exported plan)
- Modify: `src/margin/cli.py` (add `cfo-inputs`)

**Interfaces:**
- Consumes: `Ledger`, `RunRecord`, `settle` (Task 4); `apply_flat_price`, `summarize` (Task 13).
- Produces: `percentile(values, q) -> float` (nearest rank); `cfo_inputs(ledger, flat_price) -> dict`; `render_inputs_table(inputs) -> str`; `render_ari_prompt(inputs) -> str`; `margin cfo-inputs` writing `docs/business/inputs.json`, `inputs.md`, `ari-prompt.md`.
- `cfo_inputs` returns, per arm in `A`, `B`, `C` (evaluation tasks only): `runs, solve_rate, cost_per_job_p50, cost_per_job_p90, cost_per_verified_fix, avg_price, revenue_per_job, gross_margin`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cfo.py`:

```python
import pytest
from test_ledger import rec

from margin.bench.cfo import cfo_inputs, percentile, render_ari_prompt, render_inputs_table
from margin.ledger import Ledger


def seeded(tmp_path):
    ledger = Ledger(tmp_path / "l.jsonl")
    for n, cost in enumerate([1.0, 2.0, 3.0, 4.0]):
        ledger.append(rec(run_id=f"C{n}", task=f"e{n}", arm="C", cost=cost, price=5.0, solved=n != 3))
        ledger.append(rec(run_id=f"A{n}", task=f"e{n}", arm="A", cost=cost * 2, price=0.0, solved=True))
    return ledger


def test_percentile_is_nearest_rank():
    assert percentile([1, 2, 3, 4], 0.5) == 2
    assert percentile([1, 2, 3, 4], 0.9) == 4
    assert percentile([7], 0.9) == 7
    assert percentile([], 0.5) == 0.0


def test_inputs_for_arm_c(tmp_path):
    inputs = cfo_inputs(seeded(tmp_path), flat_price=6.0)
    c = inputs["C"]
    assert c["runs"] == 4
    assert c["solve_rate"] == pytest.approx(0.75)
    assert c["cost_per_job_p50"] == 2.0 and c["cost_per_job_p90"] == 4.0
    assert c["cost_per_verified_fix"] == pytest.approx(10.0 / 3)   # all spend, including the failed run
    assert c["avg_price"] == pytest.approx(5.0)
    assert c["revenue_per_job"] == pytest.approx(15.0 / 4)        # three verified jobs pay 5.0 each
    assert c["gross_margin"] == pytest.approx((15.0 - 10.0) / 15.0)


def test_flat_price_is_applied_to_arm_a(tmp_path):
    a = cfo_inputs(seeded(tmp_path), flat_price=6.0)["A"]
    assert a["avg_price"] == pytest.approx(6.0)
    assert a["revenue_per_job"] == pytest.approx(6.0)


def test_empty_ledger_yields_no_arms(tmp_path):
    assert cfo_inputs(Ledger(tmp_path / "none.jsonl"), 1.0) == {}


def test_rendered_outputs_contain_the_measured_numbers(tmp_path):
    inputs = cfo_inputs(seeded(tmp_path), flat_price=6.0)
    table = render_inputs_table(inputs)
    assert "| C |" in table and "$10.00" not in table and "$3.33" in table
    prompt = render_ari_prompt(inputs)
    for needle in ("$2.00", "$4.00", "75%", "pricing", "runway"):
        assert needle in prompt
```

`seeded` rows use the default split `evaluation` from `rec` ✓.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cfo.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'margin.bench.cfo'`.

- [ ] **Step 3: Implement `bench/cfo.py`**

```python
"""Turn measured ledger numbers into the inputs for the cfo.ai business plan."""
from __future__ import annotations

import math

from margin.bench.report import apply_flat_price
from margin.ledger import Ledger


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def cfo_inputs(ledger: Ledger, flat_price: float) -> dict:
    out: dict[str, dict] = {}
    for arm in ("A", "B", "C"):
        rows = [
            r for r in apply_flat_price(ledger.latest(arm).values(), flat_price) if r.split == "evaluation"
        ]
        if not rows:
            continue
        solved = [r for r in rows if r.solved]
        cost = sum(r.cost_usd for r in rows)
        revenue = sum(r.revenue_usd for r in rows)
        out[arm] = {
            "runs": len(rows),
            "solve_rate": len(solved) / len(rows),
            "cost_per_job_p50": percentile([r.cost_usd for r in rows], 0.5),
            "cost_per_job_p90": percentile([r.cost_usd for r in rows], 0.9),
            "cost_per_verified_fix": cost / len(solved) if solved else None,
            "avg_price": sum(r.price_usd for r in rows) / len(rows),
            "revenue_per_job": revenue / len(rows),
            "gross_margin": (revenue - cost) / revenue if revenue > 0 else None,
        }
    return out


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.2f}"


def render_inputs_table(inputs: dict) -> str:
    lines = [
        "| Arm | Runs | Solve rate | Cost/job p50 | Cost/job p90 | Cost per verified fix | Avg price | Revenue/job | Gross margin |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, s in inputs.items():
        margin = "n/a" if s["gross_margin"] is None else f"{s['gross_margin']:.0%}"
        lines.append(
            f"| {arm} | {s['runs']} | {s['solve_rate']:.0%} | {_money(s['cost_per_job_p50'])} | "
            f"{_money(s['cost_per_job_p90'])} | {_money(s['cost_per_verified_fix'])} | {_money(s['avg_price'])} | "
            f"{_money(s['revenue_per_job'])} | {margin} |"
        )
    return "\n".join(lines)


def render_ari_prompt(inputs: dict) -> str:
    c = inputs.get("C") or next(iter(inputs.values()))
    return (
        "I run Margin, an agent that fixes software issues and charges per verified fix. "
        "Please build a monthly financial model with a base and a growth scenario, covering pricing, "
        "costs, revenue and runway.\n\n"
        "Measured unit economics from a benchmark of real runs:\n"
        f"- Cost to run one job: median {_money(c['cost_per_job_p50'])}, 90th percentile {_money(c['cost_per_job_p90'])} "
        "(mostly model usage).\n"
        f"- The agent verifies a fix on {c['solve_rate']:.0%} of jobs; customers pay only for verified fixes.\n"
        f"- All-in cost per verified fix, including failed attempts: {_money(c['cost_per_verified_fix'])}.\n"
        f"- Current average price per job: {_money(c['avg_price'])}.\n\n"
        "Please: (1) recommend a pricing structure (per verified fix, with a quote band) and test two price points; "
        "(2) model revenue and gross margin at the volumes I give you; (3) add hosting, observability and "
        "tooling costs as separate fixed lines; (4) show monthly cash and runway given my starting cash. "
        "Ask me for volumes, fixed costs and starting cash before you build it."
    )
```

In `test_inputs_for_arm_c`: C rows: costs [1,2,3,4]; `percentile(costs,0.5)`: nearest rank ceil(0.5*4)=2 → index 1 → 2.0 ✓; p90: ceil(3.6)=4 → idx 3 → 4.0 ✓. cost_per_verified_fix = total cost 10 / solved 3 ✓ (solved n!=3 → rows 0,1,2). avg_price 5.0 ✓. revenue: C rows keep own price 5.0 (apply_flat_price only A/B): `rec(price=5.0, solved)` → settle gives revenue 5.0 for solved → total 15 → per job 3.75 ✓ gross (15−10)/15 ✓. For A rows: `rec(cost=cost*2, price=0.0, solved=True)` → apply_flat_price(6.0): revenue 6.0 each → avg_price 6.0 ✓ revenue_per_job 6.0 ✓.

`test_rendered_outputs...`: table has "| C |" ✓; `"$3.33"` from cost_per_verified_fix 3.333 ✓; `"$10.00" not in table` (fine). Prompt: needles "$2.00" (p50) ✓ "$4.00" (p90) ✓ "75%" ✓ "pricing" ✓ "runway" ✓.

- [ ] **Step 4: Add the `cfo-inputs` command to `cli.py`**

```python
def cmd_cfo_inputs(args: argparse.Namespace) -> int:
    import json

    from margin.bench.cfo import cfo_inputs, render_ari_prompt, render_inputs_table
    from margin.ledger import Ledger

    settings = Settings.from_env()
    flat = json.loads((settings.root / "bench" / "flat_price.json").read_text())["flat_price_usd"]
    inputs = cfo_inputs(Ledger(settings.root / "docs" / "evidence" / "ledger.jsonl"), flat)
    out = settings.root / "docs" / "business"
    out.mkdir(parents=True, exist_ok=True)
    (out / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    (out / "inputs.md").write_text(render_inputs_table(inputs) + "\n")
    (out / "ari-prompt.md").write_text(render_ari_prompt(inputs) + "\n")
    print(render_inputs_table(inputs))
    print(f"wrote {out}/inputs.json, inputs.md and ari-prompt.md")
    return 0
```

and in `build_parser`:

```python
    cfo = sub.add_parser("cfo-inputs", help="write the measured numbers and prompt for the cfo.ai plan")
    cfo.set_defaults(func=cmd_cfo_inputs)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_cfo.py && uv run ruff check src tests`
Expected: 5 passed.

- [ ] **Step 6: Generate the real inputs**

```bash
uv run margin snapshot-ledger
uv run margin cfo-inputs
cat docs/business/ari-prompt.md
```

Expected: the table matches `docs/results.md` for the same arms (cross-check one cell by hand).

- [ ] **Step 7: Build the plan in cfo.ai (builder present; account created via cfo.ai/neathacks)**

1. Confirm the subscription was cancelled in Settings → Billing right after signup, as the event instructs; do not enter payment details anywhere else.
2. Paste `docs/business/ari-prompt.md` into cfo.ai (the web app, or its MCP server from the terminal).
3. Supply the scenario inputs the builder chooses (monthly job volumes for base and growth, fixed costs such as hosting and tooling, starting cash). These are the builder's assumptions: record them in `docs/business/assumptions.md` and label them as assumptions in any summary, never as measurements.
4. Ask for two price points and the runway under each; keep both in the plan.
5. Export or screenshot the finished model: pricing, costs, revenue, runway. Save to `docs/business/` (for example `plan.pdf` or `plan-*.png`). cfo.ai's export formats were not documented when this plan was written; screenshots are an acceptable fallback.
6. Write `docs/business/README.md`: one paragraph on the plan, the measured inputs (with a link to `docs/results.md`), the assumptions, and the resulting price, margin and runway.

- [ ] **Step 8: Commit**

```bash
git add src/margin/bench/cfo.py src/margin/cli.py tests/test_cfo.py docs/business docs/evidence/ledger.jsonl
git commit -m "feat: measured inputs and the cfo.ai business plan"
```

---

### Task 20: Entire evidence, privacy gate, EVIDENCE.md, demo and submission (M8b)

**Files:**
- Create: `EVIDENCE.md`, `tests/test_evidence.py`, `docs/demo-script.md`, `docs/evidence/posts.md`, `docs/evidence/graph-stats.txt`, `docs/evidence/checkpoints.md`
- Modify: `README.md`, `hackathon.md`, `.entire/settings.json` (only after the privacy gate passes)

**Interfaces:** none new. This task produces the artifacts judges check and a gated publication of Entire checkpoints.

- [ ] **Step 1: Write the failing evidence test**

`tests/test_evidence.py`:

```python
from margin.config import ROOT

TEXT = (ROOT / "EVIDENCE.md").read_text()


def test_evidence_page_is_complete():
    assert "{{" not in TEXT, "fill in every {{...}} placeholder with a real link"


def test_evidence_page_covers_every_required_claim():
    for claim in (
        "The agent improved", "You used neatlogs", "You used Entire", "You used cfo.ai",
        "The agent recovers from failures", "You built in public", "You wrote the code during the hackathon",
        "Known limits",
    ):
        assert claim in TEXT, claim


def test_evidence_links_to_generated_artifacts():
    for path in ("docs/results.md", "docs/business", "docs/evidence/failure-recovery.md", "make verify"):
        assert path in TEXT, path
```

Run: `uv run pytest tests/test_evidence.py`
Expected: FAIL with `FileNotFoundError: ... EVIDENCE.md`.

- [ ] **Step 2: Entire graph evidence**

```bash
cd ~/Desktop/margin
entire graph init-agents --repo .
git status --short            # expect .entire/graph-agent.md, AGENTS.md, CLAUDE.md
entire graph stats --repo . > docs/evidence/graph-stats.txt
cat docs/evidence/graph-stats.txt
```

Commit the generated agent files and the stats. Read `AGENTS.md` and `CLAUDE.md` once to confirm the generated block contains nothing personal.

- [ ] **Step 3: Confirm checkpoints exist and read one**

```bash
entire status
entire checkpoint list
entire checkpoint explain HEAD
```

Expected: at least one checkpoint from a build session. If the list is empty, the build sessions were not hooked: start Claude Code inside `~/Desktop/margin`, make a small real change there, commit it from that session, and check again. Write the checkpoint ids and commit shas you intend to cite into `docs/evidence/checkpoints.md`.

- [ ] **Step 4: Privacy gate (must pass before any checkpoint is pushed)**

Checkpoints in public repositories are public and show the session transcript. With the builder, list every string that must never appear publicly: full name, email addresses, employer or private project names, home-directory path, and any key prefix. Then search every checkpoint ref:

```bash
git for-each-ref --format='%(refname)' | grep -i entire
for ref in $(git for-each-ref --format='%(refname)' | grep -i entire); do
  git grep -I -n -i -E 'STRING1|STRING2|STRING3|/Users/' "$ref" || true
done
```

Expected: no matching lines. If anything matches, do not push: (a) look for redaction settings (`entire --help`, `entire checkpoint --help`, the `.entire/redactors/` convention the repo's `.gitignore` mentions) and add patterns for the matching strings; (b) delete the affected local checkpoint refs with `git update-ref -d <ref>`; (c) re-create the evidence from a fresh session that never contained those strings. Re-run the search until it prints nothing. Record "gate passed on <date>, strings checked: <count>" in `docs/evidence/checkpoints.md` without listing the strings.

- [ ] **Step 5: Publish checkpoints and verify the link**

Only after Step 4 printed nothing:

1. Set `"push_sessions": true` in `.entire/settings.json`, commit, and `git push`.
2. Builder: sign in at entire.io with GitHub, authorise the Entire GitHub App, and import the repository (the guide says an organisation admin imports; if a personal repository is not accepted, create an organisation, transfer `JemIIahh/margin` to it, and update the remote and README links).
3. Run `entire status` and confirm it reports sync; changes can take up to an hour to appear.
4. Open `https://entire.io/gh/OWNER/REPO/commit/<FULL_COMMIT_SHA>` for a commit that has a checkpoint; check the Sessions and Changes views both load while signed out of any private context.
5. Put that URL and the checkpoint id (from `entire checkpoint list`) in `docs/evidence/checkpoints.md`.

- [ ] **Step 6: Write `EVIDENCE.md`**

Create it with this structure, replacing each `{{...}}` with the real link or value (the test in Step 1 refuses leftovers):

```markdown
# Evidence

Every claim below links to something a judge can open. Numbers come from `docs/evidence/ledger.jsonl`;
run `make verify` to regenerate `docs/results.md` from it and fail if it differs.

## The agent improved
- Before and after, 12 evaluation tasks: [`docs/results.md`](docs/results.md).
- Same task, arm A (naive, flat price) and arm C (quote, cap, graph context): trace {{TRACE_URL_A}} versus trace {{TRACE_URL_C}}.
- What changed between them, with checkpoints: {{CHECKPOINT_LINK_FIXES}}.

## You used neatlogs
- Traces tagged `arm:A`, `arm:B`, `arm:C`: {{NEATLOGS_TRACE_LIST_URL_OR_SCREENSHOT_PATH}}.
- Span kinds used: WORKFLOW, AGENT, TOOL, GUARDRAIL (governor, verifier, recoveries), plus LLM spans with tokens and cost.

## You used Entire
- Checkpoint link: {{CHECKPOINT_URL}} (id {{CHECKPOINT_ID}}).
- entire-graph at runtime for search and impact, and its savings report: [`docs/evidence/graph-stats.txt`](docs/evidence/graph-stats.txt).

## You used cfo.ai
- Business plan covering pricing, costs, revenue and runway: [`docs/business/`](docs/business/) ({{CFO_PLAN_FILE}}).
- Measured inputs it was built from: [`docs/business/inputs.md`](docs/business/inputs.md).

## The agent recovers from failures
- Injected overload, test timeout and flaky test, each followed by recovery: [`docs/evidence/failure-recovery.md`](docs/evidence/failure-recovery.md).
- A run killed mid-flight and resumed from its checkpoint: {{RESUME_TRACE_URL}}.

## You built in public
- Posts tagged #neatHack: [`docs/evidence/posts.md`](docs/evidence/posts.md).

## You wrote the code during the hackathon
- Public repository with dated commits: {{REPO_URL}}/commits/main (first commit {{FIRST_COMMIT_DATE}}).

## Known limits
- The target tests are visible to the agent; the verifier restores them before judging, so editing them cannot help.
- Network access is not blocked inside the test sandbox; the tasks were chosen because they need none.
- 16 tasks is a small sample: treat percentages as indicative, and see the per-task table for every run.
- Model prices come from `pricing.toml`, checked on {{PRICING_CHECK_DATE}}.
- Quote accuracy is reported out of sample (leave-one-out), including the misses.
- The business plan's volumes, fixed costs and starting cash are the builder's assumptions, labelled as such in `docs/business/assumptions.md`.
```

Then run `uv run pytest tests/test_evidence.py` and expect 3 passed.

- [ ] **Step 7: Update `README.md` with run instructions**

Replace the placeholder README body with: one paragraph on what Margin does; a **Setup** section (`uv sync`, copy `.env.example` to `.env`, `entire enable --agent claude-code`); a **Run** section showing `uv run margin quote --task ID`, `uv run margin run --task ID --arm C`, `uv run margin bench --arm C --split evaluation --version v2`; a **Verify** section (`make verify`); and links to `EVIDENCE.md`, `docs/results.md`, `docs/receipts.html` and `docs/business/`. Update `hackathon.md`: the stack, a dated entry per milestone with the real before and after numbers, known limitations, and the submission section's confirmed items.

- [ ] **Step 8: Write the demo script**

Create `docs/demo-script.md` for a video of about three minutes that names all three tools. Use this structure and fill in real task ids, numbers and timestamps after rehearsing:

1. **0:00–0:30, the problem.** One sentence ("agents are hard to price"), the arm A result on a task it lost money on (receipt + cost vs flat price).
2. **0:30–1:30, the product.** `margin quote --task ID` (the band), `margin run --task ID --arm C` live or recorded, an injected fault (`MARGIN_FAULT=tool_timeout`), the governor downgrade or abort with its reason, then the receipt and `docs/receipts.html`.
3. **1:30–2:15, neatlogs and Entire.** The v1 and v2 traces side by side with the cost and token numbers; the failing trace read through the neatlogs MCP and the fix it led to; the Entire checkpoint page (Sessions, then Changes) and the entire-graph token savings.
4. **2:15–3:00, cfo.ai and the close.** The plan's price, margin and runway built from the measured p50 and p90; `make verify`; the repository link.

Record the video only after `make verify` passes. Watch it once with sound off to confirm every on-screen step is readable.

- [ ] **Step 9: Building in public**

Maintain `docs/evidence/posts.md` as a dated list of links to posts tagged #neatHack. Suggested posts, each with a trace or receipt screenshot (screenshots must be checked for keys and personal data first): the concept; the first end-to-end trace; the arm A baseline and what it lost; graph context saving tokens; the first quote versus actual; a governor intervention; a failure recovery; the cfo.ai plan; the finished evidence page and demo. Posting is the builder's action: draft the text, never post on their behalf.

- [ ] **Step 10: Final checks before the builder submits**

```bash
make verify
git log --format='%h %ad %s' --date=short | tail -3     # first commit is dated within the event
git status --short                                       # clean
grep -rniE "ANTHROPIC_API_KEY=.{8}|NEATLOGS_API_KEY=.{8}|sk-ant|nlw_[a-z0-9]{8}" --exclude-dir=.git --exclude=.env . || echo "no keys committed"
```

Expected: tests and `--check` pass, the first commit date is inside the event, the tree is clean, and the key scan prints "no keys committed".

Then give the builder the submission text to review: team name Sofer, project name Margin, the public repository link, the demo video link, and the Entire checkpoint link and id, in the format the event page asks for (a quote-post of the official neatlogs post). The builder posts it; do not submit or post anything for them.

- [ ] **Step 11: Commit**

```bash
git add EVIDENCE.md README.md hackathon.md docs tests/test_evidence.py .entire AGENTS.md CLAUDE.md
git commit -m "docs: evidence page, demo script and Entire checkpoint evidence"
```

---

### Task 21 (optional): Entire Trails and Brain for the "Best Use of Entire" prize

Do this only after Tasks 1–20 are complete and verified. It is not required for the main submission.

**Files:**
- Create: `docs/evidence/entire-extras.md`
- Modify: `EVIDENCE.md` (add a line under "You used Entire")

- [ ] **Step 1: Check the window**

The Entire guide lists its event as Oct 10–11, 2026, narrower than neatHack's. Ask in the neatHack Discord, or on the guide page, whether "Best Use of Entire" has its own submission deadline, and what it asks for. If that window has closed, skip this task and note the decision in `hackathon.md`.

- [ ] **Step 2: Trails**

1. Request Trails access with the form linked from the Entire event page.
2. In Entire, open Settings → General for the repository (needs admin) and turn on Runners, Auto build on push, and Trails.
3. From the repository root:

```bash
entire runner setup -y
git add .entire && git commit -m "chore: entire runner setup"
git push
entire trail create
```

4. Do one real change on the trail branch and merge it through its pull request, so the trail has content.

- [ ] **Step 3: Brain**

The guide installs Brain with `curl -fsSL https://raw.githubusercontent.com/entireio/entire-brain/main/scripts/get-brain.sh | bash`. That runs third-party code, so read the script first (`curl -fsSL <that URL> | less`) and only run it if it looks right. Then, in the repository:

```bash
entire brain setup
entire brain init-agents
claude mcp add entire-brain -- entire brain mcp
```

Review the files `init-agents` generated before committing them, as in Task 20, Step 2.

- [ ] **Step 4: Record what was used and what it did**

In `docs/evidence/entire-extras.md`, write which of Trails and Brain were used, one concrete thing each did for this project, and a link to the trail or checkpoint that shows it. Link that file from `EVIDENCE.md`. Commit with `git commit -m "docs: entire trails and brain evidence"`.
