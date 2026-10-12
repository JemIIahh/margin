# A stress test on harder tasks (2026-10-11)

The 16 benchmark tasks and the live Markdown run are small fixes: one to three files, a few lines each. This test asks what
Margin does when the work is larger. Three real closed issues in repositories the task search never used, each fixed
upstream by a change of 50 to 330 source lines. One run each of arm E (the full product), as a customer would get it:
the cap is the top of the quoted band, nothing else is changed.

**Result: none of the three was fixed, in either round.** Under the quoted cap (round 1) none of the runs made a single
edit. With four times the cap and twice the turns (round 2) all three edited, and two made real progress: Click went from
63 failing target tests to 30, and Black #1245 from two to one, with nothing else broken. Nothing was billed for any of
them. The stress test cost $1.73 in all ($0.36 and $1.37).

## The tasks

| Task | Issue | What the real fix did | Target tests | Repository |
|---|---|---|---|---|
| `click-2952` | [pallets/click#2952](https://github.com/pallets/click/issues/2952), flag value ignores `envvar` | `core.py` and `types.py`, 161 changed lines; env-var, default and flag-value semantics | 63 | 11,800 lines, suite 3 s |
| `black-1245` | [psf/black#1245](https://github.com/psf/black/issues/1245), comments between `fmt: off/on` are reformatted | `comments.py` and `linegen.py`, 333 changed lines | 2 | 103,000 lines, suite 33 s |
| `black-4349` | [psf/black#4349](https://github.com/psf/black/issues/4349), needless parentheses in an indexed assignment | `lines.py`, `linegen.py`, `mode.py`, a new 51-line helper behind a preview feature | 1 | 103,000 lines, suite 37 s |

Manifest: [`bench/tasks-hard.toml`](../../bench/tasks-hard.toml), split `live`, so they are in no reported table. They came
from the same kind of search as the benchmark (single-parent 2025-26 bug-fix commits that cite a closed issue), with the
size limits loosened to 2 to 10 source files and 50 or more changed lines. Only these three were kept: the other
candidates cited a pull request (whose text describes the fix) or were feature work. `margin tasks validate` passes for
all three with `--max-source-files 8 --max-seconds 120` (new flags: the benchmark's limits of 3 files and 60 s are
curation defaults, not rules); target tests were found by running the fix's tests before and after the real fix, and the
real fix breaks nothing.

Two details of the task setup, as with the Markdown run: Black builds a version file at install time, so its tasks install
the published `black[d,jupyter]` for that file and the optional test dependencies (the worktree's source still loads
first); and Click's issue body only points to a comment, so its issue file also carries the user's reproduction from the
thread.

## What happened

| | Click #2952 | Black #1245 | Black #4349 |
|---|---|---|---|
| Intake gate | accept (0.95) | accept (0.97) | accept (0.96) |
| Quoted band, cap | $0.050 to $0.251 | $0.022 to $0.112 | $0.022 to $0.112 |
| Spent | $0.174 | $0.090 | $0.092 |
| Turns | 30 (the limit) | 14 | 16 |
| Edits made | 0 | 0 | 0 |
| Stopped by | turn limit; $0.077 of the cap unspent | the cap, at 80% plus the next call | the cap, at 82% plus the next call |
| Coach notes | 2 | 2 | 2 |
| Billed | $0 | $0 | $0 |

In every run the agent read tests and source, ran snippets, and was judged by Jev as not ready to edit (`ready_to_edit`
0.19 to 0.30 throughout). The coach named the right place each time: `normalize_comment` for #1245,
`normalize_invisible_parens` for #4349, `resolve_envvar_value` and the boolean conversion in `types.py` for #2952. Reading
is what the budget went on: on the 100,000-line repository a call averaged $0.005, and the governor's estimate for the
next one had risen to $0.025 once the agent had read a large data file and a large module, so a $0.11 cap bought 14 to 16
turns.


## Round two: four times the runway

Round one stopped every run before it could edit, which does not say whether the agent could have done the work. So the
same three tasks were run again with the cap at 4 times the quote's top (`MARGIN_CAP_MULTIPLE=4`, a test-only setting,
refused for benchmark versions), 60 turns instead of 30, and a hard per-run ceiling as a second safety net. The price
stays the quoted one, so a run that overspends shows as a loss. Same arm E, same models.

| | Click #2952 | Black #1245 | Black #4349 |
|---|---|---|---|
| Cap (4x), spent | $1.004, $0.463 | $0.448, $0.417 | $0.448, $0.422 |
| Turns | 60 (the limit) | 59 | 56 |
| Edits, test runs | 4, 6 | 6, 3 | 9, 4 |
| Target tests failing | 63 to 30 | 2 to 1 | 1 to 1 |
| Tests newly broken | 0 | 0 | 0 |
| Stopped by | the turn limit; $0.54 of the cap unspent | the cap (narrowed budget used up) | the cap |
| Billed | $0 | $0 | $0 |

- **Click #2952:** the progress was steady, 63 to 43, 41, 38 and 30 failing target tests over four edits to `core.py`, with
  no regressions. It ended on the 60-turn limit with more than half its money left, so here the turn limit, not the cap,
  was the binding constraint.
- **Black #1245:** six edits to `comments.py`, the file the real fix changed, fixed `fmtskip7` but not `fmtonoff`, the
  larger of the two cases; the run ended when the narrowed budget ran out.
- **Black #4349:** nine edits to `linegen.py`, with regressions along the way that it repaired, but the target test never
  passed. The agent worked on a neighbouring function from the one the maintainers changed, and its change is not behind
  Black's "preview" feature convention, which a maintainer would ask for in a style change.
- **A network failure:** the first round-two run of Black #1245 hit a connection error that outlasted all six retries at
  turn 13. The ledger marks it as an infrastructure failure, excluded from every table, and it was run again. A shorter
  network drop in the Black #4349 run was recovered by the retries.

What round two adds: the agent does not fail for want of ability to start. Given runway it edits, reads its own test
results, and moves toward the fix. On the largest task (Click, 63 tests across four behaviours) it was more than halfway
there. What it does not show is that more runway would have finished any of them: Click might have converged in another 30
turns or might not, and Black #4349 was on the wrong function.

## What this shows

- **The protections held.** Each run stopped at its cap or turn limit, nothing was billed for a failed fix, and the
  receipts say why. A worse outcome than $0.36 was not possible by design.
- **The quote cannot see difficulty, and here it was outside its experience.** The quoter learned from 72 recorded runs whose
  largest repository was 7,274 lines and longest suite 16.5 s. Black is 14 times larger, with a suite twice as long, and
  both Black tasks got exactly the band of a one-line Markdown fix. A quote built on data like that is an extrapolation and
  should say so: the next change is to widen the band, or flag low confidence, when a task's features are beyond the
  history.
- **Hard tasks need more runway than the benchmark's.** In round one Click ended on the 30-turn limit with money left and
  the Black runs ended on the cap with turns left. Neither limit was chosen for work of this size, and round two shows the
  difference runway makes (edits and real progress, against none).
- **Raising the cap is not free.** Round two cost roughly three to five times round one per run (2.7 to 4.6 times) ($0.42 to $0.46 against $0.09 to
  $0.17) and still did not verify a fix, so on these tasks an honest quote would have been well above the price of a quoted
  easy job, and Margin would have billed nothing.

## What this does not show

- **Whether the agent can solve these at all.** Round two moved toward a fix on two of three but verified none; a third
  round with more turns on Click, or a stronger worker model, would be the test.
- A solve rate. It is one run on each of three tasks per round, with a cheap worker model (`claude-haiku`).
- That Margin is bad at hard tasks in general: it shows what it does under the cap a customer would be quoted today.

Receipts for both rounds: [`docs/evidence/live/`](../evidence/live/).
