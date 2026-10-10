#!/usr/bin/env bash
# Kill a live run mid-flight (after its first checkpoint), then resume it from persisted state.
# Pick a task that takes several turns, or the run may finish before the kill lands.
set -euo pipefail
TASK="${1:?usage: resume_demo.sh TASK_ID [ARM]}"
ARM="${2:-C}"
RUN_ID="demo-resume-$(date +%H%M%S)"

uv run margin run --task "$TASK" --arm "$ARM" --run-id "$RUN_ID" --version demo-resume &
until [ -f "runs/$RUN_ID/checkpoint.json" ]; do sleep 1; done
sleep 2
pkill -9 -f -- "--run-id $RUN_ID" || true
wait 2>/dev/null || true
echo "killed after the first checkpoint; resuming $RUN_ID"
uv run margin resume --run-id "$RUN_ID"
