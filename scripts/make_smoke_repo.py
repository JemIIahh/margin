"""Create a throwaway local repo and manifest for the live smoke run.

Everything lands in bench/cache, which is gitignored.
"""
import shutil
import subprocess

from margin.config import ROOT

CACHE = ROOT / "bench" / "cache"
SRC = CACHE / "smoke-src"


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", "-c", "user.name=smoke", "-c", "user.email=smoke@local", *args],
        cwd=SRC, check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def main() -> None:
    shutil.rmtree(SRC, ignore_errors=True)
    (SRC / "pkg").mkdir(parents=True)
    (SRC / "pkg" / "__init__.py").write_text("")
    (SRC / "pkg" / "mathy.py").write_text("def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n")
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    (SRC / "pkg" / "mathy.py").write_text("def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
    (SRC / "tests").mkdir()
    (SRC / "tests" / "test_mathy.py").write_text(
        "from pkg.mathy import add, mul\n\n\ndef test_add():\n    assert add(1, 2) == 3\n\n\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n"
    )
    git("add", "-A")
    git("commit", "-q", "-m", "fix add")
    fix = git("rev-parse", "HEAD")
    issue = CACHE / "smoke-issue.md"
    issue.write_text("`add(1, 2)` returns -1 instead of 3. It looks like subtraction is used instead of addition.\n")
    manifest = CACHE / "smoke.toml"
    manifest.write_text(
        f'[[task]]\nid = "smoke-add"\nsplit = "calibration"\nrepo = "{SRC}"\nbase_commit = "{base}"\n'
        f'fix_commit = "{fix}"\nissue_url = "local"\nissue_file = "{issue}"\n'
        'target_tests = ["tests/test_mathy.py::test_add"]\ntest_files = ["tests/test_mathy.py"]\n'
        'test_args = ["tests"]\ndeps = ["pytest"]\npythonpath = ["."]\n'
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
