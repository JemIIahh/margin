# neatlogs findings (Task 2), 2026-10-10

Method: `scripts/hello_trace.py` runs one real model call through our provider adapter (the event's LiteLLM proxy, so the
**openai** SDK is the one auto-instrumented), with one span of each kind and one deliberately failing span. Each run was then
read back from neatlogs through its authenticated MCP endpoint (`get_trace_context`), not by eye in the dashboard.

## Setup checks
- `python -m neatlogs doctor --local` passes. `doctor --probe` passes every check: `TRACE_VISIBLE`, `TRACE_FINALIZED`,
  `HIERARCHY_VALID`, `ATTRIBUTES_VALID`, `INPUT_OUTPUT_VALID`, `METADATA_VALID`, `TYPED_TOKENS_VALID`. The key in `.env` is a
  project key (the `nlw_` ingest key would have returned 401).
- The MCP endpoint (`https://ingest.neatlogs.com/mcp`, bearer key) answers read-only calls directly. Its tools include
  `whoami`, `search_traces`, `get_trace_context`, the detections tools and the triage tools. `whoami` returns a personal name,
  so do not paste its output into a recorded session.

## What the live trace showed
| Question | Result |
|---|---|
| Span kinds | `WORKFLOW`, `AGENT`, `GUARDRAIL`, `TOOL` arrive as `workflow`, `agent_action`, `guardrail`, `tool_call`. The tree is right: workflow, then the agent turn, then the LLM, guardrail and tool spans as its children |
| LLM span | Present, named after the model (`claude-haiku`), with latency |
| Token counts on the LLM span | **First run: 0.** Cause: our adapter used `with_raw_response`, and neatlogs' openai instrumentation reads `.usage` from what `create` returns, which a raw response does not have. **Fixed** (the adapter now uses the parsed `create` and reads the proxy's cost header with an HTTP response hook). Re-run: 22 prompt + 5 completion tokens, `llm_calls: 1` |
| Cost on the LLM span or trace | **0**, because neatlogs has no price for a model called `claude-haiku`. Our own cost is on the AGENT turn spans (`margin.cost_usd`, `margin.spend_usd`) and in the ledger |
| A failing span | **First run: SUCCESS.** `neatlogs.trace` is a bare try/finally (read in the installed SDK) and never records an exception. **Fixed** in `telemetry.trace` (record the exception, set error status, set `error` and `error.message`). Re-run: that span is `ERROR`, the trace has `has_error: true` and `error_count: 1` |
| Trace status when a failure was recovered from | The trace status becomes `error` even if the run then succeeded. Expected, and useful: a recovery shows as a failed span followed by a recovery span |

## Not verified from the API (needs a look at the dashboard)
- Whether the custom `margin.*` attributes (for example `margin.spend_usd`, `margin.cost_usd`, `margin.rung`) appear on the spans:
  `get_trace_context` only returns status, model, token counts, tool name and input/output.
- Whether the trace tags (`arm:hello`, `version:v0`) can be filtered in the dashboard.
- The Claude Code MCP connection (`claude mcp add ...`, plan Steps 7 and 8) was not made, because it would store the key in the
  Claude configuration. Reading traces through the HTTP endpoint above works without it.

## Decisions that follow
- Keep the span kinds and the `margin.*` attribute names as they are.
- Every AGENT turn span carries that turn's tokens and metered cost; the benchmark's cost story is the ledger, with traces as the
  per-turn drill-down.
- Failures are marked by the shim, so `record_failure` (Task 17) renders as a failed span.
