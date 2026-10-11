# Evidence

Every claim below links to something a judge can open. Numbers come from `docs/evidence/ledger.jsonl`;
run `make verify` to regenerate `docs/results.md` from it and fail if it differs.

> **Status.** Every link on this page opens. The posts under "You built in public" are listed in
> [`docs/evidence/posts.md`](docs/evidence/posts.md) as the builder publishes them.
> `tests/test_evidence.py` refuses any leftover placeholder.

## The agent improved
- Before and after, 12 evaluation tasks: [`docs/results.md`](docs/results.md).
- Same task, `marshmallow-2900`: arm A (naive, flat price) run `marshmallow-2900-A-20261010-145224-b903` ended not verified at $0.23; arm C (quote, cap, graph context) run `marshmallow-2900-C-20261010-183320-b1c6` verified at $0.14. Screenshots of the two traces in neatlogs: [arm A](docs/evidence/trace-arm-a.jpg) and [arm C](docs/evidence/trace-arm-c.jpg). The first model call carries 33,582 tokens in arm A (whole files as context) and 2,916 in arm C (graph context).
- What changed between them: graph context for the agent, then the quote and the governor, built in the session the checkpoint below records (its Sessions and Changes views); the measured effect and where it did not help are in [`docs/notes/arm-c-evaluation.md`](docs/notes/arm-c-evaluation.md).
- How the 12 evaluation tasks (and 4 calibration tasks) were chosen, and which candidates were rejected and why: [`docs/notes/task-curation.md`](docs/notes/task-curation.md).

- A fourth version built after an audit of the 56 recorded runs ([`docs/notes/audit-2026-10-11.md`](docs/notes/audit-2026-10-11.md)): arm D, with a coach model that writes a note when the run is stuck, a stop once the fix verifies, a `run_python` tool and lessons learned from other tasks. It fixed 11 of 12 at $0.107 per fix with a margin of +$2.68, against arm C's 9 of 12 and +$1.97 ([`docs/notes/arm-d-evaluation.md`](docs/notes/arm-d-evaluation.md), including what it does not show).

- A fifth version, arm E, hands three decisions in arm D to TypeSafe's Jev (an intake gate, a per-turn progress judge, a lesson picker). It matched arm D, 11 of 12 at $0.108 per fix, with about 30% less spent on coaching and under one cent of Jev for all 12 jobs ([`docs/notes/arm-e-evaluation.md`](docs/notes/arm-e-evaluation.md)).

## You used neatlogs
- Traces tagged `arm:A`, `arm:B`, `arm:C`: [screenshot of the trace list](docs/evidence/trace-list.jpg): 64 traces in the window, the newest 25 shown. Each trace carries four tags (`arm:`, `task:`, `split:`, `version:`), visible on its trace page. The red "Execution Failed" badges mark failed calls that were retried or recovered: the test-timeout demo (1), the API-overload demo (2) and a real API timeout on `mistune-420`.
- Span kinds used: WORKFLOW, AGENT, TOOL, GUARDRAIL (governor, verifier, recoveries), plus LLM spans with tokens and cost.

## You used Entire
- Checkpoint link: https://entire.io/gh/JemIIahh/margin/commit/5ad9776bfaa59fb58de2c6bb05778623b56fd78d (id `01M4KJFZ9SS3FGZ96RS2AERSE8`, commit `5ad9776`).
- Local checkpoints for every commit, and the state of the privacy review: [`docs/evidence/checkpoints.md`](docs/evidence/checkpoints.md).
- entire-graph at runtime for search and impact (arms B and C). Its report over the build sessions is in [`docs/evidence/graph-stats.txt`](docs/evidence/graph-stats.txt); note that it covers the *build* sessions, which barely used the graph, so it shows about zero savings. The effect of graph context on Margin's agent is measured as tokens per solved fix, arm A versus arm B, in `docs/results.md`.

## You used TypeSafe (Jev)
- An intake gate screens each issue before any money is spent: on held-out items it accepted 12 of 12 genuine issues and declined
  6 of 6 with a planted instruction to the agent and 4 of 4 vague ones ([`docs/evidence/intake.md`](docs/evidence/intake.md)), with
  thresholds checked on calibration items first ([`docs/notes/intake-calibration.md`](docs/notes/intake-calibration.md)).
- A progress judge decides when the coach steps in; its one useful question was found by replaying it on recorded calibration runs
  ([`docs/notes/judge-calibration.md`](docs/notes/judge-calibration.md)).

## You used cfo.ai
- Business plan covering pricing, costs, revenue and runway: [`docs/business/`](docs/business/) (exports: [`cfo-pricing.xlsx`](docs/business/cfo-pricing.xlsx), [`cfo-revenue-and-margin.xlsx`](docs/business/cfo-revenue-and-margin.xlsx), [`cfo-cash-and-runway.xlsx`](docs/business/cfo-cash-and-runway.xlsx), [`cfo-scenarios.xlsx`](docs/business/cfo-scenarios.xlsx); summary in [`README.md`](docs/business/README.md)).
- Measured inputs it was built from: [`docs/business/inputs.md`](docs/business/inputs.md).

## The agent recovers from failures
- Injected overload, test timeout and flaky test, each followed by recovery: [`docs/evidence/failure-recovery.md`](docs/evidence/failure-recovery.md).
- A run killed mid-flight and resumed from its checkpoint: [screenshot of the resumed trace](docs/evidence/trace-resume.jpg) (`tomlkit-619`, run `demo-resume-184535`). The run was killed with `kill -9` after its second model call; the trace starts at `turn-2` because turns 0 and 1 ran in the process that was killed, and it carries a fifth tag, `resumed:true`. The ledger cost covers all 30 model calls, before and after the kill ([`docs/evidence/failure-recovery.md`](docs/evidence/failure-recovery.md)).
- Offline tests of each recovery path, and of resume, are in `tests/test_faults.py` and `tests/test_resume.py`.

