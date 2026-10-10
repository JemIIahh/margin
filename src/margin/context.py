"""Code context for the agent: plain search and whole-file stuffing (arm A).

The entire-graph adapter (arms B and C) is added to this module in Task 14.
"""
from __future__ import annotations

from pathlib import Path

SKIP_DIRS = {"tests", "test", "docs", "build", "dist", "venv", "node_modules"}


class GraphError(RuntimeError):
    pass


def _is_source(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    for part in rel.parts[:-1]:
        if part.startswith(".") or part in SKIP_DIRS or part.endswith(".egg-info"):
            return False
    name = rel.name
    return not (name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py")


def grep_search(root: Path, query: str, max_hits: int = 40) -> str:
    if not query.strip():
        raise ValueError("query must not be empty")
    needle = query.lower()
    hits: list[str] = []
    for path in sorted(Path(root).rglob("*.py")):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if needle in line.lower():
                hits.append(f"{rel.as_posix()}:{number}: {line.strip()[:160]}")
                if len(hits) >= max_hits:
                    return "\n".join(hits)
    return "\n".join(hits) or "no matches"


def naive_context(root: Path, max_chars: int) -> str:
    """Arm A: stuff whole source files into the prompt, smallest first, up to a character budget."""
    root = Path(root)
    files = [p for p in root.rglob("*.py") if _is_source(p, root)]
    files.sort(key=lambda p: (p.stat().st_size, str(p)))
    chosen: list[tuple[str, str]] = []
    used = 0
    for path in files:
        rel = path.relative_to(root).as_posix()
        body = path.read_text(encoding="utf-8", errors="replace")
        block = f"### {rel}\n```python\n{body}\n```\n"
        if used + len(block) <= max_chars:
            chosen.append((rel, block))
            used += len(block)
    return "\n".join(block for _, block in sorted(chosen))
