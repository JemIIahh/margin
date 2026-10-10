# neatHack build log

## Project

- **Name:** Margin
- **Purpose:** An issue-fixing agent that quotes a price band before it works, enforces a budget while it works, and reports its margin afterwards.
- **Problem:** Agent cost per task is volatile, so agent work is hard to price. Margin makes cost a control signal and measures the result.

## Team

Solo. Registered team name: Sofer.

## Stack

- Python 3.12 (via uv), Anthropic SDK (`claude-sonnet-5-5`, `claude-haiku-5-5`)
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

## Demo

Not available yet.

## Known limitations and next steps

- No live model call has been made yet. The Anthropic request shape was checked against the installed SDK, but real behaviour, the neatlogs span rendering and the cost of a run are unmeasured.
- The benchmark has not been run: arms A, B and C, the quote coverage, the failure-recovery runs and the cfo.ai plan all wait on API keys and on the builder's cfo.ai account.
- Network access is not blocked inside the test sandbox; the 16 tasks were verified to need none, and the sandbox's other limits are listed in `EVIDENCE.md`.
- Next: put the two API keys in `.env`, run arm A on the calibration tasks, then B, then C (see the plan).

## Submission

- Requirements confirmed from the published page: use neatlogs, Entire and cfo.ai; public repo with commits dated during the event; before/after evidence; a run showing failure recovery; building in public tagged #neatHack; demo video; submission by quote-tweet.
- Open: team-size and conduct FAQ answers are not published on the page.
