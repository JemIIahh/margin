# Curation script kept for provenance. It was run from a session scratch directory, so its HARDCODED PATHS ARE
# SPECIFIC TO THAT SESSION; adjust HERE/H/ROOT before reusing. See docs/notes/task-curation.md.
"""Stage 1: mine candidate bug-fix commits from candidate repos (git only, blobless clones, read-only).

Usage: python3 mine.py owner/name [owner/name ...]   -> writes mine/<name>.json
"""
import json
import re
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).parent / "mine"
OUT.mkdir(exist_ok=True)

FIXY = re.compile(r"\b(fix|fixes|fixed|bug|regression|crash|incorrect|wrong|broken|error|handle|avoid|prevent|raise|issue)\b", re.I)
ISSUE = re.compile(r"#(\d+)")


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


def is_test(path: str) -> bool:
    low = path.lower()
    name = low.rsplit("/", 1)[-1]
    return (
        low.startswith(("test/", "tests/"))
        or "/tests/" in low or "/test/" in low
        or name.startswith("test_") or name.endswith("_test.py") or name in ("test.py", "conftest.py")
    )


def mine(slug: str, limit: int = 3000):
    name = slug.split("/")[1]
    bare = OUT / f"{name}.git"
    if not bare.exists():
        sh("git", "clone", "--bare", "--quiet", "--filter=blob:none", f"https://github.com/{slug}", str(bare))
    log = sh("git", "log", "--no-merges", "--format=%H%x1f%P%x1f%ad%x1f%s", "--date=short", f"-n{limit}", cwd=bare)
    found = []
    for line in log.splitlines():
        sha, parents, date, subject = line.split("\x1f")
        if len(parents.split()) != 1 or not FIXY.search(subject):
            continue
        files = sh("git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--no-renames", sha, cwd=bare).split()
        tests = [f for f in files if is_test(f)]
        src = [f for f in files if not is_test(f)]
        src_py = [f for f in src if f.endswith(".py")]
        if not tests or not src_py or len(src) > 3 or not all(t.endswith(".py") for t in tests) or len(tests) > 2:
            continue
        found.append({"sha": sha, "base": parents, "date": date, "subject": subject, "tests": tests, "src": src,
                      "issue_refs": ISSUE.findall(subject)})
    (OUT / f"{name}.json").write_text(json.dumps(found, indent=1))
    return name, len(found)


if __name__ == "__main__":
    for slug in sys.argv[1:]:
        try:
            print(*mine(slug), flush=True)
        except Exception as exc:  # noqa: BLE001
            print(slug, "FAILED", str(exc)[:200], flush=True)
