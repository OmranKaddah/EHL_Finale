# RFQ agent architecture specification

## Goal and scope

Build an agent that discovers the evidence for one RFQ from four changing business
websites, resolves the brief's authority, date, revision, scope, and withdrawal
rules, computes the bid deterministically, then enters and signs it in the tender
portal. A private run changes the site software, layout, names, and data, so site
navigation and record selection must adapt to the run rather than rely on a fixed
click path.

The current MVP implements only the first vertical slice: model-directed parallel
exploration and a small, provenance-carrying shared evidence ledger. It does not
calculate, fill, sign, or submit a bid.

## Challenge and investigation context

The public practice scenario presents four independently authenticated business
sites: tender portal, supplier/customer portal, ERP, and webmail. Each site can
contain cookie banners, popups, dead links, and distracting content. Public
scouting credentials are supplied by `atira scout --env` in the process
environment; do not commit them, print them, or hard-code them. A later private
run may change site software, layout, names, records, credentials, and scenario
data. The four sites are investigation sources, not four fixed scripts: discover
sites from the runtime payload and let the model select useful pages and records.
Parallel browser sessions are allowed, up to the number supplied by Atira (the
package requests four).

The task's ground truth is defined by the full rules on the challenge page. The
following compact index is here to orient implementation and code review; consult
the authoritative challenge rules when resolving ambiguities:

1. Quantity is tender quantity with the latest applicable, non-withdrawn Q&A
   change; requirement is from the current specification revision.
2. Match only an active ERP material whose bore, derived/final stroke, pressure,
   mounting, and certification all match. Missing match means `no_bid`.
3. Select each valid price condition as of the scenario date and the highest
   reached per-position scale. Normalize its price unit and currency/FX before
   downstream calculations. Use Decimal arithmetic and HALF_UP to cents.
4. Apply the latest exact-reference director approval. A conditional minimum is
   evaluated on undiscounted base goods only; if it fails, discount is zero and
   an older approval does not revive. No-bid also has zero conditional discount.
5. A Q&A condition group can override the default discount clause per position.
   Discountable components may be base only, base plus mass surcharge, or
   neither; setup is always excluded. Surcharge is reported before discount.
6. Technical clarifications can withdraw numbered earlier answers. Scoped
   amendments apply only to their named current revision/requirement/attributes;
   latest dated applicable amendment wins. For `nutzbarer Weg`, first apply
   amendments, then add twice the per-end reserve from the matching technical
   release.
7. Convert `Satz` to pieces using the governing spec. Price scales, inventory,
   allocation weights, and bid quantities use pieces. Carton rounding changes
   packaging cost only.
8. Pool demand by selected material for stock and delivery decisions. Shared
   stock is all-or-nothing across the pooled demand. A Q&A delivery commitment
   applies only to its matching material and when its inclusive pooled-demand
   ceiling is met; otherwise use shared-stock/production rules.
9. Packaging uses Q&A tariff key, ERP pieces per carton, and an independent
   `ceil(position pieces / carton size)` per position. Do not discount packaging.
10. Shared setup pools use Q&A membership, ERP allocation mass, and the
    authorized Rüstpools mail fee/allocation rule. Add allocated fee to ordinary
    setup. Project bonus uses its marginal bands on eligible undiscounted goods,
    then cents are allocated by largest remainders (ties by position ID); it is
    independent of discount clauses.
11. Metal-index rates come from the latest exact-reference authorized message,
    choosing the validity window containing the scenario date. All authority,
    sender/subject, exact-reference, and date cutoffs in the brief apply; newer
    applicable records replace older ones, but unrelated/future records never
    apply.
12. Final unit price is clause-discounted EUR base plus clause-discounted mass
    surcharge plus (ordinary/shared setup + carton cost - allocated project
    bonus) divided by final pieces. Use unrounded components in this formula and
    round final unit price once, HALF_UP. Line total uses quantity times rounded
    final unit price. Optional breakdown fields are reports, not formula inputs.
13. Submit one decision per position for a bid. Missing active material means
    `no_bid`, no positions, total zero. Omitted positions are allowed for
    explicitly partial submissions but receive no position credit; the bid must
    still be signed/submitted. Saving alone is not scored.

The 28-field answer form and per-field score make completeness valuable. Position
fields are independently scored; optional breakdown fields can be blank, while
known zero values should be entered as `0.00`. All monetary answers are net EUR.
The model must make navigation, search, and relevant-document choices at runtime;
helpers can inspect only model-selected pages/results and may do deterministic
parsing, pagination, arithmetic, validation, retry, and form filling. They may
not autonomously discover and traverse the evidence corpus before model direction.
For email evidence, search combines words with AND, so include the exact tender
reference and a subject/topic. Read the relevant inbox/archive result. Authorized
record families use the corresponding sender local part and the bidder mailbox
domain: `technik` / Technikfreigabe, `logistik` / Verpackungstarife or
Terminfreigabe, `finanzen` / Devisenfixing or Projektbonus, and `kalkulation` /
Rüstpools or exact-reference Konditionsregeln and Preisindizes. Always enforce the
full brief's exact subject, reference, and scenario-date conditions.

