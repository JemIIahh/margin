# How the 16 benchmark tasks were chosen

**Status: selected by the build agent, awaiting the builder's review.** The choice of tasks shapes every number the
project reports, so please read the table and the rejected list below before treating the manifest as final.
The commit that adds the manifest is separate from the code so it can be amended or reverted on its own.

## The tasks

Each task is one real, closed GitHub issue. `base_commit` is the fix commit's parent; `fix_commit` is the commit that
fixed it (a single-parent commit). The agent sees the issue text and the fix commit's test changes (already applied
and committed in its worktree). It never sees the fix.

| Task | Split | Issue | Fix merged | Licence | Target tests | Source files | Suite (s) |
|---|---|---|---|---|---|---|---|
| `cachetools-423` | calibration | [tkem/cachetools#423](https://github.com/tkem/cachetools/issues/423) | 2026-09-27 | MIT | 1 | 1 | 4.69 |
| `toolz-602` | calibration | [pytoolz/toolz#602](https://github.com/pytoolz/toolz/issues/602) | 2025-10-16 | BSD-3 | 1 | 1 | 1.02 |
| `moreitertools-1304` | calibration | [more-itertools/more-itertools#1304](https://github.com/more-itertools/more-itertools/issues/1304) | 2026-09-29 | MIT | 2 | 2 | 14.75 |
| `sqlparse-772` | calibration | [andialbrecht/sqlparse#772](https://github.com/andialbrecht/sqlparse/issues/772) | 2024-05-13 | BSD-3 | 2 | 3 | 1.02 |
| `moreitertools-1308` | evaluation | [more-itertools/more-itertools#1308](https://github.com/more-itertools/more-itertools/issues/1308) | 2026-10-06 | MIT | 1 | 2 | 14.41 |
| `moreitertools-1284` | evaluation | [more-itertools/more-itertools#1284](https://github.com/more-itertools/more-itertools/issues/1284) | 2026-09-17 | MIT | 4 | 1 | 14.49 |
| `moreitertools-1214` | evaluation | [more-itertools/more-itertools#1214](https://github.com/more-itertools/more-itertools/issues/1214) | 2026-07-16 | MIT | 1 | 1 | 13.9 |
| `sqlparse-826` | evaluation | [andialbrecht/sqlparse#826](https://github.com/andialbrecht/sqlparse/issues/826) | 2025-11-29 | BSD-3 | 2 | 2 | 2.36 |
| `sqlparse-332` | evaluation | [andialbrecht/sqlparse#332](https://github.com/andialbrecht/sqlparse/issues/332) | 2026-07-25 | BSD-3 | 1 | 1 | 1.77 |
| `tomlkit-261` | evaluation | [python-poetry/tomlkit#261](https://github.com/python-poetry/tomlkit/issues/261) | 2026-06-23 | MIT | 1 | 3 | 1.07 |
| `tomlkit-619` | evaluation | [python-poetry/tomlkit#619](https://github.com/python-poetry/tomlkit/issues/619) | 2026-09-30 | MIT | 2 | 1 | 0.96 |
| `tabulate-241` | evaluation | [astanin/python-tabulate#241](https://github.com/astanin/python-tabulate/issues/241) | 2026-03-05 | MIT | 1 | 1 | 1.4 |
| `tabulate-305` | evaluation | [astanin/python-tabulate#305](https://github.com/astanin/python-tabulate/issues/305) | 2025-03-17 | MIT | 1 | 1 | 1.16 |
| `marshmallow-2249` | evaluation | [marshmallow-code/marshmallow#2249](https://github.com/marshmallow-code/marshmallow/issues/2249) | 2025-01-22 | MIT | 5 | 3 | 2.69 |
| `marshmallow-2900` | evaluation | [marshmallow-code/marshmallow#2900](https://github.com/marshmallow-code/marshmallow/issues/2900) | 2026-03-25 | MIT | 1 | 3 | 1.87 |
| `mistune-420` | evaluation | [lepture/mistune#420](https://github.com/lepture/mistune/issues/420) | 2026-07-25 | BSD-3 | 1 | 1 | 2.02 |

*Fix merged* is the fix commit's committer date. Nine of the 16 are dated 2026-06-23 or later.

## Checks every task passes

`margin tasks validate` (code in `src/margin/bench/tasks.py`) was run on all 16 and reported `ok` for each:

- the target tests fail at the base commit once the fix commit's test changes are applied;
- the real fix commit makes them pass, with **no new failures** versus the baseline (the same verdict the agent is judged by);
- the fix touches at most 3 non-test files (CHANGELOG and docs files count) and the whole suite runs in well under 60 s;
- **no network.** After everything was cloned and installed, the full validation was repeated with the network denied at
  the OS level (`sandbox-exec -p '(version 1)(allow default)(deny network*)'`) and all 16 still passed. The baseline
  and fix runs therefore never needed the network. Network access is still *not* blocked in real runs (a known limit).
- licences are permissive. Read from each repository's own LICENSE file: MIT-style for cachetools, more-itertools,
  tomlkit, python-tabulate and marshmallow; BSD-style for toolz, sqlparse and mistune.

## How the candidates were found (scripts in `docs/notes/curation/`)

The scripts ran from a scratch directory, so their paths are session-specific; they are kept for provenance, not as a tool.

1. `mine.py`: blobless clones of 19 candidate repositories (`python-slugify` could not be cloned and was skipped); kept
   single-parent commits whose subject reads like a bug fix, that change 1 or 2 test files and at least one `.py` source
   file, and at most 3 non-test files. 1,046 commits matched.
2. `probe.py`: for up to 14 recent matches per repository, used the project's own `prepare_run`/`run_suite` to check out
   the base commit, apply the fix's test changes, and find the tests that fail before and pass after the real fix.
   170 candidates across 15 repositories were probed; 131 reproduced. (`humanize` yielded none, because its version file is
   generated at build time, so it was dropped rather than debugged.)
3. `pool.py`: kept candidates whose commit message references a **genuine closed issue** (not a pull request) with a
   body of at least 300 characters, checked through the GitHub API (read-only). Pull-request descriptions were excluded
   on purpose: they tend to describe the fix, which would leak it.
4. I then read the issue text for each shortlisted candidate and chose by hand; `gen_manifest.py` wrote `bench/tasks.toml`
   and `bench/issues/*.md` from the probe data, so the pinned commits and target test ids are not hand-typed.
   Issue files are the issue title and body as fetched (carriage returns removed; comments are not included).

## Rejected after reading, and why

- `tomlkit#336` (underscored integers) and `cachetools#218` (invalidating `cachedmethod`): feature requests whose API is not
  determined by the issue, so a solve rate would measure guessing the maintainer's design.
- `sqlparse#532` (NULLS LAST parsing): the reporter says they are unsure what the right parse is.
- `sqlparse#827`: written as a pull-request summary, not a bug report.
- `more-itertools#1057`: a question, not a defect.
- `pyjwt#1039`: proposes two different changes (validate on encode, better errors on decode).
- Candidates whose only reference was a pull request, however good the code change.

## Limits and caveats worth knowing

- Most tasks are small, single-function fixes. Solve rates may be high, which compresses the room to show a difference
  between arms. The set mixes small container and string fixes with parser bugs (sqlparse, tomlkit) to keep some spread.
- `more-itertools` supplies 4 tasks and `sqlparse` 3; the other six repositories supply 1 to 2 each. Eight repositories in all.
- Calibration (4 tasks, 4 repositories) uses cachetools, toolz, more-itertools and sqlparse. The evaluation set (12 tasks)
  spans more-itertools, sqlparse, tomlkit, python-tabulate, marshmallow and mistune; cachetools and toolz appear only in
  calibration, so evaluation covers six of the eight repositories.
- Issue text for tomlkit-619 includes a long pasted pytest log; it is kept as fetched.
- Two defects in the test runner were found *by* this validation and fixed in `src/margin/sandbox.py`: test ids were
  prefixed with the worktree path whenever the repository had no pytest config of its own, and one unimportable test
  module (tomlkit's, which needs a git submodule) blanked the whole run. Both have regression tests.
