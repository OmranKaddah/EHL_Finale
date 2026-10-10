# Atira RFQ planning agent

This repository contains the first MVP of an agent for the Atira RFQ challenge.
It asks Qwen to assign focused investigations across sites supplied by the current
run, then runs those investigators concurrently in up to four browsers. Each
investigator chooses its next action from its live page observation. The workers
share a source-quoted evidence ledger in memory.

It deliberately stops before calculating or submitting a bid. It is a planning
and evidence-gathering foundation, not a competition-ready solver. The challenge
requires the model to choose navigation and relevant documents at run time; the
MVP does not crawl all sites or use copied public-scenario answers.

## Project layout

- `agent.json` is the Atira package manifest and remains at the archive root.
- `src/rfq_agent/` contains the Python package; see [the architecture specification](docs/AGENT_SPEC.md).
- `uv.lock` pins the local and sandbox dependencies.
- `.env` is not used for challenge credentials or model calls and must remain private.

## Local scouting workflow

The package requests four browsers and uses `min(site count, browsers provided, 4)`
investigators. Start `atira models proxy` in one terminal and leave it running. In
another terminal:

```sh
uv sync
uv run playwright install chromium
eval "$(atira scout --challenge rfq --env)"
uv run --no-sync python -m rfq_agent
```

The scouting logins are for local development only; actions there do not count as
a scored bid. The agent reads credentials from the run environment and never
includes their values in model prompts or routine output.

## Package workflow

The challenge runner uses the root `agent.json`, installs with `uv sync`, and runs
`python -m rfq_agent`. A test run or submission is a separate step; inspect the
agent behavior and current Atira run status before starting one.