## You built in public
- Posts tagged #neatHack: [`docs/evidence/posts.md`](docs/evidence/posts.md).

## You wrote the code during the hackathon
- Public repository with dated commits: https://github.com/JemIIahh/margin/commits/main (first commit 2026-10-10).

## Known limits
- Arm E, like every arm, was run once per task. A second run of arms D and E, and runs of an unprotected agent on the injected issues, were planned and not made, to keep the event allowance for the demo. Issue text and short run digests are sent to TypeSafe when arm E or the gate runs; the injected issues are templates we wrote, so the gate's detection is an upper bound.
- Arm D was measured after the benchmark, on later code (from commit `cfa2362`), with its four changes together (no ablation) and one run per task. Its lessons were written from the arm A to C runs of other tasks in the same repositories and are used leave-one-out; building them cost $0.31, which is not in any run's cost.
- The target tests are visible to the agent. The tools refuse writes to test files and test infrastructure (`conftest.py`, pytest, tox and setup config, `sitecustomize.py`, `.pth` files, anything under a `tests` directory, and any module or package named `pytest`, `_pytest` or `pluggy`), and before judging every change to those paths is reverted, so editing or adding tests cannot change the verdict; the ledger records which test paths the agent touched. A test that passed at the base commit and is now skipped or missing counts as a regression. A fix that legitimately needs to change a config file such as `pyproject.toml` could not be judged solved; none of the 16 tasks does.
- The governor's check before each call uses an optimistic estimate of that call (warm-cache prompt reads plus the expected output), so one call can carry spend slightly past the cap; receipts show the actual cost.
- Runs that fail for infrastructure reasons (the API after retries, a harness error) are recorded with `infra_error` and excluded from every reported number; their spend still counts against the batch budget guard.
- A resumed run re-extracts its graph features from the already-modified worktree and may replay the tool calls of the turn that was in flight when it was killed.
- Test code runs as the same OS user as the harness. File tools are confined to the worktree, host-side git is hardened and tamper-checked, and subprocess environments carry no keys, but there is no OS-level isolation: a deliberately malicious test could still reach the network or read other user-owned files (on macOS, for example, via `ps`). The tasks were chosen from well-known repositories at pinned commits, and the agent only runs code in those repositories. For the chosen tasks specifically, the baseline and fix runs were repeated with the network denied at the OS level and all 16 still passed.
- Issue text is untrusted input. The agent has no shell and its file tools are confined, but nothing screens the issue text itself for instructions aimed at the agent.
- 16 tasks is a small sample, and most are small single-function fixes: treat percentages as indicative, and see the per-task table for every run.
- The tasks were selected by the build agent from mined candidates, with every rejected candidate recorded; selection was not blind to difficulty.
- Model prices come from `pricing.toml`, checked on 2026-10-10.
- The agent runs on the event's LiteLLM proxy models (`claude-haiku`, fallback `nova-2-lite`), not on Sonnet 5.5. Solve rates and costs describe those models and are not comparable with a Sonnet 5.5 run.
- Quote accuracy is reported out of sample (leave-one-out), including the misses.
- Before a fix is judged, a check confirms that pytest and its dependencies load from the virtual environment and not from the worktree (a file written at the repository root named like one of them would otherwise replace the runner and write its own results); a worktree that shadows them is judged not solved. A fresh-context review found this gap after the benchmark had run; no recorded run was affected, and the check was then validated on all 16 tasks' real fixes.
- Every benchmark and demo run was made with the source as of commit `73da1d0` (`src/` did not change between that commit and the last run). Three later source commits were not re-measured: `f6ccac0` (report and receipts formatting), `e35c9d0` (review fixes: a pytest-shadowing guard, a baseline failure now leaves a row, API timeouts counted, no run path in tool errors) and `a7c63c1` (smaller fixes: a null optional tool argument means "not given", `--only-missing` per version, budget guard counts a killed run, receipts for flat-priced arms, `quote` cleans up, corrupt checkpoint error). Only the null-argument change can alter what an agent run does, and only by accepting a call that was previously answered with an error.
- Every number here comes from ledger rows produced by the live agent, which is `claude-haiku` through the event's proxy, one run per task per arm. The pipeline's other behaviour (retries, faults, resume) is also exercised offline with scripted model replies.
- Three runs hit a client-side model-call timeout (`sqlparse-772` on arm A, `tabulate-305` on arm B, `mistune-420` on arm C). The abandoned request may have been billed by the provider but is not in our cost, so those costs are lower bounds; `docs/results.md` lists the two evaluation runs. The proxy-versus-metered comparison (60 of the 61 local runs with a proxy cost header match our metered cost within $0.0005; the one exception is the resumed demo run, whose proxy client only saw the calls after the resume) cannot see this case.
- The published ledger also holds rows that are not benchmark results and are excluded from every table: four early calibration rows with cost 0 (the model call failed before the proxy key was set, marked `infra_error`), the fault-injection and resume demo runs (`version:demo-*`), and the smoke-test run. The flat price is computed from the manifest's four calibration tasks only.
- The business plan's volumes, fixed costs and starting cash are the builder's assumptions, labelled as such in `docs/business/assumptions.md`.
