"""Crash-tolerant appends for the JSONL ledger and event log."""
from __future__ import annotations

import os
from pathlib import Path


def append_line(path: Path, line: str) -> None:
    """Append one line. If a killed process left the file without a final newline, terminate that torn line first.

    Otherwise the next record would be glued onto the fragment and the whole combined line would fail to parse,
    silently dropping a complete record (which for the event log may be a cost event).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab+") as f:
        f.seek(0, os.SEEK_END)
        if f.tell() > 0:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")
        f.write(line.encode("utf-8") + b"\n")
        f.flush()
