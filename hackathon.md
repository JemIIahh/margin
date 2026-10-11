# neatHack build log

## Project

- **Name:** Margin
- **Purpose:** An issue-fixing agent that quotes a price band before it works, enforces a budget while it works, and reports its margin afterwards.
- **Problem:** Agent cost per task is volatile, so agent work is hard to price. Margin makes cost a control signal and measures the result.

## Team

Solo. Registered team name: Sofer.

## Stack

- Python 3.12 (via uv). Live runs use the event's LiteLLM proxy (`claude-haiku`, fallback `nova-2-lite`) through the OpenAI SDK; the Anthropic SDK path (`claude-sonnet-5-5`, `claude-haiku-5-5`) is the default provider and has only been tested offline
- neatlogs SDK (traces), neatlogs MCP (trace queries from the coding session)
- Entire CLI 0.11.4 (checkpoints, refs backend) and entire-graph v0.4.0
- cfo.ai (business plan)
- pytest JUnit output for verification; `sandbox-exec` was used once to prove the benchmark tasks need no network

## Build log

### 2026-10-10

- Created the repo and enabled Entire for Claude Code before the first commit. Session-log auto-push is off until the checkpoint contents are reviewed.
- Installed the entire-graph plugin.
- Wrote the design spec (`docs/superpowers/specs/2026-10-10-margin-design.md`).
- Found that the machine's default Python (3.14) is outside neatlogs' supported range (3.10–3.13); the project pins 3.12.
- Read the organiser setup emails. Spec updated: the neatlogs SDK needs the project API key (not the `nlw_` ingest key); the Entire submission needs an accessible checkpoint link and ID, and checkpoints in public repos are public, so session logs stay unpushed until reviewed.

### 2026-10-10 (build session)

- Built the pipeline from the plan, task by task, each with a test written first: settings and telemetry shim, price table and spend meter, run ledger and receipts, run state with checkpoints, the sandbox, the baseline-aware verifier, the governor, agent tools, the model client and agent loop, run orchestration and CLI, the batch runner and report metrics, the nearest-neighbour quoter, the entire-graph adapter, fault injection and resume, the results and receipts pages, and the cfo.ai inputs. The suite was at 200 tests and `ruff` clean at that point.
- Corrected a price from the plan: Sonnet 5.5 cache reads are $0.10 per million tokens, not $0.20 (checked against the published pricing table).
- Security hardening found by a review and then reproduced on this machine: the agent could rewrite a worktree's `.git` pointer with a case variant (`.GIT`), which made the host run a command of its choosing during `git diff`. Fixed with a pinned git directory, a scrubbed git environment and a tamper check; the same attempt now stops at a path error.
- Chose the 16 benchmark tasks (4 calibration, 12 evaluation, 8 repositories, all closed GitHub issues) by mining each repository's history, reproducing fail-before and pass-after with the project's own verifier, then reading every issue; see `docs/notes/task-curation.md`. All 16 validate, and still validate with the network blocked.
- Validating real repositories found two defects the synthetic tests could not: pytest's rootdir fell back to this project's own config, which prefixed every test id with the worktree path (no target test could ever match), and one unimportable test module blanked a whole run. Both are fixed with regression tests.
- Ran a fresh-context code review of the whole pipeline before any live run. It found one critical problem and seven important ones, all reproduced and fixed with a failing test first: the verifier could be satisfied without a fix (a `conftest.py` hook that rewrites every outcome to "passed" scored `solved`; now test files and test infrastructure are reverted before judging, and a skipped or missing passing test counts as a regression), a tool call cut off by the output limit would have broken the next request, infrastructure errors were recorded as ordinary unsolved benchmark rows, a resume before the first checkpoint dropped paid cost, exceptions after spending left no ledger row, retries gave up after 15 seconds, and the governor called a just-fixed run "no progress". One finding was rejected after checking the live pricing page: the Sonnet 5.5 cache-read price of $0.10 is right. The suite is now at 240 tests.
- Checked the Entire checkpoints for the privacy gate: they hold full session transcripts, including local paths and email addresses, so they are not published and `push_sessions` stays off (`docs/evidence/checkpoints.md`).
- Ran `entire graph stats` over the build sessions. It reports about zero savings because those sessions barely used the graph; that says nothing about Margin's runtime, which is measured as tokens per solved fix between arms A and B.

### 2026-10-10 (first live runs)

