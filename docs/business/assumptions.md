# Assumptions behind the business plan

**Everything in this file is the builder's assumption, not a measurement.** The measured unit economics are in
[`inputs.md`](inputs.md) and come from the benchmark ledger (`docs/results.md`).

## Measured (arm C, the full product, 12 evaluation tasks, one run each)
- Cost per job: median $0.09, 90th percentile $0.14. Solve rate 75%. Cost per verified fix $0.13.
- Average quoted price $0.34 **per verified fix**, charged only when the fix verifies: about $0.26 per job attempted.
- Arm B (graph context, flat price, no quote or governor) measured better on cost and solve rate: 92%, $0.11 per verified fix,
  64% gross margin against 63% for C. The plan uses C because it is the product that quotes a band; the margins are nearly equal.

## Assumed (answers given to cfo.ai, 2026-10-10)
| Item | Assumption |
|---|---|
| Jobs per month, base | 1,000, flat |
| Jobs per month, growth | 1,000 in month 1, growing 25% a month for 12 months |
| Hosting | $40 per month (estimate) |
| Observability | $50 per month (estimate) |
| Tooling and miscellaneous | $30 per month (estimate) |
| Payment processing | about 3% of revenue, billed monthly so there is no per-job fixed fee |
| Accounting, legal, miscellaneous | $50 per month |
| Salaries | none (solo founder, $0 pay) |
| Starting cash | $3,000 as of 2026-10-10 (illustrative, not a real balance) |
| Price points tested | $0.34 and $0.60 per verified fix |
| Volume at the higher price | 15% fewer jobs at $0.60 than at $0.34 |
| Founder salary (comparison only) | runway also shown with $2,000 a month; the main case has none |
| Raise | none, committed or planned |
| Quote band | the measured quoted prices ($0.18 to $0.67, average $0.34) |

## Caveats
- The benchmark jobs are small fixes to open-source issues made by a cheap model (`claude-haiku` through the event's proxy). Real
  customer issues are larger and a larger model costs more per job, so $0.34 per fix is a floor, not a forecast.
- There are no customers and no real volumes yet. Twelve evaluation tasks with one run each is a small sample.
- Fixed-cost figures are estimates; the real prices of the services were not looked up.
