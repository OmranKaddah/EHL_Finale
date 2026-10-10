# Robustness under unfamiliar websites and data

Keep the browser/model transport and selected-source evidence foundation. It uses
runtime site URLs, credentials, current controls, and model-selected navigation.
Replacing it with another framework would not address the remaining gaps.

The current implementation is an explorer. Passing synthetic browser tests does
not prove that its model selects the right records or that it can produce a bid.
The private websites are unknown; no guarantee of final-run success is possible.

## Workflow to complete

1. Read the full runtime brief and answer schema. Extract scenario-specific
   requirements into a checklist with unresolved fields; never use public answers
   or inferred defaults. Preserve the invariant business rules separately.
2. Dispatch starting investigations using runtime sites. Maintain a shared gap
   list and reassign work after each investigation, because specifications,
   approvals and pricing can be split differently across sites. Site identity is
   a starting hypothesis, not a permanent owner of a fact.
3. Let the model choose pages, queries, records and archive members from live
   observations. Helpers read only those selections. Capture exact source text,
   record date, reference, authority, revision, scope and document identity.
4. Resolve conflicting evidence before calculating: current revision, applicable
   amendments, withdrawal links, scenario-date cutoffs, exact-reference approvals,
   authorized sender and subject, validity windows and quantity conditions.
   Missing evidence is an explicit unresolved state, never zero by default.
5. Match active materials against all required attributes, then calculate with
   Decimal and independently validate totals and rounding. Keep pricing separate
   from browser layout so website changes cannot alter the arithmetic rules.
6. At the submission deadline, choose a validated complete or explicit partial
   answer under the brief. Enter it using model-selected controls, perform the TAN
   signing flow, and verify the receipt. An explorer finishing is not task success.

Steps 1's task loading and 2's initial dispatch exist. The remaining coordination,
resolution, pricing, answer validation and signed submission are still required.

## Implemented adaptation mechanisms

Observed HTML and ARIA controls, associated accessible labels, select options,
enabled/read-only states, selected frames/tabs, model-requested masked screenshots,
selected downloads and ZIP members, paging of long page/document text, source
quotes, investigation notes, state-scoped repetition protection, bounded transport
retries and explicit investigation outcomes. No routes, public record values or
fixed navigation sequences are used as solution defaults.

Known coverage gaps include shadow DOM, canvas-only controls, image-only/scanned
PDFs, additional office formats, delayed downloads beyond the click observation
window, and custom widgets requiring gestures beyond the supported actions.
Keyword guards for exploration submits still depend on English/German wording;
they can reject unfamiliar access forms. Replace them with a validated submission
state machine when the bid pipeline exists, rather than broadly allowing submits.

## Validation before final submission

Use synthetic scenario families that vary labels, IDs, language, control order,
menus, frame/tab placement, session expiry timing, modal timing, result paging,
file formats, and where facts are stored. Vary scenario dates, reference names,
withdrawals, superseded revisions, quantities, material attributes, units,
currencies and discount clauses independently. Fixtures must contain invented
data and must not be packaged as solver fallbacks.

Measure separately: browser action success, relevant-source discovery, governing
record selection, field correctness, arithmetic consistency, and signed receipt.
Run at least one held-out layout/scenario family without changing the agent for
that family. A public scouting run establishes public-site behavior only; several
passes on the same layout do not establish generalization. Keep screenshots and
redacted action traces for failed cases, repair generic capabilities, then rerun
both the failing variant and the held-out family.
