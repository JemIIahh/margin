"""One worktree per run: confined file tools, git helpers and a scrubbed pytest runner.

The agent never gets a shell. File tools resolve every path inside the worktree and refuse .git
(whatever its case, since macOS is case-insensitive). Subprocess environments are rebuilt from
scratch so API keys cannot reach repository code. Host-side git is hardened: the git directory is
pinned at construction, git runs in a scrubbed environment with exec-capable config neutralised,
and a fingerprint of the git config, hooks and `.git` pointer aborts the run if they change.
Network access is not blocked (vetted tasks need none); evidence docs state this limit.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

DEFAULT_EXCLUDES = ["__pycache__/", "*.pyc"]

# Config that can make git execute a command. Command-line -c beats every config file.
_GIT_HARDENING = [
    "-c", "core.fsmonitor=false",
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.attributesFile=/dev/null",
    "-c", "core.sshCommand=",
    "-c", "core.pager=cat",
    "-c", "diff.external=",
]


class PathEscape(Exception):
    pass


class EditError(Exception):
    pass


class SuiteTimeout(Exception):
    pass


class GitTampered(Exception):
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
        # Pinned before any agent code can run, so a rewritten `.git` pointer is never followed.
        self.git_dir = self._ask_git("--absolute-git-dir")
        self.common_dir = self._ask_git("--git-common-dir")
        self._fingerprint0 = self._fingerprint()

    # --- paths -----------------------------------------------------------------
    def resolve(self, rel: str, *, write: bool = False) -> Path:
        if not isinstance(rel, str) or not rel.strip():
            raise PathEscape("path must be a non-empty string")
        path = (self.root / rel).resolve()
        try:
            parts = path.relative_to(self.root).parts
        except ValueError:
            raise PathEscape(f"{rel!r} is outside the repository") from None
        if any(part.lower().rstrip(". ") == ".git" for part in parts):
            raise PathEscape("the .git directory is off limits")
        marker = self.root / ".git"
        if marker.exists() and path.exists() and os.path.samefile(path, marker):
            raise PathEscape("the .git directory is off limits")
        if write and any(part.lower().startswith(".git") for part in parts):
            raise PathEscape("git metadata files (.gitattributes, .gitmodules, ...) are read-only")
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
        path = self.resolve(rel, write=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def edit_file(self, rel: str, old: str, new: str) -> None:
        if old == "":
            raise EditError("old must not be empty")
        path = self.resolve(rel, write=True)
        text = path.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0:
            raise EditError("old text not found; read the file again and copy it exactly")
        if count > 1:
            raise EditError(f"old text matches {count} places; include more context so it matches once")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    # --- git -------------------------------------------------------------------
    def _git_env(self) -> dict[str, str]:
        return {
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(self.home),
            "LANG": "en_US.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
        }

    def _ask_git(self, flag: str) -> Path:
        out = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", flag],
            env=self._git_env(), check=True, capture_output=True, text=True,
        ).stdout.strip()
        path = Path(out)
        return (path if path.is_absolute() else self.root / path).resolve()

    def _fingerprint(self) -> str:
        digest = hashlib.sha256()
        watched = [self.common_dir / "config", self.git_dir / "config.worktree", self.root / ".git"]
        hooks = self.common_dir / "hooks"
        if hooks.is_dir():
            watched += sorted(p for p in hooks.iterdir() if p.is_file() and p.suffix != ".sample")
        for path in watched:
            digest.update(str(path).encode())
            digest.update(path.read_bytes() if path.is_file() else b"\0absent")
        return digest.hexdigest()

    def assert_git_intact(self) -> None:
        if self._fingerprint() != self._fingerprint0:
            raise GitTampered("git config, hooks or the .git pointer changed while the agent ran")

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        self.assert_git_intact()
        return subprocess.run(
            ["git", "--git-dir", str(self.git_dir), "--work-tree", str(self.root), *_GIT_HARDENING, *args],
            cwd=self.root, env=self._git_env(), check=True, capture_output=True, text=True,
        )

    def git_diff(self) -> str:
        self._git("add", "-A")
        return self._git("diff", "--cached", "--no-color", "--no-ext-diff", "--no-textconv").stdout

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
        # --rootdir pins test ids to the repo. Without it pytest walks up to the nearest config file, which for a
        # repo with none is the host project's, and every junit classname gets the worktree path prefixed.
        # --continue-on-collection-errors: by default one unimportable test module aborts the whole run and
        # blanks every other result. Report it as one failed entry and judge the rest.
        cmd = [
            str(self.venv_python), "-m", "pytest", "-q", "-p", "no:cacheprovider",
            f"--rootdir={self.root}", "--continue-on-collection-errors", f"--junitxml={junit_path}", *args,
        ]
        try:
            return subprocess.run(
                cmd, cwd=self.root, env=self.scrubbed_env(), capture_output=True, text=True,
                timeout=limit, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SuiteTimeout(f"tests exceeded {limit}s") from exc
