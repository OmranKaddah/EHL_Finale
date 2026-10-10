# Atira RFQ agent

An independent Python 3.12 implementation on the existing orphan branch. Qwen chooses browser actions and
documents from observations; typed evidence feeds deterministic EUR pricing; the browser enters and signs the bid.
A signed scouting acknowledgment is different from an accepted sandbox answer.

## Windows quickstart

From this directory, in PowerShell:

```powershell
uv python install 3.12
uv sync --frozen
uv run playwright install chromium
# This machine already has Atira installed; expose it in this terminal if necessary:
$env:PATH = "$env:LOCALAPPDATA\atira\bin;$env:PATH"
atira whoami
# Only if not already authenticated:
atira login
```

On a new computer, the official Windows CLI installer is:

```powershell
irm https://ehl-challenge.atira.ai/install.ps1 | iex
```

Terminal 1 (leave running):

```powershell
atira models proxy
```

Terminal 2, from the project directory:

```powershell
atira scout --env | Out-String | Invoke-Expression
uv run python agent.py --model-smoke
.\scripts\run-local.ps1
```

Watch the visible Chromium window and [local dashboard](http://127.0.0.1:8787).
The launcher also resolves the existing CLI under `%LOCALAPPDATA%` when it is absent from PATH.
It does not print scouting credentials. Traces are written beneath ignored `artifacts/` directories.

```powershell
uv run python scripts/inspect-trace.py artifacts/<session-directory>
.\scripts\test-local.ps1 -Browser
uv run python scripts/package_check.py
atira test-run . --challenge rfq --dry-run
atira test-run . --challenge rfq
atira status <run-id> --json
atira logs <run-id> --follow
```

The last command that starts a run above is **unscored**. No script executes `atira submit`, pushes Git branches,
changes team settings, or enables a paid model. A scored submission requires the user's separate approval.

## Runtime

`agent.json` installs the frozen runtime dependencies and runs `agent.py`. The sandbox connects exclusively to four
supplied CDP Chromium instances, never launches another browser, and reads the task/schema/fresh credentials from the
current-run API. A browserless coordinator assigns one runtime site to each tender, specifications, ERP and mail
specialist. Local mode requires `CHALLENGE_SCOUTING` and launches four visible Chromium instances. Site addresses and+tender values are never compiled into application code. Each browser's request filter permits only its assigned runtime+origin (the tender browser also accesses the declared submission origin).

Qwen uses `QWEN_BASE_URL` and `QWEN_API_KEY` from Atira. No personal OpenAI key is needed. Optional OpenAI-compatible
paid-provider configuration requires both `ATIRA_MODEL_PROVIDER=openai` and `ATIRA_ALLOW_PAID=1`, an explicit model,
and an Atira proxy endpoint. Do not enable it without approval. Merely having a key does not activate paid inference.

When Atira supplies `CLEF_BASE_URL` and `CLEF_API_KEY`, Clef classifies only sanitized screenshots that look like a
blocking popup or visual gate. Its result is advisory context for Qwen; it never clicks controls, navigates, solves a
CAPTCHA, or receives a credential/TAN screenshot.

Configuration: `ATIRA_BUDGET_SECONDS` (maximum 1200), `ATIRA_SUBMISSION_RESERVE` (default 180),
`ATIRA_DASHBOARD_PORT` (default 8787). Sandbox platform expiry is an additional hard bound. Local scouting credential
expiry is not the run timer. `--max-steps` limits debugging rehearsals; use the default for a full run.

## Implementation and evidence

- `src/atira_agent/multi_agent.py`: dependency-aware four-specialist scheduling, shared evidence, TAN handoff and benchmark.
- `src/atira_agent/orchestrator.py`: observation-conditioned specialist actions and bounded failure recovery.
- `src/atira_agent/business_rules.py` and `pricing.py`: dated scope, exact matches, Decimal calculations and allocations.
- `src/atira_agent/browser.py` and `submit.py`: generic visible browser operations, TAN and receipt states.
- `src/atira_agent/telemetry.py` and `dashboard.py`: redacted durable events and a nonblocking local viewer.

See [architecture](docs/ARCHITECTURE.md), [official contract](docs/ATIRA_CONTRACT.md),
[debugging](docs/DEBUGGING.md), [Windows runbook](docs/RUNBOOK_WINDOWS.md), and [known gaps](docs/KNOWN_GAPS.md).
The [rehearsal report](docs/REHEARSAL_REPORT.md) records actual commands, tests, run IDs, results and artifacts.
Passing unit tests is not a live signed bid.

Run the offline architecture comparison without credentials or browser startup:

```powershell
uv run python agent.py --benchmark
```
