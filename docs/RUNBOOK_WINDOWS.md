# Windows runbook

The repository uses PowerShell-compatible commands and OS-neutral Python paths. Run from the project directory.

1. `uv python install 3.12` then `uv sync --frozen`.
2. `uv run playwright install chromium` installs the local browser. The sandbox does not perform this step.
3. Add the existing CLI to this terminal: `$env:PATH = "$env:LOCALAPPDATA\atira\bin;$env:PATH"`.
4. Check `atira whoami`. Run `atira login` only when needed; do not print the token.
5. Terminal 1: `atira models proxy`. Hosted Qwen needs no personal provider key.
6. Terminal 2: `atira scout --env | Out-String | Invoke-Expression` then `.\scripts\run-local.ps1`.
7. Watch visible Chromium and <http://127.0.0.1:8787>. Use `--trace-dir` to distinguish attempts.
8. Run `.\scripts\test-local.ps1 -Browser`, then `uv run python scripts/package_check.py`.
9. Inspect `atira test-run . --challenge rfq --dry-run` before `atira test-run . --challenge rfq`.
10. Review `atira status <run-id> --json`, logs and official recording. Iterate on concrete failures.

For a short navigation diagnostic:

```powershell
.\scripts\run-local.ps1 -MaxSteps 24 -TraceDir artifacts/navigation-diagnostic
```

The short run intentionally may stop without signing and exits nonzero in that case. A full rehearsal uses the
default step count and 20-minute budget. Avoid rerunning just because inference is temporarily slow; inspect events.

If proxy port 8765 is busy, use the same alternate port in `atira models proxy --port 8777` and
`atira scout --env --port 8777 | Out-String | Invoke-Expression`. Optional paid inference requires explicit approval
and the configuration documented in README; no script configures or uploads a personal key.

Keep `.codex/` and `.entire/` local. Check `entire status` after commits. Do not use `entire doctor --force` to resolve
unrelated stuck sessions; it can discard uncondensable work. No force reset, history rewrite or remote push is needed.
On this Windows installation, Entire's commit-linking prompt opens the controlling terminal even when stdin is
redirected. Run `git commit` in an interactive terminal and answer its link-to-session question. Verify the resulting
`Entire-Checkpoint` trailer with `entire checkpoint list --json --no-pager`; do not disable the hook to avoid the prompt.
