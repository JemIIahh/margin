# Demo script (about three minutes)

**The story:** agents are hard to price; an audit of our own runs found where the money went; a coach, a cheap judge (TypeSafe's Jev) and
a stop rule fixed it; every job ends with a receipt that proves the cost. Name all four tools on screen: neatlogs, Entire, cfo.ai and
TypeSafe. Say once that this is 12 real issues with one run each, on the event's `claude-haiku`.

## Before recording

- **Budget:** the only live model spend is one short arm E run (about $0.03 per take) and a few Jev calls (about $0.0001 each). Ten takes
  stay under $0.50. `margin quote` and everything shown from files or the web is free.
- **Privacy:** run the terminal full screen with a plain prompt (`export PS1='$ '`), keep `.env` closed, collapse the neatlogs sidebar
  (your name is in it), and use full-screen browser windows so tabs and addresses do not show.
- **Warm-up:** run `uv run margin intake --task sqlparse-826` once before recording; the first Jev call of the day can take about 10 seconds.
- Run `make verify` first; it should print `385 passed` and `docs/results.md is up to date`.

## 0:00 to 0:25, the problem

Show the README's opening and its results table.

> "AI agents can fix real bugs, but nobody can price that work. In our benchmark the same naive agent spent 6 cents on one issue and 30 on
> another, and the 4 issues it failed still cost money. Margin quotes a price before the work, controls spend during it, and only bills
> when the repository's own tests prove the fix."

## 0:25 to 1:10, the product, live

```bash
uv run margin intake --task sqlparse-826                              # gate: accept (injection about 0.09, actionable about 0.97)
uv run margin intake --task moreitertools-1308 --variant inj-10       # same issue with a planted instruction to the agent: decline (injection about 0.98)
uv run margin quote --task tabulate-241                               # cost band $0.0668 - $0.4451 (p50 $0.1724) from 15 past runs; price $0.6677
MARGIN_COACH_MODEL=claude-sonnet-4.6 uv run margin run --task moreitertools-1308 --arm E --version demo-video   # about 70 s, about $0.03
cat runs/<the run id it prints>/receipt.md                           # the run prints this path for you
```

> "TypeSafe's Jev screens the issue, for a fraction of a cent, before the agent spends anything, and blocks one that tries to instruct the agent. The quote comes from past
> jobs. The run is capped, the tests decide, and the receipt shows the price, the cost and the margin."

The `--version demo-video` tag keeps these takes out of the benchmark numbers. The run prints the receipt's path relative to the
repository (`receipt: runs/.../receipt.md`), so no line shows your macOS user name.

## 1:10 to 1:55, how it got better

Show `docs/notes/audit-2026-10-11.md` (findings 1 and 2), then this recorded arm E receipt:

```bash
cat runs/sqlparse-826-E-20261011-074735-d39c/receipt.md
```

It reads: quoted band $0.0504 to $0.3357, price $0.5035, cost $0.1567, **verified**, margin $0.3468, and two coach decisions, the first
"Jev judged the run stuck: ... ready_to_edit 0.2".

> "We audited 56 of our own runs. Agents kept spending after the fix had passed, and our governor made stuck agents weaker by switching to
> a cheaper model. So now the run stops once the tests prove the fix, and when Jev judges that the agent does not know what to change, a
> stronger coach writes it a note. On this issue the naive agent and our first governed agent both failed; this run was coached at turn 8
> and verified."

Then the results table in `docs/results.md`: naive agent 8 of 12 at $0.261 per fix and 13% gross margin; arms D and E 11 of 12 at
$0.107 and $0.108, about 70%. Spend after a verified fix fell from 18% to 5%.

## 1:55 to 2:30, the proof: neatlogs and Entire

- **neatlogs:** the trace list with the red "Execution Failed" rows (`docs/evidence/trace-list.jpg`), the arm A and arm C traces of the same
  issue side by side (33,582 against 2,916 tokens in the first call), and the resumed run that starts at `turn-2` after a `kill -9`.
- **Entire:** the public checkpoint page,
  https://entire.io/gh/JemIIahh/margin/commit/5ad9776bfaa59fb58de2c6bb05778623b56fd78d, and one line: entire-graph is the agent's code
  search, which is where the 91% token saving comes from.

> "Every turn, tool call, governor decision and recovery is a trace in neatlogs. The build itself is recorded in Entire."

## 2:30 to 3:00, the business and the close

Show `docs/business/README.md`:

> "We built the plan in cfo.ai from the measured costs. At 34 cents per verified fix the gross margin is 59%, but at a thousand jobs a month
> it does not yet cover fixed costs; at 60 cents it is 75% and profitable. Every number in this video is regenerated from the stored ledger
> by `make verify`, and every claim is linked in EVIDENCE.md."

End on the repository: https://github.com/JemIIahh/margin

## After recording

Watch it once with the sound off to check every step is readable, check no frame shows your name, tabs, address bar or `.env`, then send
the video link for the submission text.
