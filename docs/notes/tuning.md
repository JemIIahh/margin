# Governor threshold tuning (calibration tasks only)

Arm C (quote, spend cap, governor) was run on the four calibration tasks with the spec's default rung thresholds
(DOWNGRADE at 0.6 and NARROW at 0.85 of the upper cost band). The evaluation tasks were not used for any tuning.

```
v2-tune-default n=4 solve=75% profitable=75% wasted=$0.26 cost=$0.39 revenue=$0.62
```

| Task | Solved | Cost | Price billed | Governor |
|---|---|---|---|---|
| cachetools-423 | yes | $0.027 | $0.195 | none |
| toolz-602 | yes | $0.068 | $0.257 | none |
| moreitertools-1304 | yes | $0.032 | $0.168 | none |
| sqlparse-772 | no (turn limit) | $0.262 | $0.494, not charged (not verified) | DOWNGRADE at turn 22 |

## Decision: keep the defaults (0.6 and 0.85)

The plan's tuning step also runs an earlier pair (0.5 and 0.8) and a later pair (0.7 and 0.9) and keeps the best. Those two
batches were **not run**. Reasons, in order of weight:

1. Four tasks cannot rank three threshold pairs. Three of the four never reach a rung, and the fourth is the one task both other
   arms also fail, so the pairs would differ on one run, which is noise. The plan itself says to keep the spec defaults when the
   difference is noise.
2. Each extra batch costs about $0.4 to $0.5 of the event's shared $20 allowance; the builder asked to stop spending before the
   benchmark's main numbers were in.

What this means for the claim: the thresholds are the spec's values, chosen before any data and not fitted to it. The governor's
effect on the evaluation tasks is reported as measured, and a result of "it rarely intervenes" is a valid outcome.
If a threshold sweep is wanted later, it should be run on the calibration tasks only, under new version tags
(`v2-tune-early`, `v2-tune-late`), and recorded here.
