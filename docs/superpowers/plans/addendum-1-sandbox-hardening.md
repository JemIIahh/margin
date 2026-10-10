# Addendum 1: harden host-side git in the sandbox (Task 6b)

**Source:** an automated security review of `src/margin/sandbox.py` (commit `09118cc`, Task 6). Both findings were reproduced before this fix was written.

**Apply this before Task 7.** It changes Task 6's code and adds one requirement to Task 11.

## What was wrong

1. **Case-insensitive `.git` bypass (confirmed).** macOS is case-insensitive, so `resolve(".GIT")` passed the `".git" in parts` check. In a git worktree `.git` is a *file* holding a `gitdir:` pointer, so the agent's own `write_file(".GIT", "gitdir: /somewhere")` redirected git to a directory it controlled.
2. **Host-side git ran unhardened (confirmed).** `_git` ran with the full environment (including `ANTHROPIC_API_KEY` and `NEATLOGS_API_KEY`) and honoured whatever config the redirected git dir contained. A config such as `core.fsmonitor = <script>` made the very next `git add -A` run that script.

Proof of concept, harmless payload (`touch <marker>`): through `write_file(".GIT", ...)` followed by `git_diff()`, the marker was created, so the host ran an attacker-chosen command. After the fix the same attempt stops at `PathEscape` and the marker is never created. The injected-config and planted-hook variants (which bypass the file tools, as test code could) are caught by the tamper check and raise `GitTampered` before any git command runs.

## The fix (`addendum-1-sandbox-hardening.patch`)

- `.git` is compared case-insensitively and with trailing dots and spaces stripped, plus an `os.path.samefile` check against `<root>/.git`.
- Writes and edits are refused for any path component starting with `.git` (`.gitattributes`, `.gitmodules`, `.gitignore`, ...). Reads are unchanged.
- The git directory and common directory are resolved once, in `Sandbox.__init__`, before any agent code runs, and every host git call uses `--git-dir` and `--work-tree`, so a rewritten `.git` pointer is never followed.
- Host git runs with a scrubbed environment (`GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, minimal `PATH`, no secrets) and with exec-capable config neutralised on the command line (`core.fsmonitor`, `core.hooksPath`, `core.attributesFile`, `core.sshCommand`, `core.pager`, `diff.external`), plus `--no-ext-diff --no-textconv` on `diff`.
- A SHA-256 fingerprint of the shared git config, the worktree config, the hooks and the `.git` pointer is taken at construction and checked before every host git call. A change raises `GitTampered`.

## Steps

- [ ] **Step 1: Apply and test**

```bash
cd ~/Desktop/margin
git apply --check docs/superpowers/plans/addendum-1-sandbox-hardening.patch
git apply docs/superpowers/plans/addendum-1-sandbox-hardening.patch
uv run pytest tests/test_sandbox.py
```

Expected: 30 passed (the 16 original tests plus 14 new ones). If the patch no longer applies because Task 6's files changed, apply its three hunks by hand; the behaviour above is the specification.

- [ ] **Step 2: Run everything and commit**

```bash
uv run pytest && uv run ruff check src tests
git add src/margin/sandbox.py tests/test_sandbox.py docs/superpowers/plans/addendum-1-sandbox-hardening.md docs/superpowers/plans/addendum-1-sandbox-hardening.patch
git commit -m "fix: harden host-side git in the sandbox against pointer and config injection"
```

- [ ] **Step 3: Task 11 amendment (when `run.py` is written)**

`GitTampered` is deliberately not caught by `ToolExecutor.execute`: tampering must end the run. In `execute_run`, wrap the agent call so the run is recorded as unsolved instead of crashing the batch, and skip every further git call in that case (`restore_paths` would raise again).

Add `from margin.agent.loop import AgentResult, run_agent`, `from margin.sandbox import GitTampered` and `from margin.verify import Verdict, final_verdict`, then replace the `result = run_agent(...)` block and the verdict lines with:

```python
    tampered: str | None = None
    try:
        result = run_agent(
            first_prompt=first_prompt(issue, context, task.target_tests), arm=arm,
            client=client or make_model_client(settings), meter=meter, governor=governor, executor=executor,
            state=state, prices=prices, settings=settings, faults=faults, resume=checkpoint,
            after_turn_hook=after_turn_hook,
        )
    except GitTampered as exc:
        tampered = str(exc)
        state.log("tampering", error=tampered)
        result = AgentResult("abort", 0, f"sandbox tampering detected: {tampered}")

    if tampered:
        verdict = Verdict(False, list(task.target_junit_ids), [], f"sandbox tampering detected: {tampered}")
    else:
        sandbox.restore_paths(task.test_files)  # undo any edits to protected tests before judging
        verdict = final_verdict(sandbox, prep.baseline, task.target_junit_ids, task.test_args, run_dir / "final.xml")
```

Add this test to `tests/test_run.py`:

```python
def test_tampering_ends_the_run_as_unsolved_without_crashing(tmp_path, monkeypatch):
    from margin.sandbox import GitTampered, Sandbox

    def tampered(self):
        raise GitTampered("config changed")

    monkeypatch.setattr(Sandbox, "git_diff", tampered)
    task, settings = make_task(tmp_path), settings_for(tmp_path)
    client = ScriptedClient([reply([tool_use("t1", "git_diff", {})], stop="tool_use")])
    result = execute_run(
        task, "A", settings, tasks_root=tmp_path, client=client, run_id="r-tamper", venv_python=Path(sys.executable)
    )
    assert not result.solved
    assert "tampering" in result.verdict_reason and "tampering" in result.abort_reason
```

## Residual risk (state it in `EVIDENCE.md` under "Known limits")

Replace the line "Network access is not blocked inside the test sandbox; the tasks were chosen because they need none." with:

> Test code runs as the same OS user as the harness. File tools are confined to the worktree, host-side git is hardened and tamper-checked, and subprocess environments carry no keys, but there is no OS-level isolation: a deliberately malicious test could still reach the network or read other user-owned files (on macOS, for example, via `ps`). The tasks were chosen from well-known repositories at pinned commits, and the agent only runs code in those repositories.

## Optional follow-up spike (after Task 11, only if it is cheap)

`/usr/bin/sandbox-exec` exists on this machine. A seatbelt profile that denies network access and denies file writes outside the worktree, the run's home directory and the JUnit output directory would close both limits above. It is deprecated, and the profile below has **not** been tested, so treat it as a spike: confirm `pytest` still runs normally under it (junit files are also written to the run directory, which must be allowed), keep it behind a setting, and drop it if it costs more than an hour.

```
(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write* (subpath "<worktree>") (subpath "<run home>") (subpath "<run dir>") (literal "/dev/null"))
```
