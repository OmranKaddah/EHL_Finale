# Working submission plan — 11 October 2026

Keep the current implementation. First prove a signed minimum bid, then add
verified position data from the four websites. This plan prioritizes actual
scouting and platform runs; do not add tests under `tests/` for this work.
The initial review did not change runtime code. Implementation has since started;
read [NEXT_SESSION.md](NEXT_SESSION.md) first for current results and the active
diagnostic run. The baseline findings below describe the original review, not
the latest verification status.

This is a development document, excluded by `package.py`. Neither this document
nor the supplied workboard is an input to a running submission.

**Success has two milestones:** an accepted, eligible signed bid, followed by an
accepted bid with verified commercial/technical content. An all-omitted bid proves
the submission path; it does not establish extraction accuracy.

## Basis and current state

Reviewed all runtime modules in `src/rfq_agent`, README, AGENT_SPEC, NEXT_SESSION,
current local result summaries, the seven-page supplied workboard, and the relevant
official pages from Atira's combined documentation. Official rules take precedence
over the workboard. Its proposed order of work remains useful; its scenario facts,
old `solve() == None` diagnosis, guessed score and unscouted wizard details are not
current implementation facts or reusable answer data.

The rules allow explicit omission of unfinished positions and optional blank
breakdown fields. A signed answer with the correct reference is the eligibility
target; there is no promised score for an empty-position bid. The model must select
navigation, searches and sources at runtime. Selected-page extraction, pagination
of a selected result set, form filling, arithmetic and validation may be helpers.
Private websites and fact locations change. Sources:
[RFQ rules](https://ehl-challenge.atira.ai/challenges/rfq.md),
[scoring](https://ehl-challenge.atira.ai/docs/scoring.md),
[fair play](https://ehl-challenge.atira.ai/docs/fair-play.md).

| Area | Established | Still missing |
| --- | --- | --- |
| Browser tools | Login, native gates, selected frames/documents, source quotes implemented; some public access success recorded | Reliable relevant navigation across complete missions |
| Tender | Public original position-list extraction succeeded | Complete current Q&A resolution and verified wizard completion |
| Customer | Access form reached in prior diagnostics | Governing original specification and complete required attributes |
| ERP | Public access-only success recorded in handoff | Matching materials, valid prices and usable stock |
| Mail | Original TAN extraction succeeded once in about 110 seconds | Fresh post-request TAN timing; latest authoritative discount mission |
| Minimum bid | Registration with source-backed email and all omissions reached the totals form locally | Actual accepted signed receipt; review and fresh TAN flow still unverified |
| Platform | Runtime setup, proxy/CDP, fresh-account enrollment and original position-list extraction verified in diagnostics | Eligibility and field-level score; follow active run in NEXT_SESSION |

The original minimum-bid failure lost useful history after a browser error.
Rehearsals now retain timestamped source/form/history checkpoints; the contact
registration fix has passed locally. No signed receipt is confirmed at handoff.
Historical synthetic passes are not evidence of a working public submission.

## 1. Get through bidder registration and the actual wizard

Primary files: `eligibility.py`, `submission.py`, `__main__.py`.

Extract a small typed submission context from the runtime brief: tender reference,
registered company, tax identifier, other supplied bidder details, and submission
instructions. Keep bidder identity separate from the calculated answer. Cite the
brief for each identity value; if a required field is absent, let the model find
the authorized source instead of inventing it.

Keep the existing field-meaning audit and verify its public behavior. The model
should map the currently observed form fields to the appropriate identity/answer
values, then let a helper fill that selected mapping. Read values back against
their labels before advancing. Correct wrong prefilled values. A successful click
is not a completed step: inspect page errors and verify advancement or saved state.
Do not count an omission until the UI shows that position is omitted.

Use a short stage-specific goal inferred from the current screen: registration,
answer entry, omissions, review, signature or receipt. These are business stages,
not fixed URLs, German labels, step numbers or a predetermined click sequence.
The model still selects every navigation control. Invalidate downstream progress
when an observed back/reset action discards it.

Apply unchanged-action protection to normal submission actions as well as screen
inspection. Currently `progress.record()` is called only for inspection in this
worker. After repeated identical validation failures, stop that diagnosis and
preserve the form observation rather than spending the whole run on it.

Run one focused live registration attempt first. Continue the same session into
the remaining wizard as soon as the actual form advances. Save screenshots at
stage changes and errors, with action purpose and non-secret field mapping.

**Exit:** correct runtime bidder data accepted; every required position omission
is visible in the actual review; reference, decision and total agree with the
validated minimum answer. Do not label it submitted yet.

## 2. Complete one fresh TAN-to-receipt flow

Primary files: `submission.py`, `mail.py`, `documents.py`.

Reuse `SigningAttempt` and the already integrated mail helpers. Authenticate and
prepare the mailbox before the time-sensitive signing stage, keeping the selected
mail browser context alive. Capture the highest relevant observed request number
immediately before the tender's signing request. Reobserve the tender form after
baseline retrieval so stale target IDs cannot be reused.

Request once through the model-selected tender control. Read a newer original
message for the exact tender reference, bind its request number to its body, and
exclude preview/draft values. Retain request/message evidence across frame changes.
Only poll/refresh the selected mailbox when awaiting delivery; never request a code
there. Retry retrieval of the same request after a read failure; an ambiguous
request click must not generate another request automatically.

Enter the verified code, check the live review, sign once, handle the authorized
confirmation dialog and capture the accepted receipt. Diagnose actual review
labels/values rather than requiring the UI to print internal enum spellings.
Never treat a saved draft or a click result as acceptance.

Measure baseline time, request-to-code and request-to-receipt. Aim to return the
code within 60 seconds of observed arrival and finish inside its five-minute
validity. The existing 110-second extraction without a baseline does not pass this.

**Exit:** one unattended public scouting run reaches a signed receipt. A second
fresh run exercises baseline freshness. Scouting receipts do not count as a score.

## 3. Run the minimum package in Atira immediately

Primary files: `package.py`, `agent.json`, `run_contract.py`, `model.py`.

After the first local receipt, run a diagnostic platform rehearsal before adding
more business scope. Build with the explicit package allowlist, stage that archive
in an isolated directory, and give the rehearsal manifest the minimum-bid entry
point. The current normal manifest starts the full workflow; do not accidentally
test a different mode from the one just verified locally.

Verify the provider key exists as a team secret, calls go through the platform
proxy, supplied CDP browsers attach, and no local browser starts. Use the run's
brief/access/schema/deadline. Keep the scored 20-minute cap even though diagnostic
platform runs can last longer. Exclude local artifacts, workboard, docs and keys.
See [run contract](https://ehl-challenge.atira.ai/docs/run-contract.md) and
[submitting](https://ehl-challenge.atira.ai/docs/submitting.md).

Use run status, diagnostic logs, screenshots and the returned answer/score to
confirm eligibility. Record the package hash, configuration, time, cost and failure
stage. Repeat the same candidate to check reproducibility; do not hide failed runs.
This is a test run, separate from scored publication.

**Exit:** a platform test reports an accepted eligible answer. Preserve this working
package as the baseline while improving quality.

## 4. Collect the business facts in focused missions

Primary files: `planner.py`, `documents.py`, `missions.py`, `investigation.py`,
`records.py`, `resolution.py`.

The following are starting roles on the public scenario, not a hardcoded routing
table. Let runtime descriptions and discovered references redirect work when
private websites store the information elsewhere.

| Starting source | Required result | Evidence that establishes completion |
| --- | --- | --- |
| Tender | All position IDs, requirements, units, original quantities; applicable dated Q&A, withdrawals, technical amendments and commercial keys | Selected original documents and completed relevant Q&A result set; effective quantities derived from dates, not row/answer-number order |
| Customer | Revision marked current; original requirement attributes, catalog groups, set conversion and stroke interpretation | Revision status plus original text for each needed requirement; usable stroke linked to the required technical release |
| ERP | Active exact attribute match; free stock, lead times, valid price scales, currency/price unit, carton size and required masses/index keys | Selected candidate/condition/stock records with dates and status; summary totals and look-alikes distinguished |
| Mail — commercial | Latest exact-reference authorized approval and conditions; the technical/commercial records referenced by the chosen positions | Original body plus sender, date, reference and key; relevant inbox/archive candidates checked for supersession |
| Mail — signing | New original code for this request | Separate baseline/request/body validation, only during signing |

Debug one explicit mission at a time and compare the saved result with the selected
original UI source. TAN evidence never completes a discount mission. Login success,
document titles and source counts never establish business completion.

For a document selector, observe which lower/adjacent pane or frame changed; read
that selected content before changing documents. Target scrolling at the chosen
container/frame: current `scroll` only sends a mouse wheel at the existing cursor
position, which need not be over that pane. Use the screenshot of the relevant
region when rendered image text is absent from accessibility data.

Let the model select source blocks/result sets once; helpers can capture their
exact text, parse rows and page that selected collection. Avoid repeated model
transcription of long quotes or one navigation decision per extracted field.
Maintain source identity, dates and coverage boundaries. Do not crawl unrelated
pages. Allow recovery out of an irrelevant frame; unrelated locked panes must not
prevent extracting an already accessible selected source.

Normalize each completed source into the existing record contracts and merge it
incrementally. Give subsequent missions concrete missing keys/attributes and their
source references instead of another broad request to investigate the whole RFQ.
Preserve incomplete facts as unresolved, and give narrow follow-up objectives.

**Exit:** original evidence from all four public sites supports one complete offered
position or dependency group. The model selects the smallest tractable group at
runtime. This may require facts for other positions because prices depend on order
discount thresholds, shared stock, setup pools and project bonuses.

## 5. Make verified partial work survive to submission

Primary files: `investigation.py`, `resolution.py`, `pricing.py`, `answer.py`,
`__main__.py`.

Fix these concrete implementation issues before relying on a quality bid:

- `InvestigationState.review()` clears the current answer before attempting the next
  normalization. Retain the best validated candidate when transport or an unrelated
  follow-up fails. Invalidate any candidate whose dependencies new evidence
  contradicts; a saved answer is not permission to ignore a governing amendment.
- `Resolver.resolve()` requires global scenario/tender/spec/Q&A/approval/bonus
  coverage and resolves every position before partial pricing can begin.
  `InvestigationState.review()` then rejects all declared bundle gaps. Replace that
  blanket gate with explicit dependencies for the included fields/positions while
  preserving global dependencies where they actually affect those values.
- `answer.validate_answer()` unconditionally indexes all four optional breakdown
  fields. Validate them only when present. Blank remains unanswered, not zero.
- `pricing._calculate()` reports only mass surcharge in `surcharge_per_unit`.
  The scoring definition includes ordinary and allocated setup per piece too:
  report `round_half_up(mass_surcharge + setup / quantity)`. Keep packaging and bonus
  separate and retain unrounded components in the final unit-price formula.
  [Official breakdown definition](https://ehl-challenge.atira.ai/docs/scoring.md).
- The full workflow submits nothing when no quality answer survives; it does not
  invoke the minimum-bid path. Keep a runtime-validated omission candidate available
  early, and select it at the collection cutoff if there is no better valid answer.
  Do not restart discovery from scratch when signing time is nearly gone.

Keep Decimal arithmetic and deterministic authority/date/revision resolution.
An optional reporting field may be blank, but missing an input to the final unit
price still leaves that price unresolved. Resolve the complete dependency set for
an offered line or omit it; never assume an unknown fee/discount is zero. Shared
demand and allocations must not silently change because other lines were omitted.
Distinguish uninvestigated material from proved absence of any active match; proved
absence triggers the runtime no-bid rule.

The all-omitted minimum candidate is an explicit incomplete-submission strategy,
not evidence that the real discount or tender total is zero. Keep that distinction
in artifacts and the coordinator's decision.

**Exit:** sign a bid with at least one fully supported position and explicit remaining
omissions. Verify those fields using the platform breakdown before expanding scope.

## 6. Expand coverage within a fixed signing budget

Keep single-mission development sequential. Once the missions work, enable parallel
production investigation using at most the four supplied browsers. Schedule from
dependencies: tender/spec discovery first, focused ERP/mail work as keys arrive.
Each worker retains its context and writes a separate mission log; the console
prints milestones, blockers and elapsed time rather than interleaved page dumps.

Initial full-run allocation, to tune from measured wizard/TAN duration:

| Elapsed time | Target |
| --- | --- |
| 0–2 minutes | Read brief; establish reference/identity and minimum candidate; prepare sessions |
| 2–11 minutes | Focused discovery, incremental records, complete dependency groups |
| 11–12 minutes | Stop new investigations; freeze and validate the best supported answer |
| 12–18 minutes | Enter bid, verify omissions/review, request/read TAN and sign |
| 18–19 minutes | Confirm accepted receipt; reserve the final minute for recovery |

Deadlines are operational limits, not a script choosing UI paths. Shorten collection
if measured signing needs more time. An early finished answer can submit earlier.
After commit, only verify the result; do not submit again on an ambiguous timeout.

Start diagnosis with the previously used `gpt-5-mini`/medium configuration if it is
still accepted by the team's proxy/account; keep model/effort explicit in artifacts
and the tested manifest. This is a continuity choice based on our recorded access
diagnostics, not a claim it is the best current model. Official OpenAI documentation
now labels it deprecated, though it lists image input and structured outputs:
[model documentation](https://developers.openai.com/api/docs/models/gpt-5-mini).
Check availability before spending a live mission on it. Select one available
replacement if necessary and establish a fresh baseline; do not change models
between retries without recording it. Optimize model cost after reliable receipts.

Use platform field-level scores to choose the next missing dependency to fix.
Complete more positions and breakdowns without destabilizing the proven signing
path. Treat the workboard's public IDs, rates and routes only as scouting history;
never copy them into prompts, defaults or packaged notes.

**Working MVP acceptance:** two consecutive unattended platform test runs from the
same package/configuration are eligible, finish within 20 minutes and contain at
least one complete offered position supported by original runtime evidence from
the relevant sites. Establish broader accuracy from the actual per-field scores;
do not promise a numerical quality score before obtaining them. Fresh sessions
exercise reliability but cannot prove generalization to the unseen private UI.

## Immediate next implementation slice

1. Preserve current artifacts; create one new run directory with configuration and
   stage/error snapshots. Fix exception cleanup so it cannot erase useful history.
2. Extract runtime bidder identity separately; validate the observed field mapping
   and read-back; prove registration advancement on the real scouting wizard.
3. Continue that minimum-bid run through explicit omissions, fresh TAN and receipt.
4. Package this exact entry point for a diagnostic Atira run and obtain eligibility.

Do not rewrite the browser driver, replace the repository, add another orchestration
framework or grow the test directory during this slice. Correct README/AGENT_SPEC's
stale statements when updating implementation status: eligibility mode now exists,
and the mail helpers are already integrated into signing. NEXT_SESSION's older
sections are historical; preserve them but follow this plan for new work.
