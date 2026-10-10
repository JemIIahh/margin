import subprocess
import sys
from pathlib import Path

import pytest

from margin.sandbox import Sandbox

BUGGY = "def add(a, b):\n    return a - b\n"
TESTS = (
    "from pkg.mathy import add\n\n\n"
    "def test_add():\n    assert add(1, 2) == 3\n\n\n"
    "def test_other():\n    assert True\n"
)


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "mathy.py").write_text(BUGGY)
    (root / "tests" / "test_mathy.py").write_text(TESTS)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture
def sandbox(repo, tmp_path) -> Sandbox:
    return Sandbox(
        root=repo, venv_python=Path(sys.executable), pythonpath=["."],
        home=tmp_path / "home", test_timeout_s=60,
    )
