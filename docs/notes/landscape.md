# How other agents are priced (checked 2026-10-11)

The demo video says: of 11 coding agents we checked, none quotes a price before the work or bills only for fixes the
tests prove. This note is where that comes from. Sources are public docs and pricing pages as published on 2026-10-11;
enterprise contracts may differ, and the claim is "a combination we did not find", not "the first".

## Coding agents

| Product | How it bills | Price before the work | Billed only on a verified fix | Per-job spend cap | Source |
|---|---|---|---|---|---|
| Devin | self-serve quota plus on-demand credits; enterprise ACUs | no | no | partial: session limits, org and user monthly caps | [billing docs](https://docs.devin.ai/admin/billing) |
| GitHub Copilot cloud agent | AI credits metered by tokens since 1 June 2026 (legacy annual plans: a premium request per session) | no | no | no: user, org and enterprise budgets | [changelog, 2026-04-27](https://github.blog/changelog/2026/04/27/github-copilot-is-moving-to-usage-based-billing/) |
| OpenAI Codex cloud | plan allowance, then credits per token ("a typical task may use 2-15 credits") | no | no | no | [pricing](https://learn.chatgpt.com/docs/pricing) |
| Cursor cloud agents | API pricing for the selected model | no | no | no: one account-level limit | [docs](https://cursor.com/docs/cloud-agent) |
| Factory | subscription with rolling usage limits, plus prepaid extra usage | no | no | no | [pricing](https://docs.factory.com/pricing) |
| OpenHands Cloud | LLM usage at cost, or your own key | no | no | no per conversation; org and user budgets | [pricing](https://hub.openhands.dev/pricing) |
| Sweep | seat tiers plus API credits (third-party source only) | no | no | not found | unverified |
| Amazon Q Developer | per user; Java upgrades metered per line, only for jobs that return code | no | partial: failed jobs are not billed, nothing is tested | no | [pricing](https://aws.amazon.com/q/developer/pricing/) |
| Kiro | credits | no | no | no | [pricing](https://kiro.dev/pricing) |
| Google Jules | tasks per day | no | no | a task count, not a spend cap | [limits](https://jules.google/docs/usage-limits/) |
| Claude Code | seats or API tokens | no | no | yes: `--max-budget-usd` caps one print-mode run (the docs say spend can pass it) | [CLI reference](https://code.claude.com/docs/en/cli-reference) |

## Outcome pricing elsewhere, and paying on merge

- **Intercom Fin:** $0.99 per outcome; an outcome includes a customer who stops asking for help after Fin replies
  ([pricing](https://www.intercom.com/pricing)). Sierra and Zendesk also price per resolution (third-party figures only).
- **Bounty boards:** Algora pays bounties after the pull request is merged and the funder releases the money
  ([algora.io](https://algora.io/pricing), fee unconfirmed). TaskBounty, per a third-party listing, sends a funded issue
  to several AI agents, shows only fixes that pass the repository's tests, and pays on merge, $50 to $500 an issue
  ([listing](https://peerpush.com/p/taskbounty), unverified). In both, the funder sets the price.
- **Spend caps alone are not new:** LiteLLM and Helicone enforce budgets per key or time window; Claude Code caps a run.

## What Margin combines

A price learned from what similar jobs cost, quoted before any model call; a hard cap on its own spend set from that
quote, with a governor at 60% and 85% and a coach when the agent is stuck; billing only when the repository's own tests
prove the fix (the same fail-to-pass and pass-to-pass rule as SWE-bench); and a receipt per job with the quote, the
actual cost and the margin. Margin's own evidence is 12 benchmark issues, one run each, plus one live run.
