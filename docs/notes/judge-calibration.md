# Calibrating arm E's progress judge (calibration tasks only)

Arm E asks TypeSafe's Jev three yes/no questions about a running job each turn: is the agent making progress, is it
repeating itself, and does it already know what to change (`ready_to_edit`). Before any live arm E run, Jev was replayed
on the recorded runs of the four **calibration** tasks (`scripts/calibrate_judge.py`; evaluation tasks were never used).

Each run was sampled every four turns. Two groups were compared:

- **productive**: a turn in a run that went on to verify, before its first fully passing test run (39 samples);
- **stuck**: a turn from turn 12 on in a run that ran out of turns without verifying (15 samples).

Runs where the governor reset the conversation were left out. Two replays were made: the first without the patch (the
diff at each turn was not saved), the second with the patch rebuilt from the recorded `edit_file` and `write_file` calls,
which is closer to what the live judge sees. 54 Jev calls each, about $0.003 in total.

## What separated the groups (second replay)

| Rule | Flags stuck samples | Flags productive samples |
|---|---|---|
| `progress < 0.25` | 7% | 18% |
| `progress < 0.35` | 53% | 51% |
| `repeating >= 0.75` | 40% | 31% |
| **`ready_to_edit < 0.40`** | **93%** | **23%** (19% from turn 8 on) |
| `ready_to_edit < 0.35` | 60% | 10% (5% from turn 8 on) |

Medians: `progress` 0.33 (productive) against 0.34 (stuck), `repeating` 0.67 against 0.71, `ready_to_edit` 0.47 against
0.34. Readiness to edit never exceeded 0.40 in a stuck sample and reached 0.77 in productive ones.

## Decision

- The coach is called when `ready_to_edit < 0.40`, from turn 8 on, at most every 4 turns and at most twice per run. A note
  costs about $0.03, so the 19% false alarms are a small cost against catching 93% of stuck stretches.
- `progress` and `repeating` did not separate the groups, so they are logged for analysis but decide nothing.
- The free nudge to edit is sent when `ready_to_edit >= 0.65` and the agent's last three calls only looked around
  (5 productive samples reached that level, no stuck one).
- If Jev is unavailable, arm E falls back to arm D's rule (8 turns without a progress event).

## Limits

- 54 samples from four tasks; the replay sees a rebuilt patch, not the exact diff; labels are proxies (where a run was
  heading), not judgments of each turn.
- Thresholds were chosen once, from this table, before any live arm E run.
