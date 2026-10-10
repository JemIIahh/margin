# Curation script kept for provenance. It was run from a session scratch directory, so its HARDCODED PATHS ARE
# SPECIFIC TO THAT SESSION; adjust HERE/H/ROOT before reusing. See docs/notes/task-curation.md.
"""Stage 3: from usable probe candidates, keep those tied to a genuine closed GitHub issue (read-only via gh)."""
import json
import re
import subprocess
from pathlib import Path

H = Path(__file__).parent
SLUG = {
    "boltons": "mahmoud/boltons", "cachetools": "tkem/cachetools", "marshmallow": "marshmallow-code/marshmallow",
    "more-itertools": "more-itertools/more-itertools", "pyjwt": "jpadilla/pyjwt", "python-tabulate": "astanin/python-tabulate",
    "toolz": "pytoolz/toolz", "sqlparse": "andialbrecht/sqlparse", "tomlkit": "python-poetry/tomlkit", "packaging": "pypa/packaging",
    "pyparsing": "pyparsing/pyparsing", "mistune": "lepture/mistune", "python-sortedcontainers": "grantjenks/python-sortedcontainers",
    "tomli": "hukkin/tomli", "jmespath.py": "jmespath/jmespath.py", "humanize": "python-humanize/humanize",
}
CACHE = H / "gh_cache.json"
cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}


def issue(slug: str, n: str):
    k = f"{slug}#{n}"
    if k not in cache:
        p = subprocess.run(
            ["gh", "api", f"repos/{slug}/issues/{n}", "--jq",
             "{n:.number,pr:(.pull_request!=null),state:.state,len:(.body//\"\"|length),title:.title,user:.user.login}"],
            capture_output=True, text=True,
        )
        cache[k] = json.loads(p.stdout) if p.stdout.strip() else {"err": p.stderr.strip()[:80]}
    return cache[k]


pool = []
for f in sorted((H / "probe").glob("*.jsonl")):
    name = f.stem
    for line in f.read_text().splitlines():
        r = json.loads(line)
        if not r["ok"]:
            continue
        body = subprocess.run(
            ["git", "--git-dir", str(H / "probe-cache" / "shared" / f"{name}.git"), "show", "-s", "--format=%B", r["sha"]],
            capture_output=True, text=True,
        ).stdout
        refs = sorted(set(re.findall(r"#(\d+)", body)) | set(re.findall(r"[Ii]ssue[ #]*(\d+)", body)), key=int)
        for n in refs[:4]:
            info = issue(SLUG[name], n)
            if info.get("pr") is False and info.get("state") == "closed" and info.get("len", 0) >= 300:
                pool.append({**r, "name": name, "issue": info["n"], "issue_title": info["title"], "issue_len": info["len"]})
                break
CACHE.write_text(json.dumps(cache, indent=1))
(H / "pool.json").write_text(json.dumps(pool, indent=1))
by = {}
for p in pool:
    by.setdefault(p["name"], []).append(p)
for name, ps in by.items():
    print(f"== {name} ({len(ps)})")
    for p in ps:
        print(f"  {p['sha'][:7]} #{p['issue']:<5} len={p['issue_len']:<5} t={len(p['targets'])} s={len(p['src'])} {p['seconds']}s | {p['issue_title'][:70]}")
print("pool size:", len(pool))
