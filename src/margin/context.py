"""Code context for the agent: plain search and whole-file stuffing (arm A).

The entire-graph adapter (arms B and C) is added to this module in Task 14.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from margin.procenv import setup_env

SKIP_DIRS = {"tests", "test", "docs", "build", "dist", "venv", "node_modules"}


class GraphError(RuntimeError):
    pass


def is_source(path: Path, root: Path) -> bool:
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
    files = [p for p in root.rglob("*.py") if is_source(p, root)]
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


_PATH_RE = re.compile(r"(?<![\w/.\-])((?:[\w.\-]+/)*[\w.\-]+\.py)(?!\w)")
_BACKTICK = re.compile(r"`([A-Za-z_][\w.]*)`")
_CAMEL = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")
_SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def extract_paths(text: str) -> list[str]:
    """Distinct `.py` paths in order of appearance, whatever format the graph printed them in."""
    seen: dict[str, None] = {}
    for match in _PATH_RE.finditer(text):
        seen.setdefault(match.group(1).removeprefix("./"), None)
    return list(seen)


def extract_identifiers(text: str, limit: int = 3) -> list[str]:
    """Symbol-looking names in an issue: backticked first (dotted names split), then CamelCase, then snake_case."""
    found: list[str] = []

    def add(name: str) -> None:
        if len(name) > 2 and name not in found:
            found.append(name)

    for match in _BACKTICK.finditer(text):
        for part in reversed(match.group(1).split(".")):
            add(part)
    for pattern in (_CAMEL, _SNAKE):
        for match in pattern.finditer(text):
            add(match.group(0))
    return found[:limit]


class GraphContext:
    """Thin adapter over `entire graph`. It runs locally and sends nothing to a model or the network."""

    def __init__(
        self,
        repo: Path,
        *,
        binary: str = "entire",
        timeout: int = 90,
        runner=subprocess.run,
        max_context_bytes: int = 12_288,
    ):
        self.repo = Path(repo).resolve()
        self.binary = binary
        self.timeout = timeout
        self.runner = runner
        self.max_context_bytes = max_context_bytes

    def _run(self, *args: str) -> str:
        cmd = [self.binary, "graph", *args, "--repo", str(self.repo)]
        try:
            # The graph parses untrusted repository files, so it gets a minimal environment, never our API keys.
            proc = self.runner(
                cmd, capture_output=True, text=True, timeout=self.timeout, env=setup_env(), check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise GraphError(f"entire graph timed out after {self.timeout}s") from exc
        except FileNotFoundError as exc:
            raise GraphError("the entire CLI is not on PATH") from exc
        if proc.returncode != 0:
            raise GraphError((proc.stderr or proc.stdout).strip()[:500] or f"exit {proc.returncode}")
        return proc.stdout.replace(f"{self.repo}/", "")

    def search(self, query: str, top_k: int = 6) -> str:
        return self._run(
            "search", "--query", query, "--top-k", str(top_k), "--format", "agent",
            "--profile", "full", "--max-context-bytes", str(self.max_context_bytes),
        )

    def impact(self, symbol: str) -> str:
        return self._run(
            "impact", "--symbol", symbol, "--depth", "1", "--limit", "10",
            "--format", "text", "--max-context-bytes", "3000",
        )

    def impact_size(self, issue_text: str) -> int:
        """Distinct files touched by the blast radius of the symbols the issue names."""
        files: set[str] = set()
        for identifier in extract_identifiers(issue_text):
            try:
                files.update(extract_paths(self.impact(identifier)))
            except GraphError:
                continue
        if not files:
            try:
                files.update(extract_paths(self.search(issue_text[:2000], top_k=8)))
            except GraphError:
                pass
        return len(files)
