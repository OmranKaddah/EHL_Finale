# Debugging

Start the Atira model proxy in one PowerShell terminal, then run `scripts/run-local.ps1` in another. Four Chromium
windows are visible. Open <http://127.0.0.1:8787> for the tender, specifications, ERP and mail panels, merged timeline,
dependency state, sanitized screenshots, evidence and pricing.
The dashboard is local-only and is disabled in sandbox mode. A port collision is logged without stopping the agent.

`--trace-dir artifacts/name` chooses an ignored trace directory. It contains:

- `events.jsonl`: coordinator events, shared evidence and pricing.
- `tender/events.jsonl`, `specifications/events.jsonl`, `erp/events.jsonl`, `mail/events.jsonl`: ordered redacted
  specialist events and observations, including tool failures and model usage.
- `evidence.json`: latest typed record ledger with quoted source references.
- `pricing.json`: last deterministic answer/diagnostic result and audit.
- `receipt.json`: only created after verified receipt.
- `summary.json`: final submission state and usage.
- `screen-*.png`: throttled, sanitized browser snapshots; sensitive screens are intentionally omitted.

```powershell
uv run python scripts/inspect-trace.py artifacts/name --tail 40
Get-Content artifacts/name/events.jsonl -Wait
uv run scripts/inspect-trace.py artifacts/sandbox-second-logs.jsonl --tail 40
```

Replay the event chronology using the summary script and the referenced screenshots/observations. Investigate the
first failed tool or unresolved dependency, not merely the final timeout. `model_started` without `model_usage`
indicates inference latency; `model_error` includes status but not credentials. A calculator refusal reports missing
evidence rather than assigning a zero. Repeated controls indicate navigation stagnation or session expiry.
The replay reader also accepts Atira CLI JSON log exports, reassembles split stdout lines, and detects Windows
PowerShell UTF-16 exports. CLI log snapshots may contain only a recent window; do not treat their event counts as
whole-run totals. Use official diagnostics for complete call counts and final scoring.

The local dashboard does not have to remain open. It is a live viewer, and stops when the agent exits; durable traces
remain available offline. Screenshots can contain commercial evidence even after credential masking, so keep traces
local and outside uploads. Do not use `atira scout` without piping its output when sharing terminal recordings.

## Sandbox

Use the unscored run page for live browser, stdout/stderr and final recording. `atira status <id> --json` and
`atira logs <id> --follow` work with the current login. Optional `atira mcp` provides `diagnose_run`, `run_logs`,
`run_screenshot`, `run_inputs`, `run_profile` and `run_llm_calls`. Inspect the installed CLI's help for its supported
arguments. The final private run intentionally exposes less data to teams.

The read-only helper reuses the installed CLI login over its MCP transport:

```powershell
uv run scripts/atira-debug.py list --out artifacts/atira-tools.json
uv run scripts/atira-debug.py get_run --run-id <run-id>
uv run scripts/atira-debug.py diagnose_run --run-id <run-id> --out artifacts/diagnosis.json
uv run scripts/atira-debug.py run_profile --run-id <run-id> --out artifacts/profile.json
uv run scripts/atira-debug.py run_screenshot --run-id <run-id> --at 10:00 --out artifacts/official-frame.json
```

Official frame responses may contain base64 images. Keep official source recordings local; the agent's separate
offline replay artifacts use its own masking/redaction boundary. The helper exposes no scored-submit, cancellation,
team-setting or messaging tools. An unavailable official recording is a validation gap, not proof of UI success.

Record run ID, package hash, official score/eligibility, failing stage, recording link and relevant trace times.
Never label a scouting acknowledgment or a synthetic test as a live sandbox acceptance.
