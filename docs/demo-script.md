# Demo script (about three minutes)

**Status: numbers filled from the live runs; links and the cfo.ai figures are still blank (`[ ... ]`).** Record the video only after
`make verify` passes, and watch it once with the sound off to confirm every on-screen step is readable. It must name all three
tools: neatlogs, Entire and cfo.ai. Say plainly that the model is `claude-haiku` through the event's proxy and that this is 12
tasks with one run each.

## 0:00 to 0:30, the problem
- One sentence: agents are hard to price, because the cost of a task varies wildly and a failed run still costs money.
- Show the arm A receipts: the same agent spent $0.06 on `moreitertools-1308` and $0.30 on `sqlparse-826`, and the second one was
  **not verified**, so a flat $0.30 price would have billed nothing for $0.30 of spend (arm A: 8 of 12 verified, gross margin 13%).

## 0:30 to 1:30, the product
- `uv run margin quote --task tabulate-241`: the cost band $0.07 to $0.45 (p50 $0.17) from 15 past runs, price $0.67.
- `uv run margin run --task tabulate-241 --arm C`, live or recorded: quote, hard cap, fix, verify. The recorded run verified at $0.13,
  margin +$0.54.
- A fault, then the recovery: `MARGIN_FAULT=tool_timeout uv run margin run --task moreitertools-1308 --arm C --version demo-fault-timeout`
  (tests time out, the run falls back to the target tests and still verifies; `docs/evidence/failure-recovery.md`).
- The governor acting with its stated reason: `marshmallow-2249`, DOWNGRADE at turn 16 ("no progress at 67% of the cap"), NARROW at
  turn 29; it ended not verified at $0.13 and billed nothing. Say that the governor did not win here (the quote's upper band, $0.15,
  was below the $0.17 the task needed) and show the receipt and `docs/receipts.html`.
- The kill and resume: `scripts/resume_demo.sh tomlkit-619 C` (killed after its first checkpoint, resumed, verified, spend counted once).

## 1:30 to 2:15, neatlogs and Entire
- neatlogs: one run's trace (`margin.run` with `turn-N`, `claude-haiku` and tool spans, 91 steps for `sqlparse-772` on arm B) and its four tags
  `arm:`, `task:`, `split:`, `version:` [ link or screenshot ]; the `failed:*` then `recovery:*` spans of a fault run [ link ].
  The dashboard's own cost column reads $0 for the proxy model; the cost story is the ledger and the receipts.
- Entire: the checkpoint page, Sessions then Changes [ link ]; entire-graph at runtime, and the measured result, arm A versus arm B:
  cost per solved fix $0.26 against $0.11, mean tokens per solved fix 836,552 against 336,605 (`docs/results.md`). Do not present
  `docs/evidence/graph-stats.txt` as a savings figure: it covers the build sessions, not the agent.

## 2:15 to 3:00, cfo.ai and the close
- The cfo.ai plan: price [ $ ], margin [ % ] and runway [ months ], built from the measured arm C numbers: median cost $0.09,
  90th percentile $0.14, verified on 75% of jobs, $0.13 per verified fix (`docs/business/inputs.md`; arm B was better on every one of those).
- `make verify` passing; the repository link; the checkpoint link and id.
