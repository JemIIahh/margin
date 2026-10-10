# Failure recovery: faults injected into live runs

Four live runs on the arm C pipeline (`claude-haiku` through the event's proxy), each with one failure forced on it, all ending
in a verified fix. Run ids are the folder names under `runs/`; the rows are in the ledger with a `fault` or `version:demo-*`
tag, so `Ledger.latest` ignores them and they never replace a benchmark row.

| Demo | Task | Run id | What was injected | What the run did | Result | Cost |
|---|---|---|---|---|---|---|
| Flaky test result | `moreitertools-1308` | `moreitertools-1308-C-20261010-184131-d364` | a target test that really passes is reported failing once | re-ran the suite and kept only failures that persist (`flaky_rerun`: "1 spurious failure(s) cleared on re-run") | verified | $0.026 |
| Tool timeout | `moreitertools-1308` | `moreitertools-1308-C-20261010-184301-4091` | the full test run times out | fell back to the target tests only (`tool_timeout`: "tests timed out; retrying with the target tests only") | verified | $0.025 |
| API overload | `moreitertools-1308` | `moreitertools-1308-C-20261010-184358-038c` | the model API rejects calls as overloaded | retried with backoff, two `retry` events in the run log, then carried on | verified | $0.024 |
| Killed and resumed | `tomlkit-619` | `demo-resume-184535` | the process was killed with `kill -9` after its first checkpoint | `margin resume` restored the checkpoint, meter and governor state and finished the run | verified | $0.102 |

## What was checked

- Each fault run records the fault name and its recovery in its ledger row (`fault`, `recoveries`: 1, 1 and 2) and in its
  `events.jsonl`; none was marked as an infrastructure error.
- The resumed run's ledger cost ($0.1022) equals the sum of all 30 model calls in its event log, so the spend before the kill
  was counted once, not lost and not doubled. Its tags include `resumed:true`.
- The kill and the resume are produced by `scripts/resume_demo.sh tomlkit-619 C`.

## Not yet checked: the traces in neatlogs

The plan asks to open each trace and see a failed span followed by a recovery span. At the time of writing the neatlogs
read-back endpoint was returning `502 Bad Gateway` (four attempts over about a minute), so this was **not** verified. To check:
open the traces list and filter by the tag `version:demo-fault-flaky`, `version:demo-fault-timeout`,
`version:demo-fault-overload` or `version:demo-resume`.
