# Atira RFQ agent

The agent reads the runtime brief and website access, builds an evidence checklist,
and assigns model-directed investigations across up to four browsers. Investigators
choose their own controls, searches, pages and documents from live observations.
A coordinator audits normalized evidence, identifies gaps, and assigns follow-up
work without assuming that facts stay on the same website across scenarios.

Deterministic modules resolve dates, authority, revisions, withdrawn answers and
material matches, then calculate prices with Decimal. Complete and explicitly
partial answers pass the runtime schema and independent arithmetic checks before
the submission worker enters the configurator, verifies the actual review, handles
the current TAN, and confirms a signed receipt. Missing evidence does not become a
zero or a guessed no-bid decision. A run exits successfully only after confirmation.

This implements the workflow; it is not yet validated on the live challenge sites
or unknown private websites. See [robustness and remaining limits](docs/ROBUSTNESS.md)
and [architecture and runtime contract](docs/AGENT_SPEC.md).

## Local workflow

Put `OPENAI_API_KEY` in your local `.env`, then:

```sh
uv sync
uv run playwright install chromium
eval "$(atira scout --challenge rfq --env)"
uv run --no-sync python -m rfq_agent
```

Console output contains one short line per browser action plus progress and errors.
Investigators run sequentially by default. To debug a website independently:

```sh
uv run --no-sync python -m rfq_agent --list-sites
uv run --no-sync python -m rfq_agent --site erp --steps 60
uv run --no-sync python -m rfq_agent --site mail --steps 60
uv run --no-sync python -m rfq_agent --site mail --mission discount --steps 60 --timeout 180
uv run --no-sync python -m rfq_agent --site mail --mission baseline --timeout 60
uv run --no-sync python -m rfq_agent --site mail --mission tan --after <baseline-number> --timeout 90
```

Use the exact IDs printed by `--list-sites`. Single-site mode stays within that
website and stops after investigation, without normalization or bid submission.
Its evidence and action history are saved under `artifacts/sites/<site-id>/`;
each site has separate files. To run the full workflow concurrently, use
`uv run --no-sync python -m rfq_agent --parallel`.

`--site` alone derives a goal from the brief; it does **not** mean TAN retrieval.
Explicit missions bypass dispatch and save separate results under
`artifacts/sites/<site-id>/<mission>/`. Capture the baseline **before** requesting
a new code through the tender portal; then pass that number with `--after`.
TAN mode without a baseline cannot establish freshness after a new request.
Codes are saved only in local result artifacts, never printed in action logs.
`--goal 'your explicit objective'` bypasses dispatch for a generic investigation.
All these modes are non-submitting. Discount mode requires quoted percentage,
reference, sender, date, conditions and authority, plus a semantic applicability
audit; unknown facts remain unresolved. An audit is model judgment, not a proof
of complete mailbox coverage. Private-layout and public end-to-end reliability
remain to be measured.

The workflow can fill and sign a validated scouting bid. Scouting actions do not
count toward a score. Runtime credentials come from Atira's payload, not `.env`.
For an opt-in minimum-bid rehearsal:

```sh
OPENAI_MODEL=gpt-5-mini OPENAI_REASONING_EFFORT=medium uv run --no-sync python -m rfq_agent --eligibility --steps 80
```

This mode **submits a bid**. It reads the tender reference and complete position
list, checks that the runtime brief permits omitting every position, then enters
an all-omitted bid. It bypasses technical/pricing investigations and saves results
under `artifacts/eligibility/`. The normal package command is unchanged. Signing
captures a mailbox baseline before one request, reads a newer original code for
the exact reference in an isolated context of the supplied browser, and verifies
the review and signed receipt. A timed-out request is never clicked again.
This is not yet proof of public eligibility or private-site reliability.

Local calls default to OpenAI `gpt-5-nano` using `.env` (existing environment
variables take precedence). Override with `OPENAI_MODEL`; GPT-5 calls use
`OPENAI_REASONING_EFFORT=low` by default. In sandbox runs, calls use Atira's
`LLM_PROXY_URL/openai/v1` and the `OPENAI_API_KEY` team secret. Never upload `.env`.
Sandbox runs attach only to provided CDP browsers. To use hosted Qwen locally,
start `atira models proxy` and set `RFQ_MODEL_PROVIDER=qwen`; for Qwen submissions,
also set `agent.json`'s `models` to `["qwen"]` to request its warm-up.

## Validation and artifacts

```sh
uv run --no-sync python -m unittest discover -s tests -v
```

Tests use invented scenarios and synthetic browser pages, including a mocked-model
TAN-to-receipt flow and renamed/reordered scenario variants. Browser tests require
locally installed Chromium. They verify mechanics and formulas, not live model
navigation quality or private-site coverage.

The opt-in integration test calls the real configured model against four locally
simulated websites and checks concurrent login and source evidence collection:

```sh
RFQ_LIVE_MODEL_TEST=1 uv run --no-sync python -m unittest discover -s tests -p test_live_navigation.py -v
```

These tests incur model charges and use only invented website data. They cover
four concurrent logins, an image-rendered receipt with a slider and acknowledgment,
and a mailbox with separate message-list, reading-pane, and iframe-body gates. Observations
group verification controls by section and expose native disclosure controls.
Links and disclosures inside disabled fieldsets are blocked until their section
unlocks, and protected text is withheld from evidence observations while locked.

The workflow shares a 20-minute deadline, capped by the actual platform deadline,
and reserves time for source audit and submission. Investigations run in short
rounds while retaining browser state and notes. `artifacts/` contains selected
source evidence, normalized records, the gap checklist, validated answer, pricing
audit, investigator history, and final submission outcome. It is ignored by Git
and must be excluded from uploaded packages, along with `.env`, `.venv`, and caches.
Tests are never imported by runtime code; their invented data is not a fallback.

Dispatch allows up to 360 seconds; investigation calls allow up to 180 seconds,
within the shared deadline. Failures record phase/error type in
`artifacts/workflow.json`. Keep the Atira proxy running when using hosted Qwen.

`agent.json` stays at the package root. Setup installs dependencies with `uv sync`;
the run command executes `python -m rfq_agent`. No test or scored run is launched
by the local test suite.

Build an upload archive with `uv run --no-sync python -m rfq_agent.package`.
This writes `dist/agent.tar.gz` containing only runtime Python files, `agent.json`,
`pyproject.toml` and `uv.lock`. It excludes local keys, artifacts, documentation,
tests and caches, and checks the compressed size limit. See the
[guidelines audit](docs/COMPLIANCE.md) for findings and remaining validation.

`rfq_agent.mail` provides `latest_tan_number(page, access)` and
`get_tan(page, access, after=None, timeout_s=90)` for an already supplied browser
and one runtime access entry. It uses the shared observation/action loop
through `loop.py`. The model chooses login, unlock controls,
messages, original versions, frames and refreshes. Baselines compare highest
observed request numbers; TAN results require current source quotes and plausible
code syntax. Calls are deadline bounded and log actions without codes.
These helpers are currently standalone; the full bid submission worker still
uses its existing signing flow. Model identification of original-message provenance,
human-visible code agreement, expiry handling and arrival-to-return latency need
live validation before relying on the helpers in a scored signing flow.
