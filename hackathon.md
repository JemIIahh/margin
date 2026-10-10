# neatHack build log

## Project

- **Name:** Margin
- **Purpose:** An issue-fixing agent that quotes a price band before it works, enforces a budget while it works, and reports its margin afterwards.
- **Problem:** Agent cost per task is volatile, so agent work is hard to price. Margin makes cost a control signal and measures the result.

## Team

Solo. Registered team name: Sofer.

## Stack

- Python 3.12 (via uv), Anthropic SDK (`claude-sonnet-5-5`, `claude-haiku-5-5`)
- neatlogs SDK (traces), neatlogs MCP (trace queries from the coding session)
- Entire CLI 0.11.4 (checkpoints, refs backend) and entire-graph v0.4.0
- cfo.ai (business plan)

## Build log

### 2026-10-10

- Created the repo and enabled Entire for Claude Code before the first commit. Session-log auto-push is off until the checkpoint contents are reviewed.
- Installed the entire-graph plugin.
- Wrote the design spec (`docs/superpowers/specs/2026-10-10-margin-design.md`).
- Found that the machine's default Python (3.14) is outside neatlogs' supported range (3.10–3.13); the project pins 3.12.
- Read the organiser setup emails. Spec updated: the neatlogs SDK needs the project API key (not the `nlw_` ingest key); the Entire submission needs an accessible checkpoint link and ID, and checkpoints in public repos are public, so session logs stay unpushed until reviewed.

## Demo

Not available yet.

## Known limitations and next steps

- Nothing is implemented yet; next is the implementation plan, then M0 (see the spec).

## Submission

- Requirements confirmed from the published page: use neatlogs, Entire and cfo.ai; public repo with commits dated during the event; before/after evidence; a run showing failure recovery; building in public tagged #neatHack; demo video; submission by quote-tweet.
- Open: team-size and conduct FAQ answers are not published on the page.
