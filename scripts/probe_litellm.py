"""Probe the event's LiteLLM proxy through the real adapter and the real agent loop.

1. Lists the proxy's models with its own prices (GET /model/info) and flags any model missing from pricing.toml.
2. For each chosen model, runs a short tool-calling loop (read a file, then explain it) and compares our metered
   cost with the proxy's own per-call accounting.

Costs well under a cent per model. Reads LITELLM_API_KEY and LITELLM_BASE_URL from .env and never prints the key.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import urllib.request
from pathlib import Path

from margin.config import ROOT, Settings, load_dotenv

load_dotenv()

from margin.agent.loop import run_agent
from margin.agent.tools import ProgressTracker, ToolOutput
from margin.governor import NullGovernor
from margin.model_openai import make_litellm_client
from margin.pricing import PriceTable, SpendMeter
from margin.state import RunState

FILE = "1\tdef add(a, b):\n2\t    return a - b\n"


class StubExecutor:
    """Just enough executor for the loop: serves one file and accepts any other tool call."""

    def __init__(self) -> None:
        self.progress = ProgressTracker()
        self.faults = None
        self.issue_text = "add() returns the wrong value"
        self.target_nodeids = ["tests/test_mathy.py::test_add"]
        self.read = 0

    def execute(self, name: str, args: dict) -> ToolOutput:
        if name == "read_file":
            self.read += 1
            return ToolOutput(FILE)
        return ToolOutput("ok")

    def digest(self) -> dict:
        return {"diff": "", "tests": "(not run)"}


def proxy_models() -> list[dict]:
    import os

    base, key = os.environ["LITELLM_BASE_URL"].rstrip("/"), os.environ["LITELLM_API_KEY"]
    request = urllib.request.Request(f"{base}/model/info", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())["data"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", default="claude-haiku,nova-lite", help="comma separated proxy model names")
    args = parser.parse_args()
    prices = PriceTable.load(ROOT / "pricing.toml")

    print("proxy models (USD per million tokens, from the proxy):")
    for row in proxy_models():
        info = row.get("model_info", {})
        name = row["model_name"]
        mark = "in pricing.toml" if name in prices.models else "NOT in pricing.toml"
        print(f"  {name:20} in {(info.get('input_cost_per_token') or 0) * 1e6:7.3f}  "
              f"out {(info.get('output_cost_per_token') or 0) * 1e6:7.3f}  max_out {info.get('max_output_tokens')}  [{mark}]")

    failures = 0
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        if model not in prices.models:
            print(f"\n{model}: add it to pricing.toml before probing it")
            failures += 1
            continue
        client = make_litellm_client()
        meter, executor = SpendMeter(prices), StubExecutor()
        with tempfile.TemporaryDirectory() as tmp:
            result = run_agent(
                first_prompt="Read pkg/mathy.py, then say in one sentence what add() currently does.", arm="A",
                client=client, meter=meter, governor=NullGovernor(), executor=executor,
                state=RunState(Path(tmp) / "run"), prices=prices,
                settings=Settings(provider="litellm", main_model=model, fallback_model=model, max_turns=6),
            )
        ratio = meter.total_usd / client.proxy_cost_usd if client.proxy_cost_usd else float("nan")
        ok = result.stop == "end_turn" and executor.read >= 1
        failures += 0 if ok else 1
        print(f"\n{model}: {'OK' if ok else 'FAILED'} stop={result.stop} turns={result.turns} read_file_calls={executor.read}")
        print(f"   metered ${meter.total_usd:.5f} vs proxy ${client.proxy_cost_usd:.5f} (ratio {ratio:.2f})")
        print(f"   answer: {result.final_text.strip()[:140]!r}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
