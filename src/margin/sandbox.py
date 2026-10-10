"""One worktree per run: confined file tools, git helpers and a scrubbed pytest runner.

The agent never gets a shell. File tools resolve every path inside the worktree and refuse .git.
Subprocess environments are rebuilt from scratch so API keys cannot reach repository code.
Network access is not blocked (vetted tasks need none); evidence docs state this limit.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

DEFAULT_EXCLUDES = ["__pycache__/", "*.pyc"]


class PathEscape(Exception):
    pass


class EditError(Exception):
    pass


class SuiteTimeout(Exception):
    pass


class Sandbox:
    def __init__(
        self,
        root: Path,
        venv_python: Path,
        pythonpath: list[str],
        home: Path,
        test_timeout_s: int = 120,
    ):
        self.root = Path(root).resolve()
        self.venv_python = Path(venv_python)
        self.pythonpath = list(pythonpath)
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.test_timeout_s = test_timeout_s

    # --- paths -----------------------------------------------------------------
    def resolve(self, rel: str) -> Path:
        if not isinstance(rel, str) or not rel.strip():
            raise PathEscape("path must be a non-empty string")
        path = (self.root / rel).resolve()
        try:
            parts = path.relative_to(self.root).parts
        except ValueError:
            raise PathEscape(f"{rel!r} is outside the repository") from None
        if ".git" in parts:
            raise PathEscape("the .git directory is off limits")
        return path

    def relpath(self, rel: str) -> str:
        return self.resolve(rel).relative_to(self.root).as_posix()

    # --- file tools ------------------------------------------------------------
    def read_file(
        self, rel: str, start_line: int | None = None, end_line: int | None = None, max_chars: int = 20_000
    ) -> str:
        lines = self.resolve(rel).read_text(encoding="utf-8", errors="replace").splitlines()
        lo = max(1, start_line or 1)
        hi = min(len(lines), end_line or len(lines))
        numbered = "\n".join(f"{i}\t{lines[i - 1]}" for i in range(lo, hi + 1))
        if len(numbered) > max_chars:
            numbered = numbered[:max_chars] + "\n[truncated: use start_line/end_line]"
        return numbered

    def write_file(self, rel: str, content: str) -> None:
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def edit_file(self, rel: str, old: str, new: str) -> None:
        if old == "":
            raise EditError("old must not be empty")
        path = self.resolve(rel)
        text = path.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0:
            raise EditError("old text not found; read the file again and copy it exactly")
        if count > 1:
            raise EditError(f"old text matches {count} places; include more context so it matches once")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    # --- git -------------------------------------------------------------------
    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True
        )

    def git_diff(self) -> str:
        self._git("add", "-A")
        return self._git("diff", "--cached", "--no-color").stdout

    def restore_paths(self, paths: list[str]) -> None:
        if paths:
            self._git("checkout", "HEAD", "--", *paths)

    def exclude(self, patterns: list[str]) -> None:
        path = Path(self._git("rev-parse", "--git-path", "info/exclude").stdout.strip())
        if not path.is_absolute():
            path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text() if path.exists() else ""
        have = set(existing.splitlines())
        add = [p for p in patterns if p not in have]
        if add:
            sep = "" if not existing or existing.endswith("\n") else "\n"
            path.write_text(existing + sep + "\n".join(add) + "\n")

    # --- running tests -----------------------------------------------------------
    def scrubbed_env(self) -> dict[str, str]:
        return {
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(self.home),
            "LANG": "en_US.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONPATH": os.pathsep.join(str(self.root / p) for p in self.pythonpath),
        }

    def run_pytest(
        self, args: list[str], junit_path: Path, timeout_s: int | None = None
    ) -> subprocess.CompletedProcess:
        limit = timeout_s or self.test_timeout_s
        cmd = [
            str(self.venv_python), "-m", "pytest", "-q", "-p", "no:cacheprovider",
            f"--junitxml={junit_path}", *args,
        ]
        try:
            return subprocess.run(
                cmd, cwd=self.root, env=self.scrubbed_env(), capture_output=True, text=True,
                timeout=limit, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SuiteTimeout(f"tests exceeded {limit}s") from exc
