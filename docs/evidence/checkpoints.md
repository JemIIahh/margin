# Entire checkpoints

**Status: not published yet; gate in progress (2026-10-10, evening).** `push_sessions` is `false` in `.entire/settings.json`
and no checkpoint has left this machine.

## What will be published, and what will not

- **Only the final checkpoint** (the one cited in `EVIDENCE.md`) is published. A checkpoint holds the whole redacted session
  so far, so one is enough to show the build; the 28 oldest checkpoints, written before redaction was switched on, contain a
  personal email address and are kept locally under a backup ref namespace and never pushed.
- **Extra redaction rules are kept out of the repository.** Four more patterns (a personal email domain, a first name, and two
  account identifiers of a third-party service) live in `.entire/settings.local.json`, which `.entire/.gitignore` excludes, so
  the strings being hidden are not published by the file that hides them.
- **One exception is accepted by the builder:** the operating-system user name appears in file paths (`cwd`, `file_path`),
  which Entire exempts from redaction. It is a short account name, not an email or a full name.
- The gate's result is recorded in the section "Privacy gate" below once it has been run on the final checkpoint.

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

## Redaction configured (2026-10-10), and what it does and does not fix

`.entire/settings.json` now turns on PII redaction (emails, phone numbers) and a custom rule for home-directory paths,
following Entire's Privacy and Redaction docs. Checked on the first checkpoint written after the change
(`01M4JVC6NMY6QT82H2DE09GQ47`), counts only:

| Check | Result |
|---|---|
| Personal email addresses | none. What remains is code (`@pytest.mark`, `@pytest.fixture`), the allowlisted GitHub `noreply` address, and `noreply@anthropic.com` |
| Home-directory path | **still present**, in structural JSON fields (`cwd`, `file_path`, `root`). Entire exempts file-path and ID fields from every redaction layer by design, and has no setting to change that |

So the redaction rules protect transcript *text*, but the OS user name still appears in path fields. Whether that matters is the
builder's decision; if it does, options are a build session run from a neutral account or path, or not publishing those
checkpoints. Checkpoints written **before** this change (the 22 listed below, and the ones created while it was being tested)
keep their original content, including personal emails; they must not be pushed as they are. The OpenAI Privacy Filter (names)
is not available here: it only runs on the older branch backend, and this repository uses the ref backend.

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

## Privacy gate (plan Task 20, Step 4)

Run on 2026-10-10 on the checkpoint to be published, counting matches without recording the text. Nine checks: the account
email address, the email's domain, a first name, two account identifiers of a third-party service, the two API key values in the
local `.env` that are long enough to search for, any other email-shaped string with a real top-level domain (all zero), and the
operating-system user name in paths (present, accepted).
