"""Append-only event log plus an atomic per-turn checkpoint under runs/<id>/."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from margin.pricing import SpendMeter, Usage


class CorruptCheckpoint(Exception):
    pass


def _digest(messages: list) -> str:
    blob = json.dumps(messages, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


class RunState:
    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "events.jsonl"
        self.checkpoint_path = self.dir / "checkpoint.json"

    def log(self, event: str, **data: Any) -> None:
        line = {"t": round(time.time(), 3), "type": event, **data}
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, sort_keys=True, default=str) + "\n")
            f.flush()

    def events(self, event: str | None = None) -> list[dict]:
        if not self.events_path.exists():
            return []
        out = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a killed process can leave a partial last line
            if event is None or row.get("type") == event:
                out.append(row)
        return out

    def usage_events(self) -> list[tuple[str, Usage]]:
        return [(e["model"], Usage.from_dict(e["usage"])) for e in self.events("model_usage")]

    def restore_meter(self, meter: SpendMeter) -> None:
        for model, usage in self.usage_events():
            meter.record(model, usage)

    def save_checkpoint(
        self, *, turn: int, messages: list, model: str, effort: str, rung: str, extra: dict
    ) -> None:
        payload = {
            "turn": turn, "messages": messages, "model": model, "effort": effort,
            "rung": rung, "extra": extra, "digest": _digest(messages),
        }
        tmp = self.checkpoint_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.checkpoint_path)

    def load_checkpoint(self) -> dict | None:
        if not self.checkpoint_path.exists():
            return None
        data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        if data.get("digest") != _digest(data.get("messages", [])):
            raise CorruptCheckpoint(f"{self.checkpoint_path} failed its digest check")
        return data
