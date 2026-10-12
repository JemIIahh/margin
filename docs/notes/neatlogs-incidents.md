# What neatlogs showed us about our incidents (2026-10-12)

The judges asked for one video that shows how neatlogs' critical-incidents feature helped identify and solve the incidents
the agent ran into. This note records what we found when we looked, so the video says only what is true.

## The Incidents page was empty

On 2026-10-12, with the project's setup checklist completed and the day's runs visible in Traces, the Incidents page said
"No incidents yet. Show, Watch, and Hidden incidents appear here after the first Issue snapshot is published." It still
said so after a burst of six more runs that failed the same way. We therefore do not claim neatlogs raised an incident for
this project. What we used instead: Traces (every run, tagged by arm, task and version), Detections (the "Execution
Failed" badges on failed calls) and Investigate (an AI that reads traces and answers a question).

## Investigate, first question

Asked: *In the last 2 days, which runs of the margin workflow ended without making any edit (no edit_file call), and why
did they end?* It answered with 10 runs. That matches our own records exactly: three runs at the quoted cap in the stress
test, four re-runs of the same, one run lost to a network error, and two smoke tests.

- **Right:** the count; the run that ended at turn 13 after consecutive model-call errors (our real network incident); the
  smoke tests; the Jev scores it quoted match our event logs.
- **Wrong:** that "the Coach forcefully terminates" stuck runs. The coach only writes a note. Those runs ended because the
  spending cap or the turn limit was reached, as the receipts and the governor spans say. It also said it had not read four
  of the traces in depth.

## Investigate, second question, and a bug of ours

We then ran Black #4349 again (`incident-test-2`) and asked why that run ended without an edit. It again said the coach
ended it, and placed the abort at turn 13 (it was turn 14, for the cap: "spend $0.0888 plus next call $0.0248 reaches the
cap $0.1121").

Between the two questions we had added the run's outcome (why it stopped, edits, cost, cap) to the trace. That change did
nothing: neatlogs' workflow span is not OpenTelemetry's current span, so the attributes went to an empty span (checked locally
with neatlogs' own wrapper; our tests had used a plain OpenTelemetry span, so they passed). The outcome is now its own child
span, `margin.outcome`, made with neatlogs' own `trace()`, with a plain-language summary ("not verified. Stopped by: spend
... reaches the cap ... 0 edits made. The coach wrote 2 note(s); a coach note is advice and never ends a run."). Commits
`7871ac4` (the attempt) and `26fd631` (the fix).

## Investigate, third question

Asked about `incident-test-3`, the first run to carry the working outcome span, in Neatlogs Fast mode: *Why did the most recent
margin run, version incident-test-3 on black-4349, end without making any edit?* It found the right trace (it noted its
default filter window had excluded it and searched historically) and said, a third time, that "the run was terminated by the
Coach agent due to repetitive exploration and a lack of progress", with a "graceful abort (Turn 15)". Checked against the
run's own event log:

| Claim | The run's record |
|---|---|
| zero edits | correct: 0 edit_file calls |
| Jev at turn 12: progress 0.32, repeating 0.46, ready to edit 0.29 | correct |
| Jev at turn 8: 0.43, 0.46, 0.29 | wrong: 0.43, 0.47, 0.36 |
| the coach aborted the run at turn 15 | wrong: ABORT at turn 16, "spend $0.0901 plus next call $0.0246 reaches the cap $0.1121" |

So the answer was right about what the agent did and wrong, a third time, about why the run ended. Whether it ever read the
`margin.outcome` span we added is not something the answer shows; it did not mention it. We did not try Deep mode.

## What changed because of this

- The run's outcome is in the trace, in plain words.
- Hard-task runs get more runway in a test (`MARGIN_CAP_MULTIPLE`, 60 turns): every run then edited, and Click's target tests
  went from 63 failing to 30 ([`stress-test.md`](stress-test.md)).
- The network incident is recorded as an infrastructure failure and excluded from every result; resuming from the
  checkpoint instead of stopping is not built yet.

## Limits

One project, one day of traces, three questions, all in Fast mode. Investigate's explanations were wrong about mechanism all
three times we checked, and we say so; its lists of runs matched our records. We did not use the "Track as issue" action that the judges' demo shows on an Investigate report.
