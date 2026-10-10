# Addendum 3: run the agent on the event's LiteLLM proxy

**Why.** The live steps (smoke run, arms A, B and C) need model money, and `ANTHROPIC_API_KEY` is empty. neatHack gives each team a **$20 allowance** on a shared, OpenAI-compatible LiteLLM proxy with Claude and Nova models. This addendum lets `margin` use it as a second *provider*. The default stays `anthropic`, so nothing changes unless `MARGIN_PROVIDER=litellm` is set.

**Do this before Task 11's live smoke run and before any arm A run.** Arms A, B and C must all run on the same model, so the choice below is made once, up front.

## What was verified against the live proxy (2026-10-10, about $0.07 spent of the $20)

| Check | Result |
|---|---|
| Models exposed | `claude-haiku`, `claude-sonnet-4.6`, `claude-opus-4.6`, `nova-micro`, `nova-lite`, `nova-pro`, `nova-2-lite` |
| Prices (USD per million tokens, from the proxy's own `/model/info`) | `claude-haiku` 1.10 in / 5.50 out; `claude-sonnet-4.6` 3.30 / 16.50; `nova-2-lite` 0.33 / 2.75; `nova-lite` 0.06 / 0.24 |
| Two-turn tool-call round trip (call a tool, read its result, answer) | Correct on all six models tried, valid arguments every time |
| Through the real adapter and the real agent loop | `claude-haiku`, `claude-sonnet-4.6` and `nova-2-lite` answered correctly; `nova-lite` finished with an **empty answer** |
| Our metered cost vs the proxy's own per-call cost header | **Ratio 1.00** on all four models |
| Prompt caching | Works on Claude (a breakpoint on a tool result too): the second call read 9,127 tokens at about one twelfth of the first call's price. Works on Nova for the system prompt only; Nova **rejects** a breakpoint inside a tool result (400) |
| Output ceiling | Nova (micro, lite, pro) caps at 10,000 tokens; the Claude models and `nova-2-lite` allow 64,000 |
| Rate limit | **60 requests per minute per key** (response header), so runs must stay sequential |

The patch was applied to a copy of the repo at `5e0ace0`: the whole suite passes with 27 new tests, and `ruff check` is clean. Mocked-transport tests cover the conversion in both directions (tool calls, tool results, errors, cache markers, token accounting, stop reasons) over the real `openai` SDK.

**Not verified:** neatlogs' `openai` instrumentation against the live dashboard (Step 6 checks it), long runs (cost per real task is unknown until Step 5 measures it), and whether the shared allowance is also being spent by anything else on the team.

## Decision: which models

Use **`claude-haiku` as the main model and `nova-2-lite` as the downgrade fallback.** Reasons:

- `claude-sonnet-4.6` costs about three times as much per token as `claude-haiku`. The full benchmark is roughly 60 runs, and $20 will not cover it on Sonnet.
- `nova-lite` gave an empty answer in the live probe; `nova-2-lite` did not, and is still 3x to 17x cheaper than Haiku, so the governor's downgrade rung stays meaningful.
- The economics (quote, cap, margin) do not depend on the model, but the solve rate does: expect a lower solve rate than Sonnet 5.5 would give, and say so in `EVIDENCE.md`.

If Step 5 shows `claude-haiku` runs are too expensive for the remaining allowance, fall back to `nova-2-lite` as the main model for the whole benchmark. Never mix models across arms.

## Steps

- [ ] **Step 1: Apply the patch and run everything**

```bash
cd ~/Desktop/margin
git apply --check docs/superpowers/plans/addendum-3-litellm-provider.patch
git apply docs/superpowers/plans/addendum-3-litellm-provider.patch
uv add openai
uv run pytest && uv run ruff check src tests scripts
```

Expected: all tests pass and lint is clean. If `--check` fails because a file moved, use `git apply --reject` and place the hunks by hand (they are additive); the behaviour in the table above is the specification.

- [ ] **Step 2: Point `.env` at the proxy** (the key and URL are already there)

```bash
printf 'MARGIN_PROVIDER=litellm\nMARGIN_MAIN_MODEL=claude-haiku\nMARGIN_FALLBACK_MODEL=nova-2-lite\n' >> .env
```

Do not do this before Step 1: the older code would read the model names and try to send them to Anthropic.

- [ ] **Step 3: Run the live probe**

```bash
uv run python scripts/probe_litellm.py --models claude-haiku,nova-2-lite
```

Expected: both models `OK` with `ratio 1.00` between metered and proxy cost. Any model it flags "NOT in pricing.toml" must be added there (use the proxy's own rates from the table it prints) before it can be used.

- [ ] **Step 4: Commit**

```bash
git add src scripts tests pricing.toml .env.example pyproject.toml uv.lock docs/superpowers/plans/addendum-3-litellm-provider.*
git commit -m "feat: run the agent on the event's LiteLLM proxy as a second provider"
```

- [ ] **Step 5: Smoke run, then measure before committing to a benchmark**

```bash
uv run python scripts/make_smoke_repo.py
uv run margin run --tasks-file bench/cache/smoke.toml --task smoke-add --arm A --version v0
```

Read the receipt. Then run the four arm A calibration tasks and read what one *real* run costs:

```bash
uv run margin bench --arm A --split calibration --version v1
```

Compute the budget: `(mean cost per run) x (about 60 runs)` must fit inside the allowance left after the probes and smoke runs, with margin to spare. Set `MARGIN_BENCH_BUDGET_USD` to no more than that remaining amount. The spend so far is the sum of `cost_usd` in `runs/ledger.jsonl`, and each run's event log also records a `proxy_cost` event with the proxy's own figure next to ours.

- [ ] **Step 6: Check the traces**

With `MARGIN_PROVIDER=litellm`, neatlogs instruments the `openai` SDK instead of `anthropic`. Open one real run in the dashboard and confirm the LLM spans show model, tokens and latency. If they do not, record that in `docs/notes/neatlogs-findings.md` and keep the WORKFLOW, AGENT, TOOL and GUARDRAIL spans as the trace evidence (our own ledger carries the cost).

- [ ] **Step 7: Document it honestly**

- `EVIDENCE.md` under **Known limits**: "The benchmark ran on the event's shared LiteLLM proxy (`claude-haiku` as the main model, `nova-2-lite` as the downgrade fallback), not on Sonnet 5.5, so solve rates are not comparable with an Anthropic-direct run. Prices are the proxy's own, and our metered cost matched the proxy's per-call accounting."
- `hackathon.md`: update the Stack line (provider, models) and add a dated build-log entry with the real per-run cost.
- `docs/business/` (cfo.ai inputs): note that the unit costs were measured on these models; a production price would use whichever model the customer chooses.

## Things to remember while running

- **Sequential only.** 60 requests per minute per key. `margin bench` is sequential; do not run several in parallel.
- **The allowance is one shared pot ($20).** There is no endpoint to read what is left (`/key/info` is 404), so track it from the ledger.
- **`effort` and `thinking` settings do nothing on this provider.** The adapter drops them; Haiku 4.5 here is not run with adaptive thinking.
- **Nova rejects a cache breakpoint inside a tool result**, which is why the moving breakpoint is Claude-only. If a request to a Nova model returns 400 mentioning `cachePoint`, that is the cause.
- **The key never goes into chat, logs or screenshots.** If a screenshot of the event's model-access page is needed, crop out the verified email, and do not paste it into this session: Entire does not redact images.
