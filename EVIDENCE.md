# Evidence

Every claim below links to something a judge can open. Numbers come from `docs/evidence/ledger.jsonl`;
run `make verify` to regenerate `docs/results.md` from it and fail if it differs.

> **Draft.** Entries still written as `{{...}}` are artifacts that do not exist yet (traces, the published checkpoint,
> the cfo.ai plan). They are filled in as the live benchmark and the publication steps are done, and
> `tests/test_evidence.py` (added when they are all filled) refuses any leftover.

## The agent improved
- Before and after, 12 evaluation tasks: [`docs/results.md`](docs/results.md).
- Same task, arm A (naive, flat price) and arm C (quote, cap, graph context): trace {{TRACE_URL_A}} versus trace {{TRACE_URL_C}}.
- What changed between them, with checkpoints: {{CHECKPOINT_LINK_FIXES}}.
- How the 12 evaluation tasks (and 4 calibration tasks) were chosen, and which candidates were rejected and why: [`docs/notes/task-curation.md`](docs/notes/task-curation.md).

## You used neatlogs
- Traces tagged `arm:A`, `arm:B`, `arm:C`: {{NEATLOGS_TRACE_LIST_URL_OR_SCREENSHOT_PATH}}.
- Span kinds used: WORKFLOW, AGENT, TOOL, GUARDRAIL (governor, verifier, recoveries), plus LLM spans with tokens and cost.

## You used Entire
- Checkpoint link: {{CHECKPOINT_URL}} (id {{CHECKPOINT_ID}}).
- Local checkpoints for every commit, and the state of the privacy review: [`docs/evidence/checkpoints.md`](docs/evidence/checkpoints.md).
- entire-graph at runtime for search and impact (arms B and C). Its report over the build sessions is in [`docs/evidence/graph-stats.txt`](docs/evidence/graph-stats.txt); note that it covers the *build* sessions, which barely used the graph, so it shows about zero savings. The effect of graph context on Margin's agent is measured as tokens per solved fix, arm A versus arm B, in `docs/results.md`.

## You used cfo.ai
- Business plan covering pricing, costs, revenue and runway: [`docs/business/`](docs/business/) ({{CFO_PLAN_FILE}}).
- Measured inputs it was built from: [`docs/business/inputs.md`](docs/business/inputs.md).

## The agent recovers from failures
- Injected overload, test timeout and flaky test, each followed by recovery: [`docs/evidence/failure-recovery.md`](docs/evidence/failure-recovery.md).
- A run killed mid-flight and resumed from its checkpoint: {{RESUME_TRACE_URL}}.
- Offline tests of each recovery path, and of resume, are in `tests/test_faults.py` and `tests/test_resume.py`.

## You built in public
- Posts tagged #neatHack: [`docs/evidence/posts.md`](docs/evidence/posts.md).

## You wrote the code during the hackathon
- Public repository with dated commits: https://github.com/JemIIahh/margin/commits/main (first commit 2026-10-10).

## Known limits
- The target tests are visible to the agent. The tools refuse writes to test files and test infrastructure (`conftest.py`, pytest, tox and setup config, `sitecustomize.py`, `.pth` files, anything under a `tests` directory), and before judging every change to those paths is reverted, so editing or adding tests cannot change the verdict; the ledger records which test paths the agent touched. A test that passed at the base commit and is now skipped or missing counts as a regression. A fix that legitimately needs to change a config file such as `pyproject.toml` could not be judged solved; none of the 16 tasks does.
- The governor's check before each call uses an optimistic estimate of that call (warm-cache prompt reads plus the expected output), so one call can carry spend slightly past the cap; receipts show the actual cost.
- Runs that fail for infrastructure reasons (the API after retries, a harness error) are recorded with `infra_error` and excluded from every reported number; their spend still counts against the batch budget guard.
- A resumed run re-extracts its graph features from the already-modified worktree and may replay the tool calls of the turn that was in flight when it was killed.
- Test code runs as the same OS user as the harness. File tools are confined to the worktree, host-side git is hardened and tamper-checked, and subprocess environments carry no keys, but there is no OS-level isolation: a deliberately malicious test could still reach the network or read other user-owned files (on macOS, for example, via `ps`). The tasks were chosen from well-known repositories at pinned commits, and the agent only runs code in those repositories. For the chosen tasks specifically, the baseline and fix runs were repeated with the network denied at the OS level and all 16 still passed.
- Issue text is untrusted input. The agent has no shell and its file tools are confined, but nothing screens the issue text itself for instructions aimed at the agent.
- 16 tasks is a small sample, and most are small single-function fixes: treat percentages as indicative, and see the per-task table for every run.
- The tasks were selected by the build agent from mined candidates, with every rejected candidate recorded; selection was not blind to difficulty.
- Model prices come from `pricing.toml`, checked on 2026-10-10.
- Quote accuracy is reported out of sample (leave-one-out), including the misses.
- Until the benchmark is run, no result in this file is a measurement of the live agent: the pipeline is verified offline with scripted model replies.
- The business plan's volumes, fixed costs and starting cash are the builder's assumptions, labelled as such in `docs/business/assumptions.md`.
