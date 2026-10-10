# RFQ eligibility investigation — 10 October 2026

## Rehearsal run_016032d912630f20: idle browsers and mailbox blockage

The platform reported no submitted answer after 1,177.999 seconds (19m38s), with 162 model
calls. The action log contains 72 coordinator actions, 13 specification actions and 12 tender
actions. There are no ERP/email specialist actions. One attempted fact publication failed
citation validation. The runtime delayed ERP/email startup until prerequisite facts arrived;
this prevented even independent login/navigation work. The coordinator later handled mail.

Browser navigation repeatedly targeted browsers already assigned to a different origin.
A supplied browser index was ignored when page/ref was absent, defaulting to page zero.
Extra tabs preserved original blank pages. Passive screenshots and active-page selection
now reduce these display/targeting problems; blank screenshots alone do not establish idleness.

Clef produced 56 recorded assessments and 27 control suggestions. Eleven suggested references
were later selected by an agent (not necessarily successfully). Suggestions included ordinary
login/form controls, so uptake does not prove a net speedup. Recovery suggestions are now
limited to observed dialogs/interrupted actions, with explicit per-call timing and uptake metrics.
There is no controlled with/without-Clef comparison yet.

The run validated an all-omitted partial bid and requested a signing TAN. It then stalled on
the mailbox unlock, attempted a range action, and ultimately called request_human. No receipt
was recorded. Prompts now require inspecting all related unlock controls and the resulting
state, rather than repeating one gesture. No site-specific slider values or dismissal labels
are selected by code.

The previous 900-second finalization reserve left fewer than five minutes for research.
The reserve is now 300 seconds within the unchanged 1,185-second default total. The live
brief allows two-hour rehearsals but only twenty-minute scored runs; extending test duration
would not validate scored-run timing. All specialist startup is concurrent; dependencies
apply within their tasks. Progress logs/artifacts now show ten milestones and per-agent
activity so waiting, failure, partial calculation and missing facts remain visible.

## Specialist rehearsal: early handoff failure

