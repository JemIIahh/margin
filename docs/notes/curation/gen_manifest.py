# Curation script kept for provenance. It was run from a session scratch directory, so its HARDCODED PATHS ARE
# SPECIFIC TO THAT SESSION; adjust HERE/H/ROOT before reusing. See docs/notes/task-curation.md.
"""Write bench/tasks.toml and bench/issues/*.md from probe results + fetched issue text. Run from the project root."""
import json
import subprocess
from pathlib import Path

H = Path("/private/tmp/claude-501/-Users-ram-Desktop-margin/428afbc1-7d7e-4b07-bb5a-0e6802f57e73/scratchpad")
ROOT = Path("<project root>")

# repo-name -> (slug, id prefix, pythonpath, test_args, deps)
REPO = {
    "cachetools": ("tkem/cachetools", "cachetools", ["src"], ["tests"], ["pytest"]),
    "toolz": ("pytoolz/toolz", "toolz", ["."], ["toolz"], ["pytest"]),
    "more-itertools": ("more-itertools/more-itertools", "moreitertools", ["."], ["tests"], ["pytest"]),
    "sqlparse": ("andialbrecht/sqlparse", "sqlparse", ["."], ["tests"], ["pytest"]),
    "tomlkit": ("python-poetry/tomlkit", "tomlkit", ["."], ["tests"], ["pytest", "pyyaml"]),
    "python-tabulate": ("astanin/python-tabulate", "tabulate", ["."], ["test"], ["pytest"]),
    "marshmallow": ("marshmallow-code/marshmallow", "marshmallow", ["src"], ["tests"], ["pytest", "simplejson"]),
    "mistune": ("lepture/mistune", "mistune", ["src"], ["tests"], ["pytest"]),
}
# (repo-name, issue number, split) in manifest order
PICK = [
    ("cachetools", 423, "calibration"), ("toolz", 602, "calibration"),
    ("more-itertools", 1304, "calibration"), ("sqlparse", 772, "calibration"),
    ("more-itertools", 1308, "evaluation"), ("more-itertools", 1284, "evaluation"), ("more-itertools", 1214, "evaluation"),
    ("sqlparse", 826, "evaluation"), ("sqlparse", 332, "evaluation"),
    ("tomlkit", 261, "evaluation"), ("tomlkit", 619, "evaluation"),
    ("python-tabulate", 241, "evaluation"), ("python-tabulate", 305, "evaluation"),
    ("marshmallow", 2249, "evaluation"), ("marshmallow", 2900, "evaluation"),
    ("mistune", 420, "evaluation"),
]


def q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def qlist(xs) -> str:
    return "[" + ", ".join(q(x) for x in xs) + "]"


pool = json.loads((H / "pool.json").read_text())
(ROOT / "bench" / "issues").mkdir(parents=True, exist_ok=True)
out = ["# The 16 benchmark tasks. Generated from mined, probed and validated bug-fix commits; see docs/notes/task-curation.md.\n"]
for name, number, split in PICK:
    slug, prefix, pythonpath, test_args, deps = REPO[name]
    matches = [p for p in pool if p["name"] == name and p["issue"] == number]
    assert len(matches) == 1, (name, number, len(matches))
    p = matches[0]
    task_id = f"{prefix}-{number}"
    text = (H / "issues_draft" / f"{slug.split('/')[1]}-{number}.md").read_text().replace("\r", "")
    (ROOT / "bench" / "issues" / f"{task_id}.md").write_text(text.rstrip() + "\n")
    out.append(
        "\n[[task]]\n"
        f"id = {q(task_id)}\nsplit = {q(split)}\nrepo = {q('https://github.com/' + slug)}\n"
        f"base_commit = {q(p['base'])}\nfix_commit = {q(p['sha'])}\n"
        f"issue_url = {q(f'https://github.com/{slug}/issues/{number}')}\nissue_file = {q(f'bench/issues/{task_id}.md')}\n"
        f"target_tests = {qlist(p['targets'])}\ntest_files = {qlist(p['tests'])}\n"
        f"test_args = {qlist(test_args)}\ndeps = {qlist(deps)}\npythonpath = {qlist(pythonpath)}\n"
    )
    print(f"{task_id:20} {split:11} targets={len(p['targets']):2} tests={p['tests']} src={p['src']}")
(ROOT / "bench" / "tasks.toml").write_text("".join(out))
print("wrote", ROOT / "bench" / "tasks.toml")
