# Margin — design spec

An issue-fixing agent that treats cost as a control signal: it **quotes** a price band before working, **governs** its own spend while working, and **proves** its margin afterwards. Built for neatHack (single track: "Build an agent that works (literally)").

## 1. Intent

**Outcome.** A working agent that takes a repo + issue and delivers a verified fix at a quoted price, plus public evidence that (a) it improved, (b) it recovers from failures, and (c) its economics are measured, not guessed.

**Who it is for.** Anyone selling or running agent work who cannot predict what a task will cost: maintainers, bounty hunters, small teams with a backlog, and agent builders pricing their own product.

**Why this stands out.** Agent cost per task is volatile and most vendors fall back to hybrid pricing because they cannot meter or predict it. Mid-run budget awareness is studied; a *pre-run quote learned from the agent's own trace history* is the angle we take. The task (fix an issue, tests as verifier) is deliberately conventional; the economics are the product.

**Success criteria (each must be demonstrable from the public repo):**

1. End to end: given `(repo, base commit, issue)` the agent produces a patch that makes the target tests pass with **no new failures versus the baseline** at that commit.
2. A price band is produced *before* the run; quote coverage (actual cost inside the band) is measured and reported honestly, including misses.
3. The governor visibly changes behaviour mid-run (downgrade / narrow / abort) and the trace shows the decision and reason.
4. A before/after table over the same tasks: solve rate, % jobs profitable, gross margin, spend wasted on failed runs, quote coverage.
5. A run with an injected fault shows what the agent did next.
6. A run killed mid-flight resumes from persisted state.
7. Tool evidence: neatlogs traces tagged per arm, Entire checkpoints and entire-graph output, a cfo.ai plan built from the measured cost distribution.
8. `EVIDENCE.md` links every claim to an artifact, and `make verify` regenerates the numbers from the stored ledger.

**Non-goals.** Languages other than Python; a web UI beyond one receipt page; real billing; any blockchain component; SWE-bench-grade solve-rate claims; Crustdata and AWS credits (offered by the event, not needed here).

## 2. Economics (defined once, used everywhere)

- **Revenue per job** = `price` if the verifier passes, else `0` (pay-per-verified-fix).
- **Cost per job** = tokens × price table (`pricing.toml`) + compute time, summed from the run's own metering.
- **Margin per job** = revenue − cost. Failed runs cost money and earn nothing, which is why early abort matters.
- **Flat price (arms A, B)** = mean cost of the calibration runs × (1 + target markup). Set once, not tuned per task, so the baseline is not a strawman.
- **Quoted price (arm C)** = band upper cost (p90) × (1 + the same target markup).
- Target markup is one config value (`TARGET_MARKUP`, default 0.5), identical across arms.
- Model prices live in `pricing.toml` and are verified against Anthropic's current published pricing before the first benchmark run.

## 3. Architecture

Python 3.12 (neatlogs supports 3.10–3.13; the machine default is 3.14, so the project pins 3.12 via `uv`). The agent loop calls the Anthropic SDK directly with tool use; no agent framework, so every step is ours to trace.

| Unit | Purpose | Depends on |
|---|---|---|
| `margin/agent` | Loop: plan → localize → edit → test → repair. Tools: `read_file`, `search`, `graph_*`, `apply_patch`, `run_tests`, `git_diff`. | sandbox, context, governor |
| `margin/sandbox` | One git worktree per run at the base commit; cached per-repo venv; subprocess calls with hard timeouts. | git, uv |
| `margin/context` | Adapter over `entire graph` (`search`, `impact`, `neighbors`, `def`) returning compact context packs and impact-size features. | entire CLI |
| `margin/quote` | Features → price band. kNN over the ledger; band half-width from leave-one-out log-residuals; cold-start fallback to ledger-wide median and p90. | ledger |
| `margin/governor` | Live spend meter and rung policy (below). Emits a decision event for every rung change. | pricing |
| `margin/verify` | Snapshot failing test ids at base; run after patch; verdict = target tests pass ∧ no new failing ids. | sandbox |
| `margin/state` | Append-only event log plus a step checkpoint (turn index, message digest, spend) under `runs/<id>/`; `resume` replays to the checkpoint. | none |
| `margin/ledger` | JSONL ledger of runs: features, quote, actual cost, verdict, revenue, margin. Renders the receipt (markdown + one HTML page). | none |
| `bench/` | Task manifest, runner (global spend guard), report generator, `make verify`. | all |

**Governor rungs.** Budget cap = quote p90 cost. With spend `s` and cap `C`:
1. `s < 0.6C`: continue on `claude-sonnet-5-5`.
2. `s ≥ 0.6C` and no progress (failing target tests not decreasing): switch the edit/repair loop to `claude-haiku-5-5`.
3. `s ≥ 0.85C`: narrow — stop exploring, allow one minimal-patch attempt, cap remaining turns.
4. `s ≥ C`: abort with a stated reason; revenue 0, cost bounded at the cap.

Rung thresholds are config values so they can be tuned on calibration tasks only.

**Fault injection.** `MARGIN_FAULT` selects a deterministic fault wrapped around tools: `api_overload` (simulated 529), `flaky_tests` (first run fails spuriously), `tool_timeout`. Recovery: backoff retry, isolated test re-run, re-plan with the error in context. Every recovery is a visible span.