[run_f4cfd6012c38f7d3](https://ehl-challenge.atira.ai/runs/run_f4cfd6012c38f7d3)
ended after 268.141 seconds and 49 model calls. The platform recorded quality 0 and
ineligible, with “Run exited with code 0 without submitting an answer”. The downloaded
log is `.rfq-artifacts/run_f4cfd6012c38f7d3.log`.

Clef labelled tender observation `obs-5` as human verification. The runtime immediately
ended the tender worker and retained a browser hold. On `obs-21`, Clef classified the page
as an optional distraction and the coordinator chose to dismiss the survey, but the stale
hold rejected that click. The coordinator then called `request_human`, returning
`awaiting_human`. This was an early controlled exit, not the run deadline.

The specification worker dismissed its document-display notice after one eight-second
blocked click. It also hit a false signing gate while choosing a binding-document purpose:
the guard matched the word “verbindlich” without requiring a submission action.

Corrections now make Clef classification advisory, supply a model-selected recovery-control
suggestion, pass obstruction screenshots to the navigator, and allow a cited reassessment
of a mistaken hold. A generic pre-action modal check returns new evidence when a late
popup covers the planned control. The navigator decides how to proceed. The signing guard
no longer treats the standalone binding-document adjective as a submission action.
These changes have local regression coverage; a new hosted run is still needed to measure
their effect on end-to-end completion.

## Confirmed failure

Previous rehearsal `run_8564a91ba9963580` finished **failed**, with 166 model calls,
no answer and no score. Atira reports: “Run exited with code 1 without submitting an
answer.” Its log ends with the local 1,185-second timeout during a model call. The earlier
`run_5d1664ec8cea1b87` log also ends without acceptance.

The [v6 rules](https://ehl-challenge.atira.ai/challenges/rfq.md) require the correct tender
reference for eligibility. Explicit omissions earn no position credit; partial bids still
require TAN signing. Saving does not submit. These runs failed before a scored answer
existed; the logs do not establish a wrong-reference or TAN rejection by the portal.

## Defects and fixes

- `partial_submission` parsed every observation URL as HTTP. A blank/srcdoc observation
  crashed the scan (failed-run steps 129 and 161). Non-HTTP observations are now excluded.
- Slider failures and stale refs consumed time. Keyboard endpoints/steps and checked
  values supplement mouse dragging. After a modal interrupts a gesture, re-observation
  remains necessary; the model chooses its recovery.
- `finish` accepted any nonempty tender-site quote. Review validation and an independent
  receipt assessment now distinguish drafts, TAN requests and signed confirmations.
- The manifest requested one browser. It now requests four, with stable identities,
  sequential bounded workers, per-action screenshots and a four-pane viewer.
- Logs lacked reasons and controls. Journals now link decisions, browser/page identity,
  controls, observations, results, phase and timings.
- Navigation accepted guessed paths. Supplied/observed targets are now required. Table
  and selected CSV/JSON extraction never traverse sites or choose business records.
- The first improved rehearsal exposed missing form/link evidence: observations saved only
  DOM inner text, although the model could see control values and URLs. Reference checks
  repeatedly rejected that evidence. Observations now retain visible control metadata too.
- The coordinator reused browser zero across sites despite the prompt. Four-browser runs
  now retain one model-selected origin per browser, with explicit sequential worker checks.
  Chrome for Testing's banner is informational; idle windows were blank, not broken.
- The first improved rehearsal reached review but exposed an integration error in the new
  validator: requests without tools still sent an empty tools list and auto tool choice,
  causing HTTP 400. Tool settings are now omitted for plain review calls. A hosted-model
  synthetic check accepted a matching review, rejected a saved draft, and accepted an
  explicit signed receipt. The gate was not bypassed in the failed rehearsal.
- Batched TAN entry invalidated the validated review because only single-field edits
  were recognized. TAN-only batches now preserve validation; batches containing business
  edits still invalidate it. Regression tests cover both cases.

## Validation and live evidence

Local tests run sequentially. Four real CDP browsers were exercised with two synthetic
layouts each, independent form state, table extraction, eight screenshots and four-pane
preview. This tests the adapter, not autonomous generalization to private websites.

Eligibility rehearsal: [run_a1855583bebeeeec](https://ehl-challenge.atira.ai/runs/run_a1855583bebeeeec),
package SHA-256 `6ed0db77bf78d87639b880ef9a2a5cb4643af52b0b79d9a422e97df1046627f2`.
It uses `--eligibility-first`. Platform recordings cover all four browser displays. Early
actions include model-selected login, cookie consent, tender selection, survey dismissal,
slider recovery, participation and document inspection.

This rehearsal finished **failed**, with 154 model calls and no answer/score. It reached
the actual portal review, but repeated validator HTTP 400s blocked TAN signing until timeout.
The request-format fix has passed a separate hosted-model check and will be rehearsed next.

**Eligibility is not yet confirmed.** Update this report from the next platform verdict.
No full commercial bid or private-layout generalization is claimed.

All four hosted-Qwen navigation probes passed sequentially on synthetic sites with randomized
paths and record values, two layouts and two popup variants. Each found and cited the correct
record after deterministic table extraction. See `.rfq-artifacts/navigation-probe/40efe4fd/`
for `outcomes.json`, `actions.jsonl`, evidence and four-window snapshots. This is bounded
generalization evidence, not a guarantee for unseen private sites.

Clef's text and screenshot choice API was checked through the official local proxy. Changed
page states now invoke it automatically for low-stakes visual classification, with a bounded
timeout; merely exposing an optional decision tool had left it mostly unused in earlier runs.

Rehearsal `run_079644a7f21afccb` was canceled while queued to include the TAN batch fix;
it did not execute or produce eligibility evidence.

The replacement end-to-end rehearsal is [run_7f53f80f56344321](https://ehl-challenge.atira.ai/runs/run_7f53f80f56344321),
package SHA-256 `5e013e5c0669d54fb89894fb6dc8267cedf1081625f2dde33db2de5643fabe7c`.
It runs `--sequential-checks --eligibility-first`: four bounded worker checks, then portal
review and signed partial submission. The package passed all 99 local tests, including
the real-browser tests. Atira accepted the replacement rehearsal at approximately 15:54 UTC.
At 15:56 UTC, the platform reported **queued, nine runs ahead, zero model calls**.
Its result remains pending; neither a signed receipt nor eligibility is yet claimed.
