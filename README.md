# Margin

An issue-fixing agent that knows what it costs: it **quotes** a price band before it works, **governs** its own spend while it works, and **proves** its margin afterwards.

You give it a repository, a commit and an issue. It quotes a cost band learned from its own past runs, fixes the issue with a hard spending cap, and the result is judged by the repository's tests: it counts only if the target tests pass and nothing that passed before now fails. Revenue is the quoted price if the fix is verified and zero otherwise, so a failed run is a visible loss, which is why the governor matters.

Built for neatHack. **Status:** the pipeline is implemented and tested offline; the benchmark runs that produce the published numbers have not been generated yet. See [`hackathon.md`](hackathon.md) for the build log and [`docs/superpowers/specs/2026-10-10-margin-design.md`](docs/superpowers/specs/2026-10-10-margin-design.md) for the design.

Uses [neatlogs](https://neatlogs.com) (traces), [Entire](https://entire.io) (checkpoints and entire-graph) and [cfo.ai](https://cfo.ai) (business plan).

## Setup

```bash
uv sync                                  # Python 3.12 is pinned (neatlogs supports 3.10 to 3.13)
cp .env.example .env                     # only if you have no .env yet; then fill in the keys
entire enable --agent claude-code        # record build sessions as Entire checkpoints
```

`.env` needs `ANTHROPIC_API_KEY` and `NEATLOGS_API_KEY` (the neatlogs **project** key from Settings, API keys; not the `nlw_` ingest key). Never commit it. Without a neatlogs key every trace call is a no-op, so tests and dry runs need no network.

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

- [`EVIDENCE.md`](EVIDENCE.md): every claim, linked to something you can open (in progress)
- [`docs/results.md`](docs/results.md) and [`docs/receipts.html`](docs/receipts.html): generated from `docs/evidence/ledger.jsonl`
- [`docs/business/`](docs/business/): the cfo.ai plan and the measured numbers it was built from
- [`docs/notes/task-curation.md`](docs/notes/task-curation.md): how the 16 benchmark tasks were chosen
- [`docs/superpowers/plans/`](docs/superpowers/plans/): the implementation plan