At a high level, scoring awards decision/reference/discount, position fields,
total, and arithmetic consistency separately. Positions are weighted across
material, quantity, base price, surcharge, packaging, project bonus, final unit
price, and delivery; withdrawn-answer and date-selected metal-index checks may
also score. No-bid scoring is unchanged. Partial submissions retain credit for
completed positions, but an omitted position earns no position points and still
requires an explicit signed submission in a scored run.

## Fair-play and safety invariants

1. A dispatch model chooses focused starting investigations from the runtime site
   list. Each investigator's model chooses targets, queries, and documents from
   current runtime observations. There is one browser action per planning turn.
2. Helpers may inspect a selected page, interact with a selected control, parse a
   selected document, paginate a model-selected result set, and do arithmetic.
   They must not enumerate the sites and gather all their contents before model
   direction.
3. Never encode public tender answers, material numbers, prices, discounts, logins,
   TANs, or other website-derived scenario facts as defaults or fallbacks.
4. Use only run-provided browsers and model endpoints in the sandbox. Model calls
   go through the Atira proxy. Do not start a local model in a run or contact other
   hosts.
5. Keep credential values out of model prompts, traces, evidence, and routine
   logs. The planner may choose a credential key; browser code resolves its value
   locally when filling the selected field.
6. Do not submit unless the answer has been resolved and validated. The current
   exploration MVP always stops without submitting.

## Source layout and ownership

```text
src/rfq_agent/
  __init__.py       package identity and version
  __main__.py       dynamic worker allocation and lifecycle orchestration
  browser.py        run-provided CDP attachment or local Chromium adapter
  model.py          Qwen client routed through Atira's proxy
  planner.py        observations, prompts, action validation, action loop
  evidence.py       selected facts with source quote and page provenance
  run_contract.py  run/scouting input and platform submission contract
```

### Module boundaries

- **`__main__.py`** loads the current run or local scouting payload, computes the
  worker count, connects browsers, dispatches investigations, and prints a
  secret-free completion summary. It must not contain site-specific selectors,
  bid rules, or pricing logic.
- **`browser.py`** owns browser lifecycle and CDP details. In a sandbox it attaches
  to the browser URLs Atira supplies and never launches another browser. Locally
  it can launch Chromium for scouting.
- **`model.py`** owns model transport only. It takes messages and returns text;
  it does not navigate, parse business rules, or calculate bids.
- **`planner.py`** owns the model-directed control loop. It turns the current page
  into a bounded observation, gives the model the brief, available sites, selected
  evidence, and permitted actions, validates one action, and applies it. It is
  responsible for recovery from stale targets and for the step/time budget.
- The dispatch step in **`planner.py`** uses the model to choose a distinct
  runtime-provided site and focused objective for each worker. The package asks
  for four browsers; runtime worker count is `min(site count, browsers provided, 4)`.
- **`evidence.py`** owns provenance records. The MVP requires every recorded claim
  to cite exact text visible on the currently selected page. Later records should
  add normalized fact type, source record date, revision, exact tender reference,
  scope, and authority without treating model confidence as proof. Its async
  ledger deduplicates matching quotes from concurrent investigators.
- **`run_contract.py`** owns the platform API and local scouting payload formats.
  It must not decide which website to inspect or how a bid is calculated.

## Planned responsibility split after the MVP

Add modules only when the corresponding behavior is implemented:

- `investigation.py`: evidence-gap state and the dependency map between quantities,
  current requirements, catalog groups, approvals, and calculations. It exposes
  gaps to the planner; it must not autonomously traverse pages.
- `documents.py`: parse a document only after the planner selects it; preserve
  page/section and revision provenance.
- `resolution.py`: deterministic temporal and authority resolution: exact tender
  reference, approved sender/subject family, scenario-date cutoff, revision scope,
  latest applicable record, and withdrawn-answer handling.
- `matching.py`: compare candidate active ERP materials against every required
  bore, stroke, pressure, mounting, and certification attribute. A missing match
  drives the no-bid rule.
- `pricing.py`: Decimal-only price, FX, quantity scale, discounts, surcharge,
  packaging, shared setup, bonus, allocation, and total calculations. Centralize
  HALF_UP rounding and largest-remainder allocation here.
- `answer.py`: answer schema validation, all-position/no-bid rules, explicit
  omissions for partial bids, field completeness, and arithmetic cross-checks.
- `submission.py`: interact with the selected tender configurator, TAN flow, and
  receipt confirmation. It must use the runtime-discovered page structure.

## Runtime information flow

1. Load the run's brief, answer schema, site access, submission kind, and deadline.
2. A model assigns distinct runtime-provided sites and focused objectives to up to
   four workers. Each attaches to its own browser and chooses one next action per
   page observation.
3. Record only selected evidence in the shared ledger, each item linked to its
   exact page quote and provenance. A fact is not governing merely because it was
   found most recently; resolution checks reference, authority, date, revision,
   and scope.
4. Deterministic modules resolve the evidence graph, match materials, calculate
   prices, validate the answer, and report unresolved fields.
