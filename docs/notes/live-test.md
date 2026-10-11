# A live test on an issue outside the benchmark (2026-10-11)

The 16 benchmark tasks were chosen at the start and every arm was tuned on four of them. This test asks what Margin does
on a real issue it was never built around: a repository the task search never mined, and a fix newer than every
benchmark task. One run, arm E, the same code and models as the evaluation.

## The task

- **Issue:** [Python-Markdown/markdown#1647](https://github.com/Python-Markdown/markdown/issues/1647), "3.11 doesn't accept
  tag properties containing html strings anymore". `<span data-tip-txt="<kbd>Ctrl</kbd>">Anything</span>` was escaped as
  text instead of passed through as HTML.
- **Fix:** commit `7a29324` by a maintainer, 2026-10-03, eight days before this run. It changes the `HTML_RE` pattern in
  `markdown/inlinepatterns.py` and adds one test, `test_angle_brackets_in_attributes`.
- **Why this one:** Python-Markdown was not among the repositories mined for the benchmark. The issue is a genuine bug
  report with the exact input and expected output; the fix is a single commit that touches one source file, the
  changelog and one test file. It was found by the same filters as the benchmark (a 2026 single-parent bug-fix commit
  that cites a closed issue, not a pull request).
- **Manifest:** [`bench/tasks-live.toml`](../../bench/tasks-live.toml), split `live`, so it is in no reported table.
  `margin tasks validate` reported `ok` (7 s): the new test fails at the parent commit with the fix's test applied, passes
  with the maintainer's fix, and nothing else breaks.

## The run (`markdown-1647-E-20261011-153448-8550cc62`, version `live-1`)

| Step | What happened |
|---|---|
| Intake gate (Jev) | accept: injection 0.03, actionable 0.97, cost $0.000035 |
| Quote | cost band $0.0222 to $0.1121 (p50 $0.0499) from 16 past runs; price $0.1681; spending cap $0.1121 |
| Lessons | none: no past job in this repository |
| Work | 14 worker calls (`claude-haiku`), 13 tool calls, 4 Jev judge calls |
| Turn 8 | Jev judged the run stuck (`ready_to_edit` 0.34); the coach (`claude-sonnet-4.6`, $0.0096) named the attribute part of `HTML_RE` |
| Fix | one line in `markdown/inlinepatterns.py`: quoted attribute values may contain `<` and `>` |
| Verdict | **verified**: the target test passes and no test that passed before fails |
| Receipt | actual cost $0.0689, inside the band and under the cap; revenue $0.1681; margin $0.0992 |
| Proxy check | the proxy's own bill for the run was $0.068563 against $0.068832 metered |

Receipt: [`docs/evidence/live/markdown-1647-receipt.md`](../evidence/live/markdown-1647-receipt.md).

## How much of the suite the verdict covered

The run's task environment installed only `pytest` and `pyyaml`, and ran the repository from source. Python-Markdown finds
its extensions (`md_in_html`, `footnotes`, `tables` and others) by name through the installed package's metadata, so 364
extension tests could not load: they failed before the fix and after it, and the verdict's "nothing that passed before
broke" covered the other 746 or so. A harness gap, found after the run by reading the failures.

The agent's fix was then re-checked, without running the agent again, in an environment that also installs the
published `markdown` 3.11 (it registers the extension names; the worktree's source still loads first):

| Version of `inlinepatterns.py` | Passed | Newly failing |
|---|---|---|
| before the fix | 1,109 | |
| the agent's fix | 1,110 | 0 |
| the maintainer's fix | 1,110 | 0 |

The only test that changes is the bug's own. So the verdict stands on the whole runnable suite, including `md_in_html`,
the extension that handles raw HTML. The task now lists `markdown==3.11` in its `deps`, and `margin tasks validate`
reports a baseline of 1,109 passing tests. The ledger row and receipt are the run as recorded.

## What the tests did not catch

The agent's pattern for the attributes is `(?:[^<>"']*|"[^"]*"|'[^']*')*`, a repeated group whose first branch can
itself repeat. On a tag that is never closed, the regex engine tries every way to split the text between them. Timed on
`<a ` followed by n letters and a stray `<` (no match possible), with Python 3.12:

| n | before the fix | maintainer's fix | agent's fix |
|---|---|---|---|
| 10 | 0.00 ms | 0.01 ms | 0.11 ms |
| 18 | 0.00 ms | 0.00 ms | 29 ms |
| 22 | 0.00 ms | 0.00 ms | 595 ms |

The time roughly quadruples for every two extra characters, so a tag of about 30 characters would take minutes.

The coach did not cause this. Its note suggested `(?:[^<>"']|"[^"]*"|'[^']*')*`, one character at a time, which matches the
issue's tag and stays linear (0.01 ms at n = 22, 0.37 ms at n = 5,000). The worker wrote `[^<>"']*` inside the group
instead, and that one added `*` is what makes the pattern exponential. The
maintainer's fix uses possessive quantifiers and stays instant; Python-Markdown fixed slow-parsing bugs of this kind in
August and September 2026 (#1619, and a reference-link case of the still-open #798). The repository's suite has no test for it, so Margin's verdict, which is the suite's
verdict, was "verified".

**What this means.** Margin's guarantee is exactly "the repository's own tests pass and nothing that passed broke". That
is stronger than an agent's word, and it is what made this run billable, but it is only as strong as the suite: a fix can
pass every test and still be one a maintainer would reject. Ways to close the gap, none built yet: time the suite and the
changed functions before and after and refuse a fix that slows them; run a linter for super-linear regexes on changed
patterns; and keep a human review before merge, which the roadmap's GitHub App already assumes.

## Limits

One run on one issue. It shows Margin working end to end on an unseen repository at the quoted price; it does not
estimate a solve rate.