- Switched the model provider to the event's LiteLLM proxy (an OpenAI-compatible endpoint) with an adapter that converts the Anthropic-shaped requests and replies. The agent's own spend metering was checked against the proxy's per-request cost header: ratio 1.00 over the first four arm A runs.
- A hello trace read back from neatlogs through its MCP showed failed spans marked as successes and model-call spans with zero tokens. Both were fixed in the telemetry shim and the adapter, and checked live (error status, 22 input and 5 output tokens).
- Calibration runs (4 tasks, version v2): arm A solved 3 of 4 for $0.80 in total; arm B (graph context) solved 3 of 4 for $0.37. Both fail `sqlparse-772` at the turn limit, which makes it the benchmark's cost-overrun case. Four tasks are indicative only. Flat price from arm A: $0.3006 (mean cost $0.2004 x 1.5).
- Reading the first traces found two gaps in the shared core, fixed with a failing test first and then both arms re-run: tool errors leaked the absolute worktree path and Python internals, and `run_tests` named the failing tests without saying why. It now shows the assertion message.
- Reading the result found a bug in the price calibration: the smoke-test run was counted as a fifth calibration task (price $0.2437). The calibration now takes the manifest's calibration tasks only.

### 2026-10-10 (benchmark)

- Ran the three arms on the 12 evaluation tasks, one run per task, after freezing the shared core: arm A (whole files) solved 8 of 12 for $2.09; arm B (graph context) 11 of 12 for $1.20; arm C (graph context, quote, governor) 9 of 12 for $1.16 and billed $3.13 against $3.31 for B at the flat price. Graph context cut the cost of a solved fix by more than half; the quote and governor did not improve on plain graph context in this sample (`docs/notes/arm-c-evaluation.md`).
- The quote's band held the actual cost on 10 of 12 arm C runs, and 14 of 16 in a leave-one-out check on arm B. The one run the governor plausibly lost was `marshmallow-2249`, where the quote's upper band was below what the task needed.
- Kept the spec's governor thresholds: the early and late sweeps were not run (four calibration tasks cannot rank them, and the event's shared allowance was being spent), recorded in `docs/notes/tuning.md`.
- Injected a flaky test, a test timeout and an API overload into live runs and killed and resumed another; all four ended verified (`docs/evidence/failure-recovery.md`). The neatlogs read-back was returning 502 at the time, so those traces were not checked in the dashboard.
- Checked in the neatlogs dashboard: the four run tags and the span tree render; the proxy model is shown at $0 because neatlogs does not price it; the custom span attributes were not checked.
- Generated the results page, the receipts page (checked at 390px) and the business-plan inputs from the stored ledger. Spend so far: $7.32 of the event's $20 allowance.
- Entire Brain: seven durable facts written by hand with explicit categories (`entire brain remember --agent none --path ...`), so nothing was extracted from sessions and no model was called; they sit outside the repository, and `entire brain facts status` reports `authored=7 distilled=0`. Automatic extraction was left off because it would send session text, which holds the home path and old emails, to a model provider.

### 2026-10-11 (audit and arm D)

- Audited the 56 recorded runs ([`docs/notes/audit-2026-10-11.md`](docs/notes/audit-2026-10-11.md)): verified runs on arms B and C spent 18% of their cost after the fix had already verified; arm C's downgrade swapped in a weaker model and wiped the conversation, and three of its four failures followed one; 10 of 12 failures ran out of turns; the agent tried 11 times to write a debugging script it could not run.
- Built arm D test-first against those findings: a coach model (`claude-sonnet-4.6`) that writes a note when the run is stuck while the worker keeps its model and memory, a stop once the fix verifies, a `run_python` tool, and lessons built from 28 recorded runs ($0.31) and used leave-one-out. Arms A to C were not changed.
- Measured it on the same 12 evaluation tasks: 11 of 12 fixed for $1.17 ($0.107 per fix), margin +$2.68, against arm C's 9 of 12 and +$1.97. It fixed all three tasks C lost and lost one that every other arm fixed. One run per task and no ablation, so which change helped most is not known ([`docs/notes/arm-d-evaluation.md`](docs/notes/arm-d-evaluation.md)).

## Demo

Not available yet.

## Known limitations and next steps

- Live runs use the event's proxy models (`claude-haiku`, fallback `nova-2-lite`), not Sonnet 5.5, so solve rates and costs are specific to them. The Anthropic provider path has not been run live.
- Only the 4 calibration tasks have been run on both arms so far; the 12 evaluation tasks, arm C, quote accuracy, the failure-recovery runs and the cfo.ai plan are not finished. Four tasks say nothing yet about whether graph context or the quote helps.
- Whether the custom `margin.*` span attributes and the `arm:`/`version:` tags show in the neatlogs dashboard is not checked; spans were read back through the neatlogs MCP only.
- Network access is not blocked inside the test sandbox; the 16 tasks were verified to need none, and the sandbox's other limits are listed in `EVIDENCE.md`.
- Next: arm A, B and C on the 12 evaluation tasks, then the failure-recovery demo, the results page and the cfo.ai plan.

## Submission

- Requirements confirmed from the published page: use neatlogs, Entire and cfo.ai; public repo with commits dated during the event; before/after evidence; a run showing failure recovery; building in public tagged #neatHack; demo video; submission by quote-tweet.
- Open: team-size and conduct FAQ answers are not published on the page.
