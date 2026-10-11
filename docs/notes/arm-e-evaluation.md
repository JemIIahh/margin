# Arm E: arm D with TypeSafe's Jev as a cheap judge (12 evaluation tasks, version v4-jev)

Arm E is arm D with three decisions handed to Jev, TypeSafe's System One model, which returns typed probabilities instead
of text. Code owns every decision made from its answers.

1. **Intake gate** (from plan addendum 2): before anything is cloned or the agent spends anything, Jev rates the issue text on `injection`
   (does it try to instruct the agent?) and `actionable` (is it a concrete defect?). Thresholds were checked on the
   calibration items only ([`intake-calibration.md`](intake-calibration.md)).
2. **Progress judge**: from turn 8, each turn Jev reads a short digest of the run. Only one of its three answers proved
   useful on our own recorded calibration runs, `ready_to_edit` (does the agent know what to change?), so it alone decides:
   below 0.40, the coach writes a note (at most two, four turns apart); at 0.65 or above while the agent only explores, it
   gets a free nudge to edit ([`judge-calibration.md`](judge-calibration.md)). It replaces arm D's fixed rule "8 turns
   without progress".
3. **Lesson picker**: Jev rates every eligible lesson (same repository, never the task's own) against the issue and only
   those it rates relevant (0.5 or more) are given, at most five.

Everything else is arm D. One run per task, the same 12 evaluation tasks, the same worker and coach models.

## Result

| Arm | Solved | Cost | Revenue | Margin | Cost per solved fix |
|---|---|---|---|---|---|
| C (graph context, quote and governor) | 9 of 12 | $1.162 | $3.129 | +$1.967 | $0.129 |
| D (C plus coach, stop, run_python, lessons) | 11 of 12 | $1.172 | $3.848 | +$2.676 | $0.107 |
| **E (D plus the Jev judge, gate and picker)** | **11 of 12** | **$1.192** | **$3.890** | **+$2.697** | **$0.108** |

**E and D are level.** Same number of fixes, cost within $0.02, margin within $0.02. E fixed `sqlparse-332`, which D lost;
E lost `marshmallow-2249`, which D fixed (it reached its spend cap with two coach notes). With one run per task, that swap is
inside run-to-run noise. Two E runs hit their spend cap: `marshmallow-2249` without a fix and `tomlkit-261` with its fix already in place.

## What Jev changed

| | Arm D | Arm E |
|---|---|---|
| Coach notes over the 12 runs | 16 | 11 |
| Coach spend | $0.164 | $0.116 (about 30% less) |
| What triggered the coach | 14 by 8 turns without progress, 2 by the governor | 10 by Jev's readiness judgment, 1 by the governor |
| Lessons given per task | 5 for most tasks, 3 for the two `tabulate` tasks, none for `mistune-420` (the first five from the repository) | 0 to 3, about 1 on average (only those Jev rated relevant) |
| Jev's own cost | none | **$0.0095 for all 12 jobs**: 128 judge calls, the gate and the lesson picker |
| Nudges to edit | none | 1 |

Arm E's mean of 298,385 tokens per solved fix in [`../results.md`](../results.md) includes Jev's input tokens, about
17,800 per solved fix; without them it is about 280,600, against arm D's 261,368. The gate's tokens are not in that
count (the gate's cost is).

The gate accepted all 12 evaluation issues. On its own held-out test (Jev only, no agent) it accepted 12 of 12 clean
issues and declined 6 of 6 injected and 4 of 4 vague ones ([`../evidence/intake.md`](../evidence/intake.md)).

## What this does not show

- **That Jev improves the fix rate.** It did not, in this sample: E matched D. Its measured effects are a cheaper, more
  selective use of the coach and the lessons, and a gate that stops bad issues before the agent spends anything.
- **Run-to-run noise.** One run per task. A second run of D and E was planned and cancelled to keep the event allowance for
  the demo.
- **What an unprotected agent does with the injected issues.** Running the agent ungated on the variants (addendum 2, step 7)
  was also cancelled for the same reason, so the gate's value against attacks is shown by what it blocked, not by what an
  unprotected agent would have done.
- **Attack realism.** The injected issues are templates we wrote; detection is an upper bound on what adaptive text achieves.
- **Calibration size.** The judge's rule comes from 54 samples on four tasks; the gate's from eight items.

## Cost and data

Arm E's 12 runs cost $1.19, of which Jev was under one cent. Issue text and short run digests (issue, patch, last test
result, recent tool calls) are sent to TypeSafe; nothing else leaves the machine beyond what the model provider and neatlogs
already receive.
