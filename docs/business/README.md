# Business plan (built in cfo.ai from the measured numbers)

Margin charges per **verified fix**: the customer sees a quote band before the job, and pays the quoted price only if the repository's own
tests pass afterwards. The plan was built in cfo.ai from the unit economics measured on 12 evaluation tasks with the full product
(arm C): median cost $0.09 per job, 90th percentile $0.14, 75% of jobs verified, **$0.13 all-in per verified fix** including failed
attempts, and an average quoted price of **$0.34 per verified fix** (about $0.26 of revenue per job attempted). Those inputs are in
[`inputs.md`](inputs.md); the volumes, fixed costs and starting cash are the builder's **assumptions**, listed and labelled in
[`assumptions.md`](assumptions.md). Nothing here is a forecast from customers, because there are none.

## Files exported from cfo.ai
| File | What it shows |
|---|---|
| [`cfo-pricing.xlsx`](cfo-pricing.xlsx) | the two price points tested |
| [`cfo-revenue-and-margin.xlsx`](cfo-revenue-and-margin.xlsx) | monthly revenue, cost of revenue and gross margin, base scenario at $0.34 |
| [`cfo-cash-and-runway.xlsx`](cfo-cash-and-runway.xlsx) | monthly cash and runway, base scenario at $0.34, with and without a $2,000 founder salary |
| [`cfo-scenarios.xlsx`](cfo-scenarios.xlsx) | base and growth scenarios at both prices, by quarter |

## What the plan says
| | $0.34 per verified fix | $0.60 per verified fix |
|---|---|---|
| Quote band (floor to cap) | $0.18 to $0.67 | $0.32 to $1.18 |
| Cost per fix including 3% processing | $0.140 | $0.148 |
| Gross margin after processing | 58.8% | 75.3% |
| Volume assumed against $0.34 | 100% | 85% |
| Base scenario, operating result | loses about $20 a month | about $118 a month profit (first quarter of 2027) |
| Growth scenario, first quarter of 2027 | operating profit $383 | operating profit $1,207 |

- **At $0.34 the base case does not make money.** 1,000 jobs a month give $255 of revenue, $105 of cost of revenue and $170 of fixed
  costs. Cash falls slowly from $3,000 (about $2,480 by the first quarter of 2027). cfo.ai reports a runway of about 126 months,
  which is true only because the loss is small; it does not mean the business is healthy.
- **At $0.60, with 15% fewer jobs, the base case is profitable** once the first payments arrive: customers pay a month after billing, so
  October and November are negative while the fixed costs run.
- **No scenario pays a $2,000 founder salary** from $3,000 of starting cash: in the base case at $0.34 the balance with salary turns
  negative in November 2026, and in every scenario in the quarterly comparison it is negative by the end of 2026.
- The growth scenario depends entirely on the assumed 25% monthly growth.

## Limits (see `assumptions.md` for the list)
- The benchmark jobs are small fixes to open-source issues made by a cheap model, so $0.34 per fix is a floor, not a forecast: real
  customer issues are larger and a larger model costs more per job.
- Arm B (graph context only, flat price) was cheaper per verified fix than arm C in the benchmark ($0.11 against $0.13); the plan uses C
  because it is the product that quotes a band.
- The $0.60 volume loss, the fixed costs and the starting cash are assumptions. cfo.ai's own Simulator page was not tested.
