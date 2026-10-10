# Demo script (about three minutes)

**Status: outline.** The structure and commands are final; every `[ ... ]` is a number, id or timestamp to fill in after
the benchmark has run and the demo has been rehearsed. Record the video only after `make verify` passes, and watch it once
with the sound off to confirm every on-screen step is readable. It must name all three tools: neatlogs, Entire and cfo.ai.

## 0:00 to 0:30, the problem
- One sentence: agents are hard to price, because the cost of a task varies wildly and a failed run still costs money.
- Show an arm A receipt for a task it lost money on: cost [ $ ] against the flat price [ $ ], not verified.

## 0:30 to 1:30, the product
- `uv run margin quote --task [task id]`: the cost band, from [ n ] past runs, and the price.
- `uv run margin run --task [task id] --arm C`, live or recorded: quote, hard cap, fix, verify.
- A fault, then the recovery: `MARGIN_FAULT=tool_timeout uv run margin run --task [task id] --arm C --version demo-fault-timeout`.
- The governor acting, with its stated reason (downgrade, narrow or abort), then the receipt and `docs/receipts.html`.

## 1:30 to 2:15, neatlogs and Entire
- neatlogs: the `v1` (arm A) and `v2` (arm C) traces side by side with their cost and token numbers [ link ]; the failing trace
  read through the neatlogs MCP and the fix it led to; the `failed:*` then `recovery:*` spans.
- Entire: the checkpoint page, Sessions then Changes [ link ]; entire-graph at runtime, and the measured tokens per solved
  fix, arm A versus arm B [ numbers from `docs/results.md` ]. Do not present `docs/evidence/graph-stats.txt` as a savings
  figure: it covers the build sessions, not the agent.

## 2:15 to 3:00, cfo.ai and the close
- The cfo.ai plan: price [ $ ], margin [ % ] and runway [ months ], built from the measured p50 [ $ ] and p90 [ $ ] (`docs/business/`).
- `make verify` passing; the repository link; the checkpoint link and id.
