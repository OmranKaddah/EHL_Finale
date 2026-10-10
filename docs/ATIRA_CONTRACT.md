# Verified Atira contract

Checked on 2026-10-10 against the official challenge, current public scouting brief, API schema and starter-kit
protocol examples. These notes deliberately contain no public tender identifiers, passwords, amounts or answers.

## Execution

- A regular-files-only gzip tarball must contain root `agent.json`; maximum compressed size is 20 MB.
- Setup argv runs in the package directory, has network, no run credentials, and five minutes. The timed run has
  Python 3.12, uv, and access only to the platform/model proxy and challenge websites. Scored RFQ time is 20 minutes.
- An unscored `test-run` may last two hours. This agent keeps its 20-minute internal budget for comparable rehearsal.
- One to four headful Chromium processes are provided; use `CDP_URLS` JSON or `CDP_URL`. Launching another browser,
  including headless, is prohibited. Local scouting may launch its own visible browser.
- Read `GET /v1/runs/current` using `x-api-key` and a custom User-Agent. Read `brief`, `access`, `submission`,
  `answer_schema`, and timestamps. API times are epoch milliseconds; credentials and token-bearing model URLs are secret.
- Use the declared submission target. RFQ requires portal configurator, email TAN, confirmation and accepted receipt.
  API submission is available only for a declared API target. HTTP 400 leaves the run open; HTTP 202 is final.
  After accepted submission the process has ten seconds to exit.

## Navigation and models

The model must choose destinations, searches and relevant documents from observations. Helpers may parse selected
pages/documents, paginate chosen result sets, fill forms, calculate and validate. Fixed site routes, broad pre-crawls,
copied scenario values and direct challenge-site API bypasses are forbidden. Private evaluation changes website
software/layout and data. The runtime discovers access and does not identify software from public selectors.

Qwen is free to participants through Atira's proxy, but has simulated ranking cost. Warm it with `models:["qwen"]`.
Official start docs use model alias `qwen`; the starter reference also shows a descriptive model name. This project
uses the documented `qwen` alias and verifies it in a real smoke call. No local model is bundled.

## Pricing refinements that override simplified summaries

The detailed runtime brief controls calculations. In particular:

- The current full revision governs requirements. Q&A technical amendments apply only to the named revision and
  requirement; withdrawn quantity replies do not apply. Usable stroke adds two revision-authorized end reserves.
- Match active material attributes exactly. No matching active material means `no_bid`; failure to finish a search does not.
- Price tiers are per-position piece quantities; stock is pooled over positions sharing a material. Set conversion
  precedes these operations. Carton ceilings change packaging cost, not bid quantity.
- **Round the FX-converted, price-unit-normalized EUR base to cents before downstream calculations.** This is distinct
  from final unit-price rounding. Approval thresholds use those undiscounted base goods, with inclusive minimums.
- The latest authorized exact-reference message no later than the scenario date supersedes older approvals.
  A failed condition does not revive an older record. Sender authority uses local part plus the current bidder domain.
- Commercial clauses affect base, base plus mass, or neither; absent groups use base-only. Setup and packaging are
  never percentage-discounted. Index validity windows are inclusive and must be date-selected.
- Shared setup uses quantity times allocation mass, and the cent rule stated in its mail. Project bonus uses marginal
  bands and aggregate HALF_UP rounding, then largest remainders with ascending position identifiers breaking ties.
- Ordinary setup can be assigned or amended per position in Q&A. It is separate from material-level defaults and
  shared pools. Q&A bonus-plan identifiers select the corresponding authorized finance record and membership.
- Final unit = clause-discounted base + clause-discounted mass +
  (ordinary setup + shared setup + cartons - allocated bonus) / pieces, rounded HALF_UP once at this final step.
  Total = sum(pieces times final rounded unit price). Rounded displayed breakdowns are never formula inputs.
- `surcharge_per_unit` includes mass plus ordinary/shared setup before discount. `rebate_total` is the entire line credit.
  Optional missing breakdowns remain blank; a known zero is explicitly zero.
- The portal supports explicit omission for partial credit, but the bid still must be signed. An omitted position
  remains relevant to any whole-order dependency needed to price submitted positions.
- In the current published workflow, requesting another TAN invalidates the previous one; validity is five minutes.
  Going back can clear later steps, and a session expiry loses unsaved entries. Runtime observations remain authoritative.

## Sources

- [Agent index](https://ehl-challenge.atira.ai/llms.txt)
- [Combined official documentation](https://ehl-challenge.atira.ai/llms-full.txt)
- [RFQ challenge](https://ehl-challenge.atira.ai/challenges/rfq.md)
- [Getting started](https://ehl-challenge.atira.ai/start.md)
- [Run contract](https://ehl-challenge.atira.ai/docs/run-contract.md)
- [Fair play](https://ehl-challenge.atira.ai/docs/fair-play.md)
- [Agent building](https://ehl-challenge.atira.ai/docs/building-an-agent.md)
- [Scoring](https://ehl-challenge.atira.ai/docs/scoring.md)
- [Packaging](https://ehl-challenge.atira.ai/docs/submitting.md)
- [CLI](https://ehl-challenge.atira.ai/docs/cli.md)
- [MCP debugging](https://ehl-challenge.atira.ai/docs/mcp.md)
- [OpenAPI](https://ehl-challenge.atira.ai/openapi.json)
- [Starter reference](https://ehl-challenge.atira.ai/starter-kit.tar.gz)
