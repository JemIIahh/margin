# Margin

An issue-fixing agent that knows what it costs: it **quotes** a price band before it works, **governs** its own spend while it works, and **proves** its margin afterwards.

You give it a repository, a commit and an issue. It quotes a cost band learned from its own past runs, fixes the issue with a hard spending cap, and the result is judged by the repository's tests: it counts only if the target tests pass and nothing that passed before now fails. Revenue is the quoted price if the fix is verified and zero otherwise, so a failed run is a visible loss, which is why the governor matters.

Built for neatHack. **Status:** implemented, tested (283 tests) and benchmarked on 16 real GitHub issues (4 calibration, 12 evaluation, one run per task per arm, model `claude-haiku` through the event's LiteLLM proxy). Headline, from [`docs/results.md`](docs/results.md): entire-graph context cut the cost of a solved fix from $0.26 (arm A) to $0.11 (arm B) and $0.13 (arm C); the quote and governor did **not** beat plain graph context in this sample (9 against 11 of 12 solved), and `docs/notes/arm-c-evaluation.md` says where and why. See [`hackathon.md`](hackathon.md) for the build log and [`docs/superpowers/specs/2026-10-10-margin-design.md`](docs/superpowers/specs/2026-10-10-margin-design.md) for the design.

Uses [neatlogs](https://neatlogs.com) (traces), [Entire](https://entire.io) (checkpoints and entire-graph) and [cfo.ai](https://cfo.ai) (business plan).

## Setup

```bash
uv sync                                  # Python 3.12 is pinned (neatlogs supports 3.10 to 3.13)
cp .env.example .env                     # only if you have no .env yet; then fill in the keys
entire enable --agent claude-code        # record build sessions as Entire checkpoints
```

`.env` needs `NEATLOGS_API_KEY` (the neatlogs **project** key from Settings, API keys; not the `nlw_` ingest key) and one model provider: either `ANTHROPIC_API_KEY` (the default), or `MARGIN_PROVIDER=litellm` with `LITELLM_API_KEY` and `LITELLM_BASE_URL` (an OpenAI-compatible proxy), with `MARGIN_MAIN_MODEL` and `MARGIN_FALLBACK_MODEL` set to names that provider serves. Never commit `.env`. Without a neatlogs key every trace call is a no-op, so tests and offline runs need no key. A benchmark batch stops when the whole ledger's spend reaches `MARGIN_BENCH_BUDGET_USD`.

## Run

```bash
uv run margin tasks validate                                   # check the 16 benchmark tasks are usable
uv run margin quote --task cachetools-423                      # the price band for a task, without running the agent
uv run margin run --task cachetools-423 --arm C                # one task: quote, cap, fix, verify, receipt
uv run margin bench --arm C --split evaluation --version v2    # one arm over the evaluation tasks
```

Arms: **A** naive (whole-file context, flat price, no governor), **B** A plus entire-graph context and the baseline-aware verifier, **C** B plus the quote and the governor. Every run writes `runs/<id>/receipt.md` and appends a row to `runs/ledger.jsonl`.

## Verify

```bash
make verify          # runs the tests, then regenerates docs/results.md from the stored ledger and fails if it differs
```

## Where things are

- [`EVIDENCE.md`](EVIDENCE.md): every claim, linked to something you can open 
- [`docs/results.md`](docs/results.md) and [`docs/receipts.html`](docs/receipts.html): generated from `docs/evidence/ledger.jsonl`
- [`docs/business/`](docs/business/): the cfo.ai plan and the measured numbers it was built from
- [`docs/notes/task-curation.md`](docs/notes/task-curation.md): how the 16 benchmark tasks were chosen
- [`docs/superpowers/plans/`](docs/superpowers/plans/): the implementation plan
