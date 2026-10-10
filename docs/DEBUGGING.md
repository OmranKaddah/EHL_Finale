# Debugging

Start the Atira model proxy in one PowerShell terminal, then run `scripts/run-local.ps1` in another. Chromium is
visible. Open <http://127.0.0.1:8787> for stage, countdown, page, sanitized screenshots, actions, evidence and pricing.
The dashboard is local-only and is disabled in sandbox mode. A port collision is logged without stopping the agent.

`--trace-dir artifacts/name` chooses an ignored trace directory. It contains:

- `events.jsonl`: ordered redacted events and observations, including tool failures and model usage.
- `evidence.json`: latest typed record ledger with quoted source references.
- `pricing.json`: last deterministic answer/diagnostic result and audit.
- `receipt.json`: only created after verified receipt.
- `summary.json`: final submission state and usage.
- `screen-*.png`: throttled, sanitized browser snapshots; sensitive screens are intentionally omitted.

```powershell
uv run python scripts/inspect-trace.py artifacts/name --tail 40
Get-Content artifacts/name/events.jsonl -Wait
```

Replay the event chronology using the summary script and the referenced screenshots/observations. Investigate the
first failed tool or unresolved dependency, not merely the final timeout. `model_started` without `model_usage`
indicates inference latency; `model_error` includes status but not credentials. A calculator refusal reports missing
evidence rather than assigning a zero. Repeated controls indicate navigation stagnation or session expiry.

The local dashboard does not have to remain open. It is a live viewer, and stops when the agent exits; durable traces
remain available offline. Screenshots can contain commercial evidence even after credential masking, so keep traces
local and outside uploads. Do not use `atira scout` without piping its output when sharing terminal recordings.

## Sandbox

Use the unscored run page for live browser, stdout/stderr and final recording. `atira status <id> --json` and
`atira logs <id> --follow` work with the current login. Optional `atira mcp` provides `diagnose_run`, `run_logs`,
`run_screenshot`, `run_inputs`, `run_profile` and `run_llm_calls`. Inspect the installed CLI's help for its supported
arguments. The final private run intentionally exposes less data to teams.

Record run ID, package hash, official score/eligibility, failing stage, recording link and relevant trace times.
Never label a scouting acknowledgment or a synthetic test as a live sandbox acceptance.
