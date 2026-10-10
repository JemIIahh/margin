# Entire checkpoints

**Status: not published.** `push_sessions` is `false` in `.entire/settings.json` and nothing has been pushed.
The privacy gate (plan Task 20, Step 4) has **not** been run: it needs the builder's own list of strings that must
never appear publicly, and it must pass before any checkpoint is pushed.

## Preliminary scan (2026-10-10, generic patterns only, read-only)

Counts over all 22 local checkpoint refs (`refs/entire/checkpoints/*`). Matched text is deliberately not recorded here.

| Pattern | Result |
|---|---|
| Credential-shaped values (`sk-ant-...`, `nlw_...`, `*_API_KEY=<value>`, GitHub tokens) | none that look real. The only `sk-ant` hits are the 12-character documentation text `sk-ant-admin` |
| Home-directory paths (`/Users/...`) | present, thousands of lines |
| Email-address-shaped strings | present, hundreds of lines |

**Conclusion:** the gate would fail today. Checkpoints contain full session transcripts, so they include local paths and
addresses. Before publishing, either configure redaction for those patterns, or re-create the evidence from a fresh session
that never contained them (plan Step 4 (a) to (c)). A checkpoint's title is also taken from the session prompt, so check
titles too.

## Checkpoints for the commits in this repository (local)

| Checkpoint id | Commit | Time (local, 10-10) | Subject |
|---|---|---|---|
| `01M4JPS05G8J0B59Y82V9C0TA5` | `e9c0a87` | 10-10 11:47 | feat: measured inputs for the cfo.ai business plan |
| `01M4JPPN4BB20TTAD443QVVXTB` | `53fa350` | 10-10 11:45 | feat: results page, receipts page, and make verify |
| `01M4JPKR5SVFTMW8ZP2KPNYXGM` | `aeaf7fb` | 10-10 11:44 | feat: fault injection, visible recoveries and resume |
| `01M4JPF445A0WWJ35VA5S0CADS` | `45b8562` | 10-10 11:41 | feat: arm C tests and the quote command |
| `01M4JPCZMYFM23S3HGR5GNG2BC` | `77c8a84` | 10-10 11:40 | feat: entire-graph adapter and graph-scoped context (arm B) |
| `01M4JP7XY57ZR928FHTEPDR3K9` | `cde4da7` | 10-10 11:37 | feat: nearest-neighbour quoter with leave-one-out evaluation |
| `01M4JP5GST8JZD1MX40T353SZA` | `0c2ed65` | 10-10 11:36 | feat: batch runner with spend guard, report metrics, bench and calibrate-flat... |
| `01M4JP1SFJMHMTSMTEBNTXACH3` | `a3816d0` | 10-10 11:34 | feat: the 16-task benchmark manifest and curation notes (selection pending bu... |
| `01M4JNQK7PVTGYF1KWVVX4BDPP` | `fbde570` | 10-10 11:28 | fix: report an unimportable test module as one failure instead of blanking th... |
| `01M4JNA95P88FZSAT9RM4HM0K8` | `a52056e` | 10-10 11:21 | fix: pin pytest rootdir to the worktree so test ids do not depend on its loca... |
| `01M4JME9MX09GTHGF3PJE0KS78` | `482fb13` | 10-10 11:06 | feat: task validation command and scrubbed environment for setup commands |
| `01M4JKR21V989F72Y14MHS8ZFA` | `df8a483` | 10-10 10:54 | feat: task preparation, run orchestration and CLI (M1 walking skeleton) |
| `01M4JKH7E93GAQ34AEMS2G21M2` | `47bfe6b` | 10-10 10:50 | feat: model request builder and agent loop with governor hooks |
| `01M4JKCXSER3QVAE8FK59NBG3R` | `23feb67` | 10-10 10:48 | feat: agent tools, plain search and naive context |
| `01M4JKA9FH6H5105Y7350EZRYJ` | `0ccd8a9` | 10-10 10:46 | feat: governor rung ladder |
| `01M4JK93R3GJD3E9FPM4ZN00MT` | `c2fac54` | 10-10 10:46 | feat: baseline-aware verifier |
| `01M4JK77EMX6EA1YHYF5E99W20` | `64710f1` | 10-10 10:45 | fix: harden host-side git in the sandbox against pointer and config injection |
| `01M4JJH6P9G7PJRM3DE1ACSF1E` | `09118cc` | 10-10 10:33 | feat: sandbox with confined file tools and scrubbed pytest |
| `01M4JJFDJJD6RZW4FSYZS74H9C` | `9068964` | 10-10 10:32 | feat: run state with event log and verified checkpoints |
| `01M4JJEY074NW8G74DXW7MXTNC` | `3e67adb` | 10-10 10:31 | feat: run ledger, settlement and receipts |
| `01M4JJDQWFAM9P949WZFE36AFB` | `946ec6e` | 10-10 10:31 | feat: price table, usage and spend meter |
| `01M4JJBRBAVZ8WDY5XKWHT2S09` | `e02faf1` | 10-10 10:30 | chore: scaffold project, settings and telemetry shim |

The same id appears as an `Entire-Checkpoint:` trailer on each commit message.
