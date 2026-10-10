# Atira RFQ challenge agent

A model-directed browser agent that reads tender documents, resolves current
specifications, checks ERP prices and stock, finds authorized discounts in mail,
and prepares and submits a signed bid through the tender portal.

## Install and test

Requires Python 3.11+.

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[test,rfq]'
.venv/bin/python -m pytest -q
.venv/bin/python -m hackathon_toolkit.rfq.runtime --help
.venv/bin/python scripts/package_rfq.py
```

The last command creates `dist/rfq-agent.tar.gz`. The sandbox manifest installs
pinned dependencies from `requirements-rfq.txt`. Installation does not require
local model weights, a search service, or an API server.

See [the RFQ agent guide](docs/RFQ_AGENT.md) for local scouting, browser setup,
runtime configuration, evidence handling, pricing rules and limitations.
Run `scripts/rehearse_rfq.sh` for a local GPT-6 Luna rehearsal against the Atira
practice sites. Use `scripts/rehearse_rfq.sh --public` to package the agent and
queue a public Atira test run using the supplied model proxy.
For local scouting, `rfq-agent --model gpt-6-luna` uses `OPENAI_API_KEY` and fails
early if the key is missing. Public Atira runs still use the supplied model proxy.
The runtime reads configuration from environment variables and loads a local `.env`
file automatically; copy `.env.example` to `.env` and add secrets such as
`OPENAI_API_KEY` there. `.env` is ignored by git. `.env.example`
contains local proxy defaults, and is not loaded automatically.

The manifest requests four independently recorded browser windows. The coordinator uses
`research` to run tender, specification, ERP and email specialists concurrently, with
separate prompts, exclusive browser ownership, cited fact sharing and direct messages.
All specialists can log in and inspect navigation immediately. ERP matching awaits the
current specification; exact-reference email searches await the tender reference. The
coordinator reconciles findings and handles calculation, bid entry and signing.
Use `rfq-agent --sequential-checks --eligibility-first` for the optional sequential diagnostic
rehearsal. The default command investigates the full task using specialist research. Local artifacts include `browsers.html`, screenshots, `actions.jsonl`, `run.json` and `progress.json`.
The browser viewer and progress log show ten evidence-linked milestones, remaining stages,
agent activity and dependency waits. Model/Clef timings measure overhead; exact remaining
browser actions cannot be predicted. Finalization begins with five minutes remaining.
Clef assesses popups, required steps, login, errors and human verification. Optional
unrelated surveys are assessed and dismissed through model-selected observed controls;
Clef suggestions are advisory. Confirmed CAPTCHA creates a human handoff
in `run.json` and stops the affected investigation. Other research workers continue.
Review and receipt validation must pass; only the platform verdict confirms eligibility.
See the [current diagnosis](docs/RFQ_DIAGNOSIS.md) for observed failures and live-run evidence.

The experimental branch includes a [paired browser-use navigation probe](docs/BROWSER_USE_EXPERIMENT.md)
for comparing the existing loop against browser-use on generated stock lookups.

## Code

- `src/hackathon_toolkit/rfq/runtime.py`: model-directed tool loop and submission validation.
- `rfq/browser.py`: provided-browser interaction and document reading.
- `rfq/clef.py`: hosted Clef decisions.
- `rfq/evidence.py`: observations and citations.
- `rfq/models.py`, `rfq/resolution.py`, `rfq/pricing.py`: validated facts, business rules and Decimal pricing.
- `tests/test_rfq_*.py`: RFQ regression tests, including an opt-in browser smoke test.
- `scripts/package_rfq.py`: submission archive containing only RFQ source and required metadata.

The speculative general-purpose document toolkit, its demos and its optional
integrations have been removed. The package name remains `hackathon_toolkit`
so existing RFQ commands and the submission manifest continue to work.
`config.py` is temporarily retained because it has concurrent edits; the RFQ
runtime does not import it, and it is excluded from wheels and submission archives.

## Challenge documentation

- [Agent documentation index](https://ehl-challenge.atira.ai/llms.txt)
- [Getting started](https://ehl-challenge.atira.ai/start)
- [RFQ rules and answer format](https://ehl-challenge.atira.ai/challenges/rfq.md)
