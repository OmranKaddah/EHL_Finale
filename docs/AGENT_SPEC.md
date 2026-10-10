# RFQ architecture and limits

The full RFQ objective remains: discover governing sources, calculate a bid,
validate it, sign it and confirm receipt. Missing evidence is unresolved, never
an invented zero or no-bid decision. Opt-in `--eligibility` discovers the complete
position list and attempts an all-omitted signed bid only when the runtime rules
permit it. It is a submission-path rehearsal, not verified commercial coverage.

## Runtime and browser flow

`run_contract.py` reads the brief, schema, deadline, submission target and credentials.
`browser.py` attaches to supplied CDP browsers in sandbox runs, and can launch
Chromium locally. `model.py` enforces the sandbox proxy; locally it defaults to
OpenAI gpt-5-nano and loads `.env`. Hosted Qwen is an explicit alternative.

`loop.py` owns bounded observation, masked screenshot/model requests and action
execution for all browser missions. Missions use its turns and retain their own
state, prompts, completion checks and error handling:

- `planner.py`: dispatch, live action schema, DOM observation/execution, exact
  source quotes, state-scoped repetition protection and investigation progress.
- `mail.py`: request-number baseline and original signing-code retrieval, also
  used by the submission worker in a separate context of the supplied browser.
- `submission.py`: source-backed bidder identity, audited field entry/read-back,
  review, current TAN and signed receipt. The model can discover missing bidder
  contact details in another runtime site while retaining the form in its tab.

`documents.py` maintains each worker's selected tabs, visible accessible frames,
selected downloads and ZIP members. Message-list, reading-pane and iframe-body
verification gates are independent. Helpers read model-selected sources only;
there is no crawler or fixed navigation route. Native input and pointer actions
execute model choices; helpers never write gate state directly.

## Business pipeline

`evidence.py` retains source quotes and stable provenance IDs. `investigation.py`
normalizes them, audits source fidelity, tracks gaps and reassigns investigations.
`records.py` defines source contracts; `resolution.py` resolves authority, dates,
revisions, withdrawals and exact material matching; `pricing.py` calculates with
Decimal; `answer.py` validates the runtime schema and independent totals.

Partial bids retain shared quantity and monetary dependencies. Unsupported rules
remain unresolved. Submission requires current observed review quotes, TAN entry,
a fresh review and a signed receipt. A commit attempt is never retried automatically,
including after a timeout. Saving a draft is not success.

## Budgets, diagnostics and validation

Main shares a 20-minute deadline capped by platform expiry. Investigation rounds
reserve time for audit and signing. Workers retain browser state and notes; notes
are hypotheses. Default investigation is sequential for debugging; parallel is opt-in.
Artifacts record sources, calculations, history and outcomes; routine logs omit secrets.
`package.py` includes runtime code/manifests only, excluding local keys and artifacts.

Tests cover invented arithmetic scenarios, source audit, browser mechanics,
independent gates and a mocked signed-receipt flow. Opt-in paid model tests use
invented local websites. They do not establish public/private-site reliability.

Known gaps: shadow DOM, canvas-only controls, scanned PDFs, office formats,
delayed downloads and unsupported gestures. Access guards include English/German
terms; unfamiliar language can be rejected. Setup allocation supports largest
remainders only. Model judgments do not prove source coverage or original-message
provenance. Source-backed registration passed locally; fresh-account document
enrollment and position-list extraction passed in a platform diagnostic. Signing
and platform eligibility still need end-to-end verification; see the newest entry
in `NEXT_SESSION.md` for the active run and results.

Before final submission, verify live source discovery and an accepted signed receipt,
then evaluate held-out layouts/data without tuning to them. Vary languages, IDs,
menus, frames, session/modal timing, records, currencies and where facts are stored.
Measure access, source selection, extraction, arithmetic and signing separately.
See [guidelines audit](COMPLIANCE.md) for the official constraints and packaging.