5. Submit the best validated complete or explicitly partial answer with enough
   time remaining; confirm the site receipt. For a missing active material, use
   the brief's no-bid rule.

## MVP action contract

The dispatch model returns distinct site assignments for available workers. Each
investigator turn returns one JSON action: `open_site`, `click`, `fill`,
`fill_credential`, `press`, `drag_to_end`, `scroll`, `wait`, `record_evidence`,
or `finish`.
Targets are short-lived IDs from the current visible controls. Site navigation is
restricted to the run-provided sites; clicks to unapproved hosts are rejected.
Evidence quotes must exactly occur in the visible text of the current page. The
MVP has a bounded step count and stores evidence only in memory.

### Known browser issue and current diagnosis

A local scouting run was started with:

```sh
eval "$(atira scout --challenge rfq --env)"
uv run --no-sync python -m rfq_agent
```

The observed run opened all four sites and filled the selected username/password
fields. The model then selected clicks; three workers failed on the next step with
`MVP safety: non-login, non-search form submission is disabled`, and one got a
stale/invalid target. The working diagnosis is that a cookie-consent control is
implemented as an HTML submit button and was rejected by a guard intended to
prevent final bid submission. `planner.py` has since been adjusted to permit
submit buttons whose selected control label includes cookie/consent and common
accept/reject wording, while the final bid/signing label block remains in place.

That adjustment has not yet been verified in a fresh browser run. The running
process does not hot-reload source; stop it with Ctrl-C and restart the command
above to pick up the change. On review, check at least:

- Whether the consent matcher sees the text/accessible label used by the actual
  cookie control, including labels such as “Accept all”, German consent wording,
  and buttons inside dialogs/iframes.
- Whether consent controls that say “Save selection/preferences” can be safely
  identified from their cookie-dialog context without broadly enabling arbitrary
  submit buttons.
- Whether login and search form submits still work, and the bid/signing blocker
  still rejects final submission controls.
- Why the customer-portal worker and ERP worker reported different errors, and
  whether stale target IDs are refreshed by a new observation rather than reused.
- Whether all four workers make progress independently when one page is blocked,
  times out, or presents a popup; whether logs remain free of credential values.
- Whether runtime site/browser counts, per-worker browser attachment, time/step
  budgets, and the Atira model proxy contract match the installed SDK/run payload.

A later run exposed a separate mail-site issue. The visible notice said
“Postfachhinweis / Der Lesebereich zeigt die ausgewählte Nachricht. Ältere
Freigaben bleiben im Archiv verfügbar. / Akzeptieren und fortfahren”. The mail
worker clicked targets on steps 4 and 5, then filled targets on steps 6–8 without
the log confirming that the notice had been dismissed. This suggests the planner
was not prioritizing the blocking notice or could not associate its button with
the notice. The current code now asks the model to clear routine blocking notices
using their observed controls before acting on underlying content, and includes
semantic dialog context on targets when available. It also clears old target IDs
before assigning IDs for a new observation to avoid stale hidden controls
colliding with current target IDs. These changes have not yet been reproduced in
a fresh local run.

The separate sandbox verification gate is visual. When its current visible text
identifies it as a robot/human verification gate, the planner attaches a masked
browser screenshot to that model turn. The model selects a current control; it may
use `drag_to_end` only on an observed slider/range in that gate, then observes the
result before taking another action. This keeps the interaction runtime-directed
and avoids hidden coordinates or external services.

Do not submit a test run or bid during code review. Reproducing the local scouting
issue is safe only if explicitly requested; this spec records the restart command
so the reviewer can decide whether to run it.

## Completion criteria for the first MVP

- Starts from Atira's run payload or `atira scout --env` output.
- Uses Atira-provided Qwen and the provided/local browser path.
- The model selects worker assignments and browser actions at runtime from the
  run data and observed state.
- Worker count follows `min(runtime site count, provided browser count, 4)`.
- Can retain source-quoted evidence without exposing credential values.
- Stops predictably at its step limit or model-selected finish.
- Does not claim to be a bid solver and never submits an incomplete bid.

## Exploration reliability update

The previous diagnosis sections describe earlier runs. Current exploration uses
state-scoped repeat tracking, so returning to a login page after navigation does
not block reauthentication. Observations expose disabled/read-only controls and
slider gestures verify their resulting value. Workers retain recent navigation
history, retry transient model errors, and report explicit completion statuses.

`documents.py` reads only model-clicked downloads and model-selected archive
members or frames. It supports PDF/text formats, bounded document paging, and
new-tab links. No document links or archive contents are crawled automatically.
The full evidence ledger is exported to `artifacts/evidence.json`; quotes are not
truncated or evicted. Worker evidence counts use the investigator identity.

Exploration is bounded by 120 actions, 18 minutes, and the platform deadline with
90 seconds reserved. Run mode refuses to launch Chromium without supplied CDP.
Synthetic browser and unit regression tests cover login recurrence, duplicate
actions, disabled fields, slider outcomes, frame selection, downloaded documents,
evidence retention, and transient model retries. These checks do not establish
success against the live challenge websites. Bid resolution, pricing, validation,
and signing remain unimplemented.
