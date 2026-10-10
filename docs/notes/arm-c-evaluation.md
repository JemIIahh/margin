# Arm C on the 12 evaluation tasks (version v2, default thresholds 0.6 and 0.85)

One run per task, so every number is a single sample. Cost is the metered spend of the run; revenue is the quoted price when
the fix verified and nothing when it did not.

| | Solved | Cost | Revenue | Margin | Cost per solved fix |
|---|---|---|---|---|---|
| A (whole files, flat $0.3006) | 8 of 12 | $2.085 | $2.405 | +$0.319 | $0.261 |
| B (graph context, flat $0.3006) | 11 of 12 | $1.203 | $3.307 | +$2.104 | $0.109 |
| C (graph context, quote and governor) | 9 of 12 | $1.162 | $3.129 | +$1.967 | $0.129 |

Quote coverage: the actual cost fell inside the quoted band on 10 of the 12 tasks (out-of-sample, leave-one-out).

## What the result does and does not show

- C clearly beats A on every column. Against B it solved two fewer and made slightly less margin; the quote did not buy more
  profit than simply running B at the flat price.
- C solved 9 and B solved 11. The three tasks C failed and B solved:
  - `marshmallow-2249`: the quote's upper band ($0.150) was below what B needed ($0.172). The governor downgraded at turn 16
    (no progress at 67% of the cap) and narrowed at turn 29 (87% of the cap), and the run ended at $0.133 with a regression
    left in. This is the failure the governor is plausibly responsible for: a cap set from a quote that undershot.
  - `tomlkit-261`: a downgrade at turn 22, then the turn limit at $0.123, under the $0.171 upper band and under the narrow
    threshold. B solved it for $0.112. The cap was not binding, so this may be run-to-run variance or an effect of the
    downgrade; one sample cannot separate them.
  - `sqlparse-826`: no governor decision at all; the turn limit at $0.176. Variance.
- The flip goes the other way too: `tomlkit-619` failed under B and solved under C.
- The governor intervened in 3 of the 12 runs (rungs on `moreitertools-1284`, `tomlkit-261`, `marshmallow-2249`); it did not
  abort any run. Spend was about the same as B ($1.162 against $1.203), so it saved little money in this sample.

## What to claim

- Claim: graph context (B and C) cut cost per solved fix by about half or more against whole-file context (A), on this
  benchmark with this model.
- Do not claim the quote and governor improved on B: in this sample they did not, and with 12 tasks and one run each the
  difference between C and B is inside what the same code does from run to run.
- The honest finding on the governor: a cap taken from the quote's upper band can end a run that needed slightly more. A
  receipt shows when that happened, which is the visibility the product promises, but the rule did not win here.
