# Hackathon guidelines audit — 10 October 2026

This is a code audit, not an organizer approval or proof of private-site success.
All direct links in the supplied Atira overview were fetched, including the
participant docs, leaderboard variants, OpenAPI reference, CLI and installers,
checksum, starter archive, and combined documentation. Installers were read as
resources rather than executed; no account changes or submissions were made.

## Requirements and implementation

| Requirement | Code evidence / result |
| --- | --- |
| Model chooses navigation, searches and documents during the run | `planner.run_planner` asks for a model action from each current observation. `InvestigationSession.apply` executes that selection. No fixed route traversal or corpus crawler was found. |
| No copied scenario answers, identifiers, credentials or fallback values | Runtime sources and brief supply facts. No copied public scenario values were found in runtime code. Tests contain invented data and are excluded from the upload archive. |
| Runtime brief, access, schema, deadline and submission channel | `run_contract.load_run`, main workflow, and answer validation consume the run payload. A shared deadline is capped at 20 minutes. |
| Every sandbox model call uses the platform proxy | OpenAI constructs its endpoint from `LLM_PROXY_URL`; Qwen now does the same and uses the run token, ignoring development endpoint overrides. Missing proxy fails closed. |
| Sandbox uses supplied browsers, maximum four | Manifest requests four. `browser.connect` attaches over CDP and rejects local launch when a run token is present. Tabs remain within those browsers. |
| No human assistance during execution | The solver has no approval prompt or external communication step. Developer debugging tools are separate from timed execution. |
| Helpers may parse selected sources and calculate | Document parsing follows a model-selected link/member. Normalization and independent source audit precede deterministic business resolution and Decimal pricing. |
| Website submission must be signed, not merely saved | `submit_on_site` requires verified review, TAN entry, fresh review, and a receipt. Main respects the runtime site/API submission channel. |
| Upload root manifest, regular files, compressed size <=20 MB, no secrets | `python -m rfq_agent.package` builds from an explicit runtime-file allowlist; excludes `.env`, artifacts, docs, fixtures, caches and environment; rejects symlink inputs and oversized archives. |
| Final websites and facts can change | Dispatch uses runtime IDs, source assignment can change between rounds, and navigation uses live observations. No known-route/site-role solution fallback was found. |

## Remaining limits

The reported mail run collected zero evidence. Slider execution and source quoting
still need repair and live verification; this audit does not resolve those defects.
Synthetic passes do not establish reliable source discovery, signing, or adaptation
to the private dataset. Shadow DOM, canvas controls, scanned PDFs, office formats
and unfamiliar access-form language remain capability gaps documented in
ROBUSTNESS.md. Sequential debugging also consumes more of the shared deadline.

The source-coverage gates can prevent submission when some evidence is missing.
Atira allows incomplete signed bids with independent partial credit; our support
requires enough shared evidence to calculate positions safely and is stricter
than the broadest partial-credit strategy. This is a performance limitation,
not a fair-play violation.

The OpenAI key must be configured as a team secret for sandbox execution; a local
`.env` is deliberately excluded. The model must satisfy the platform's current
pricing/allowlist. An actual sandbox test remains necessary to validate setup,
proxy connectivity, CDP behavior and an accepted signed receipt. Organizer review
is the authority on eligibility; no claim of guaranteed approval is made here.

## Authoritative references

- [Fair play](https://ehl-challenge.atira.ai/docs/fair-play.md)
- [Run contract](https://ehl-challenge.atira.ai/docs/run-contract.md)
- [Building an agent](https://ehl-challenge.atira.ai/docs/building-an-agent.md)
- [RFQ rules](https://ehl-challenge.atira.ai/challenges/rfq.md)
- [Scoring](https://ehl-challenge.atira.ai/docs/scoring.md)
- [Submitting](https://ehl-challenge.atira.ai/docs/submitting.md)
