# Addendum 4: the Margin console (a black-and-white staged replay built from the real ledger)

**Why.** `docs/receipts.html` is a card per run. It shows the result but not what Margin *is*. The console is an interactive page that does: it plays one recorded job as a short film (quote the price, cap the spend, bill what verifies), shows how three versions of the agent did on twelve real issues, and lets a visitor move the markup and the spending cap and watch the money recompute.

It is **a replay of recorded runs, not a live app.** It has no server, no login, no input a visitor types in, and it makes no network request. It reads files that are committed (the ledger snapshot, a replay snapshot built from each run's event log, and the task manifest with the issue titles) and draws from them. Nothing on it is typed in by hand.

Do this after the live runs you intend to publish are in `docs/evidence/ledger.jsonl`. It can be done at any time; it never changes a number, only displays it.

## The three screens

**Demo (opens first).** A staged film of one job, in black and white, with a pause button and three chapters (the chapter bar fills as it plays; click a chapter to jump; Space pauses; the arrow keys change chapter). A single bar is the whole idea: its length is the price, it fills with model cost as the agent works, and when the fix verifies the rest turns white (the margin). A very large light numeral tells the story on its own: the price, then what has been spent, then what is kept.
- *Quote the price:* the terminal types the real `margin quote` command and prints its real output line; the chapter card shows what Margin read about the issue and the three most similar past jobs the quote was learned from (numbered, and drawn on the bar); the band, the cap and the price appear on the bar.
- *Cap the spend:* the terminal types `margin run`, then streams the run's real event log; the bar fills; a four-rung governor (continue, cheaper model at 60% of the cap, narrow at 85%, stop) lights up from the real governor events, and a line in the header announces each one.
- *Bill what verifies:* two checks resolve, with the real failing test id when one fails; the terminal prints the real run summary and the receipt path; and the receipt appears as white paper with the real receipt's fields and a BILLED or NOT BILLED stamp. The bar splits into cost and margin, or turns dashed with "Not billed".
- A job picker (12 issues and the 4 failure drills), a version switch (A, B, C) that keeps the issue, the issue title and its GitHub link. The film ends on a blurred "Play again". With reduced motion it does not play by itself: it shows the finished state, and Play starts the film.

**Proof ("Did it make money?").** Written to be read top to bottom in a minute, with a one-line "how to read this" under every heading.
- *What each version kept:* one bar per version on a shared dollar axis. A bar is everything billed for the 12 fixes, split into the cost of fixes that passed (grey), the cost of jobs that failed (hatched) and the margin kept (white), with every amount written under it and the margin percentage on the right. Under it, a scorecard (rows are measures, columns are versions) with a dot on the best value in each row.
- *What each change did:* two panels, A to B (a map of the code) and B to C (a quote and a cap), each listing the before and after of verified fixes, margin, cost per verified fix and the costliest job, with the change coloured by whether it is good or bad. Below them, "Worth knowing": the plain statements generated from the same numbers, including the unflattering ones.
- *Every job, three ways:* a ledger with one row per issue and a column of bars per version on one shared scale (hatched bar and a cross: the job failed; amber tick: version C's cap; a cap past the scale is written out). Select a row to watch that job.
- *Did the quote hold up?* An interval plot: each recorded cost as a dot against the band it would have been quoted from the other jobs only, with the median marked. Filled dot: inside; red ring: outside.

**Dials ("What if the price or the cap were different?").** Two labelled sliders (markup 0 to 100%; spending cap 50 to 150% of the quoted top), each with a worked example in words ("at 50%, a fix quoted up to $0.129 is billed $0.193") and the recorded setting marked on the track. The price stays the quoted top times (1 + markup); the cap only limits what version C may spend.
- Three headline numbers (billed, model cost, margin) with the change against the recorded settings.
- *Where the cap starts to cost money:* version C's margin at every cap setting, on real axes, with the region where some job is cut off shaded, the recorded and current settings marked, a hover that names the jobs cut off at that cap, and click-to-set. Dots inside the plot show the lowest cap at which each job still finishes (filled: a fix that passed; ring: a job that failed). A sentence above the chart says in words what the current setting does.
- *The three versions at these settings:* the same bars as the Proof screen, recomputed.
- *Each job at these settings:* a table with a margin bar per job (white: kept, red: lost), changed rows marked with an amber edge, and a switch to show only the rows that changed.

Two palettes, **Black** (the default, whatever the visitor's system setting) and **White**, switchable in the header and remembered per browser. The terminal and the panels stay dark in both.

## What is real on the stage, and what is staged

The terminal shows the real output of `margin quote` and `margin run` for that run (`cli_lines()` in `src/margin/bench/console.py` builds them with the commands' own format strings), then the run's own event log. The CLI does not print the event log itself; the window shows it under a rule labelled `events · runs/<run_id>/events.jsonl`. The receipt is the real receipt's fields in its own wording; a test pins that `receipt_parts()` matches what `render_receipt()` writes. For versions A and B the receipt notes that the price is set at report time, which is what the real receipt file says. The animation, and the timing of what appears when, are staged; the numbers are not.

## What the numbers say today (so nobody is surprised)

From the committed ledger (12 evaluation issues, one run each per version):

| | Verified | Margin | Most any job cost |
|---|---|---|---|
| A: flat price | 8 of 12 | 13% | $0.303 |
| B: adds code-graph context | 11 of 12 | 64% | $0.206 |
| C: adds a quote and a cap | 9 of 12 | 63% | $0.176 |

The Proof screen says, without softening: no version C job finished over its cap (0 of 12); **version B verified more issues than version C (11 against 9)**; and of the three jobs version C did not verify, all three ran into the 30-call limit, none was stopped by the cap, and two had already been moved to the cheaper model. The text is computed (`reading()` in `console.py`), so if later runs change the numbers, the text changes with them. Do not edit the generated HTML or add hand-written claims to the template.

`marshmallow-2249` is the best story in the film: the fix passed the bug's own tests and broke another test, the verifier caught it, and nothing was billed. The Verify chapter shows the real test id, the big numeral ends on a red loss, and the receipt is stamped NOT BILLED.

## The Dials screen is an exploration, not a result

It replays the *recorded cumulative spend* of each run and asks where the run would have ended under a different cap (it stops before the first call that would pass the cap). A stopped run is assumed not to verify. It does **not** model that a different cap would also change when the governor switches model, which changes what the agent does. With that caveat, the data shows a cliff below the quoted top and a plateau above it: at today's settings the margin is $1.97; with a cap at 75% of the quote it would be $1.99; at 50% it falls to $1.05.

**Do not put a dial result in `EVIDENCE.md`, the demo script, the README or a post as a finding.** It is a way to look at the recorded data, and the page says so.

## What was verified

On a fresh copy of the repo at `ecc86a6` with this patch applied:

| Check | Result |
|---|---|
| Patch | `git apply --check` clean |
| Whole suite | 345 passed: the 300 existing tests plus 45 new ones in `tests/test_console.py` |
| `ruff check src tests scripts` | clean |
| `snapshot-replays` on the real `runs/` | 40 runs (the 36 evaluation runs plus the 4 drills); refuses and names the run if a shown run has no event log |
| `console`, `console --check`, `report --check` | write, then up to date; regeneration is byte-identical |
| Quote explanation | for all 12 version C jobs the three nearest past jobs reproduce the stored quote's median exactly; if they ever do not, the page leaves the explanation out instead of showing a different one |
| Chart data | tests pin the before-and-after rows (including that the margin points are the difference of the percentages shown) and that the quote plot's 14 of 16 equals the coverage the report states |
| Receipt and CLI lines | tests pin that the receipt fields equal what `render_receipt` writes and that the command lines use the commands' own formats |
| Dials | the displayed billed, cost and margin match an independent Python calculation at 9 dial positions and equal the ledger totals at the recorded settings (zero rows flagged as changed) |
| Scripted pass in Chromium (Playwright) at 1440 px | first-load autoplay across the chapters; pause and play; Space and arrow keys; chapter jump; the receipt and stamp; the end card and Play again; job picker; version switch keeps the issue and removes the cap in A; the failing job's regression and NOT BILLED; a failure drill's recovery in the log; Proof: three bar rows, cost segments visible, a best value marked in the scorecard, both change panels, 12 ledger rows, 16 quote rows with 2 outside, a ledger row opens its job; Dials: the headline numbers, a low cap names the jobs it cuts off, the help text follows the slider, changed rows are marked and filterable, reset returns to recorded, the chart hover shows a tooltip and a click sets the cap; palette persists across reload |
| Reduced motion | shows the finished state without playing; Play then starts the film |
| iPhone 13 emulation | no horizontal overflow on any screen; the film stacks (bar, chapter card, terminal, receipt); the Proof bars, ledger and quote plot and the Dials chart redraw at phone width; no console errors; no external requests |
| Contrast | computed for the colour pairs the page uses in both palettes: text at least 4.5:1 on every surface it sits on, bar fills and chart marks at least 3:1 |
| Output scan | no absolute paths, email addresses or key-shaped strings in `console.html` or `replays.json` |

**Not verified:** a real phone, screen readers, and any browser other than Chromium (the page uses CSS container queries, `color-mix` and `backdrop-filter`, which current Safari and Firefox support, but it was not run there).

## Design decisions you may want to know

- **Everything is computed from the ledger.** The flat price, margins and verified counts come from `report.py`, so the console and `results.md` cannot disagree. The picture at any moment of the film is a pure function of one clock, so pausing, jumping and replaying are just changes to that clock.
- **Safe by construction.** The data sits in a `<script type="application/json">` block with every `<` written as `<`. The page script only ever sets `textContent` (issue titles are split on backticks into text and `<code>` elements by DOM calls, never parsed as HTML). Tests cover both, including a task id of `</script><script>alert(1)</script>`. Header links keep only http(s) and relative paths; `javascript:`, `data:` and scheme-relative links are dropped.
- **Replays hold only what is shown:** turns (cost, model, tool names) and governor, retry, recovery and restart marks. No tool arguments, tool output, model text or free-form errors; absolute paths in a governor reason, verdict or receipt line become `<path>`.
- **The quote explanation uses the quoter's own distance.** `neighbours()` calls `Quoter._distance`, which is private because `quote.py` has no public one. That file was left alone, because the measured runs were made with it.
- **A restart is read from the log.** A second `features` event in a run's event log is drawn as "restarted from its checkpoint"; only the resume drill has one, and it carries `resumed:true`.
- **Governor thresholds on the page come from `Settings()` defaults** (60%, 85%, 30 calls). These runs used the defaults.
- **No chart library.** The bars, ledger and interval plot are plain DOM with percentage widths; the Dials line chart is SVG redrawn at the container's real width, so its text stays the same size on every screen.
- **No fonts, no CDN, no framework, no three.js.** System fonts and plain DOM. Three.js was considered and left out because nothing here needs a third dimension, and vendoring it would add about 600 KB to a file whose point is that it is small and loads nothing from outside.

## Steps

- [ ] **Step 1: Apply the patch and check**

```bash
cd ~/Desktop/margin
git apply --check docs/superpowers/plans/addendum-4-console.patch
git apply docs/superpowers/plans/addendum-4-console.patch
uv run pytest && uv run ruff check src tests scripts
```

Expected: everything passes. If `--check` fails because `src/margin/cli.py` or the `Makefile` moved, use `git apply --reject` and place the hunks by hand. Both are additive: three new functions and two sub-parsers in `cli.py`, one added line in `make verify`.

- [ ] **Step 2: Build the replay snapshot and the page from the real runs**

```bash
uv run margin snapshot-replays
uv run margin console
uv run margin console --check
```

`snapshot-replays` reads each run's `runs/<run_id>/events.jsonl` for the runs in `docs/evidence/ledger.jsonl`, so `runs/` must still be on this machine (it is git-ignored). `console` also reads `bench/tasks.toml` and `bench/issues/*.md` for the issue titles and links.

If the benchmark produced newer rows in `runs/ledger.jsonl` that you want on the page, run `uv run margin snapshot-ledger` **and `uv run margin report`** first: the console is computed from the committed snapshot, and `make verify` also checks `docs/results.md` against it.

- [ ] **Step 3: Look at it before committing**

```bash
open docs/console.html
```

Check by eye: let the first-load film play once; jump to the last chapter and watch the receipt land; open `marshmallow-2249` and play it to the end; try version A on the same issue; replay one failure drill; open Proof and Dials and move both sliders; switch to White; narrow the window. If anything looks wrong, say what and fix the template (`src/margin/bench/console_page.html`), then regenerate. Never edit `docs/console.html` by hand: `make verify` will fail on it.

- [ ] **Step 4: Optional header links**

`docs/evidence/links.json` is optional and adds links to the header. Use only URLs that already exist and are public (http, https or a relative path):

```json
[
  {"label": "Source", "href": "https://github.com/JemIIahh/margin"},
  {"label": "Evidence", "href": "../EVIDENCE.md"}
]
```

Add the published Entire checkpoint and the neatlogs trace only if those links are already public. Do not create a link to anything that is not.

- [ ] **Step 5: Mention it in the docs, then commit**

Add one line to the README's list next to `receipts.html`: "`docs/console.html`: a black-and-white replay of the recorded runs (one job from quote to bill, the three versions side by side, and a what-if on markup and cap), generated by `uv run margin console`." Add the same line under the evidence list in `EVIDENCE.md`, and say there that the Dials screen is an exploration of recorded spend, not a measured result.

```bash
make verify
git add src tests Makefile README.md EVIDENCE.md docs/console.html docs/evidence/replays.json docs/evidence/links.json docs/superpowers/plans/addendum-4-console.*
git commit -m "feat: staged console that replays the recorded runs from the ledger"
```

(Leave out `docs/evidence/links.json` if you did not create it. Do not push; the owner pushes.)

- [ ] **Step 6: Use it in the demo, if it helps**

The best demo beat is the film: open `moreitertools-1284`, let it play, and point at the bar splitting into cost and margin. Then open `marshmallow-2249` and play it to the end to show the regression the verifier caught. A screen recording of the page is also the easiest way to show it to judges (see below). Only change `docs/demo-script.md` if you re-record the demo; do not rewrite numbers by hand.

## How a visitor can open it

`docs/console.html` is one self-contained file. Anyone with the repo can open it in a browser. GitHub shows `.html` files as source, not as a page, so a judge browsing the repository sees code unless the page is served. The two ways to serve it are GitHub Pages on the `/docs` folder, or a screen recording of the page. **Both are the owner's decision**: do not change the repository's settings and do not push. If the owner turns Pages on, the page needs nothing else, because it loads nothing from outside.

## Things to remember

- **Do not hand-edit generated files.** `docs/console.html` and `docs/evidence/replays.json` are outputs; `make verify` fails if they are stale.
- **The page is only as fresh as its inputs.** After any new live run you want shown: `snapshot-ledger`, `report`, `snapshot-replays`, `console`, in that order.
- **It makes no claim the ledger does not support.** If a number surprises you, the cause is in the ledger, not the page: trace it with `jq` on `docs/evidence/ledger.jsonl`.
- **Do not describe this page as a product UI.** It replays benchmark runs. A product UI would take an issue and return a quote; this page does neither, and `EVIDENCE.md` should keep saying "replay".