## 4. Tool usage (how each required tool is load-bearing)

- **neatlogs.** Free on all paid plans for the event. The SDK needs the **project API key** from Settings → API keys, not the `nlw_` HTTP ingest key (that one returns 401 in the SDK); it lives in `NEATLOGS_API_KEY`, never in git. Setup is verified with `python -m neatlogs doctor --probe` (`TRACE_VISIBLE` and `TRACE_FINALIZED` must pass). `neatlogs.init(workflow_name="margin", instrumentations=["anthropic"], tags=[arm, task_id])`. `@span(kind="WORKFLOW")` per run, `AGENT` per reasoning turn, `TOOL` per tool call, `GUARDRAIL` for governor and verifier decisions, with custom attributes (`quote.p50`, `quote.p90`, `spend.usd`, `rung`). Run-to-run comparison uses tags plus our own report, because the docs describe no compare feature. The neatlogs MCP server (`search_traces`, `get_trace_context`) is connected to the coding session so failures are diagnosed from traces and the fix is checkpointed.
- **Entire.** Enabled before the first commit (Claude Code hooks, refs backend). `entire graph` is used at runtime for localization and as the quoter's impact-size feature; `entire graph stats --repo .` output is kept as evidence of token savings. `entire graph init-agents --repo .` runs once real code exists, and its generated files (`.entire/graph-agent.md`, `AGENTS.md`, `CLAUDE.md`) are committed.
  - **Submission needs** an accessible checkpoint link in the form `https://entire.io/gh/OWNER/REPO/commit/FULL_COMMIT_SHA` plus the checkpoint ID (from `entire checkpoint list`; location of the ID on the site is unverified). Checkpoints in public repositories are public, and the Sessions view shows requests and decisions.
  - **Privacy gate.** `push_sessions` is off until we have inspected a local checkpoint (`entire checkpoint explain HEAD`) for personal data and configured custom redactors where needed. Build sessions are started fresh inside this repo so earlier planning conversations are not captured.
  - **Hosted flow.** Sign in at entire.io with GitHub and authorize the Entire GitHub App; the guide says an org admin imports the repository. Whether a personal-account repo works is unverified; if an org is required we create one.
  - **Optional, after M6.** Trails and entire-brain, aimed at Entire's separate "Best Use of Entire" prize (Checkpoints, Graph or Brain). Its stated window is Oct 10–11, so check the deadline before relying on it.
- **cfo.ai.** Plan built from the measured ledger: cost per verified fix (p50/p90), solve rate, price, margin; scenarios for price tiers and volume; fixed costs and runway. Stored under `docs/business/`. Export format is unverified until we reach the product.

## 5. Evaluation design

**Tasks.** About 16 closed issues from small, pure-Python, permissively licensed repos. A task qualifies if: the fix commit touches ≤ 3 files; it adds or changes a test that fails before and passes after; the suite runs in under 60 s with no network; dependencies install with `uv`; the issue text is self-contained.

**Arms** (same tasks, same agent core):
- **A** naive: whole-file context, flat price, no governor. The agent only runs the target tests as feedback.
- **B** A + entire-graph scoped context + the baseline-aware verifier exposed to the agent as in-loop feedback, flat price. Run on a subset if budget requires; its job is to isolate the token and cost effect of graph context.
- **C** B + quote + governor.

Revenue for every arm is decided by the same baseline-aware verifier, so the arms are scored identically.

**Leakage control.** The quoter for task *t* is fit on the ledger *excluding t* (leave-one-out). Rung thresholds are tuned on a separate calibration subset, not the evaluation tasks.

**Reported metrics.** Solve rate, % jobs profitable, gross margin, wasted spend on failed runs, quote coverage and median quote error, mean tokens per solved task.

**Dev loop.** Three tasks for iteration; the full set only for evidence runs. The bench runner has a global spend guard (`MARGIN_BENCH_BUDGET_USD`) that aborts the batch, and it uses the same spend meter as the governor.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Quotes are inaccurate (pre-run token use is highly variable) | Quote is a band plus a hard cap; coverage is reported including misses; the governor bounds the downside. |
| Benchmark spend | Small dev set, global spend guard, Haiku fallback, calibration reused. |
| Sandbox flakiness | Task vetting rules; hard timeouts; per-repo cached venv. |
| Checkpoint transcripts leak personal data | `push_sessions` off; review before any publication. |
| cfo.ai export unknown | Capture the plan as screenshots and notes in `docs/business/` regardless of export support. |
| Scope | Cut order if behind: receipt HTML → markdown only; resume → documented only; narrow rung. Never cut quote, cap, downgrade, verifier, or the benchmark. |

## 7. Milestones (order, not dates)

M0 foundation (repo, Entire, neatlogs hello-trace, `neatlogs doctor`) → M1 walking skeleton (agent fixes one task, traced) → M2 verifier with baseline → M3 bench harness and arm A runs (the "before" traces) → M4 ledger, quoter, governor (arm C) → M5 fault injection and resume → M6 entire-graph context (arm B) → M7 cfo.ai plan from real numbers → M8 evidence page, demo video, submission.
