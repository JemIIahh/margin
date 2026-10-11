# Arm D: a coached agent that learns from past runs (12 evaluation tasks, version v3-learn)

Arm D is arm C (graph context, quote, spend cap) with four changes, each aimed at a finding in
[`audit-2026-10-11.md`](audit-2026-10-11.md):

1. **A coach instead of the downgrade.** When the run is stuck (the governor's no-progress rung, the narrow rung, or 8 turns without progress), a
   stronger model (`claude-sonnet-4.6` on the event's proxy) reads a digest of the run and writes a short note: a diagnosis, a next step and
   one thing to avoid. The worker keeps its own model (`claude-haiku`) and its whole conversation. At most two notes per run, both metered
   and counted against the cap.
2. **Stop when verified.** After a full test run in which every target passes and nothing new fails, the agent is told the fix verifies and to
   finish; if it keeps going, the harness ends the run two turns later.
3. **`run_python`.** The agent can run a snippet with the repository importable, for example to reproduce the issue.
4. **Lessons from past runs.** `margin lessons build` turned post-mortems of 28 recorded runs (every failed run and the cheapest verified run
   of each task) into 84 one-line lessons, for $0.31 with the coach model ([`bench/lessons.jsonl`](../../bench/lessons.jsonl)). A run gets
   up to five lessons from **other** tasks of the same repository, never from its own (leave-one-out); 7 lessons that advise writing tests
   are skipped, because the tools refuse test edits.

Arms A, B and C were not re-run or changed. One run per task, the same 12 evaluation tasks, the same worker model.

## Result

| Arm | Solved | Cost | Revenue | Margin | Cost per solved fix |
|---|---|---|---|---|---|
| A (whole files, flat price) | 8 of 12 | $2.085 | $2.405 | +$0.319 | $0.261 |
| B (graph context, flat price) | 11 of 12 | $1.203 | $3.307 | +$2.104 | $0.109 |
| C (graph context, quote and governor) | 9 of 12 | $1.162 | $3.129 | +$1.967 | $0.129 |
| **D (C plus coach, stop, run_python, lessons)** | **11 of 12** | **$1.172** | **$3.848** | **+$2.676** | **$0.107** |

Revenue for A and B uses the flat price ($0.3006 per verified fix); C and D bill each task's own quoted price, only when the fix verifies.

- **Against C, the product it replaces:** two more fixes for the same spend, and $0.71 more margin. D fixed all three tasks C failed
  (`marshmallow-2249`, `sqlparse-826`, `tomlkit-261`); in C, two of those failed after the downgrade the coach replaces.
- **Against B:** the same number of fixes at about the same cost ($0.107 against $0.109 per solved fix). D's margin is higher because it sells
  at quoted prices, not because it is cheaper.
- **What D lost:** `sqlparse-332`, which A, B and C all fixed. It ran out of turns after 12 `run_python` calls and two coach notes ($0.138).

## What each change did

| Change | Observed |
|---|---|
| Stop when verified | 8 of the 11 verified runs were told the fix verified, kept working, and were ended by the harness two turns later; none stopped on its own. Two more reached the 30-turn limit and one (`moreitertools-1284`) hit its spend cap, each with the fix already in place. Spend after the first "fix verifies" notice fell to **5%** of the verified runs' cost, from **18%** in arms B and C. |
| Coach | 16 notes in 11 of the 12 runs, **$0.164, 14% of D's spend**: 14 triggered by 8 turns without progress, 2 by the governor's no-progress rung. |
| `run_python` | 47 calls across the 12 runs; up to 14 in one run. |
| Lessons | 11 of the 12 tasks received lessons (3 to 5 each); `mistune-420` got none, because no other task comes from its repository. |

On the four calibration tasks (run first, as a live check) D solved 3 of 4 for $0.415, against 3 of 4 for C ($0.389) and B ($0.374); the one
miss, `sqlparse-772`, is the task every arm fails.

## What this does not show

- **Which change helped.** There is no ablation: the four changes were measured together. The pattern fits the audit (the tasks C lost after
  a downgrade were fixed without one, and the spend after verification dropped as designed), but one run per task cannot separate the
  coach from the lessons or from `run_python`.
- **Run-to-run noise.** Every arm has one run per task. A difference of one or two tasks is inside what the same code does from one run to
  the next, and D lost a task the other arms solved.
- **Same code as the benchmark.** D ran on the source after the review fixes and the arm D commits; arms A to C ran on commit `73da1d0`.
- **Where the lessons came from.** They were written from the A, B and C runs on these same tasks, used leave-one-out by task. That simulates
  a product that learns from earlier jobs in the same customer repository; a task never sees advice written about itself.
- **Cost outside the ledger.** Building the lessons ($0.31) and one probe call are not in any run's cost.

## Next, if this is taken further

- A limit on exploration: `sqlparse-332` shows that `run_python` can eat the turn budget. A nudge after several snippets without an edit
  would be the first thing to try.
- An ablation (D without the coach, D without lessons) on the calibration tasks, then more than one run per task.
- Lessons written after each D run as well, so the store grows with use, and a check that it does not drift into task-specific hints.
