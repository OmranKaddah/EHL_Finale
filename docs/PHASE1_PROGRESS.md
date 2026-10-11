# Phase 1 progress log — eligible first

Authority: `docs/PHASE1_CONTRACT.md`. This file records generic milestones only.
It must never contain website values, run identifiers, credentials, TANs or
answers. "Synthetic" below always means invented local fixtures; it is never
evidence of an official `eligible=true` result.

## Baseline (before Phase 1 implementation)

- Branch `Leonie`, parent commit `9a7fbd1`.
- Runtime is exploration-only: the entry point ends after investigation without
  a bid and the planner refuses every final bid/signing control.
- Test command: `uv run --python 3.12 --frozen python -m unittest discover -s tests -v`
- Reported baseline: 12 tests passing with a real local Chromium.
- Tooling preflight for this session: Entire Brain 0.1.0 (available), Entire
  Graph provider `entire-graph` v0.4.0 (available, Python semantic coverage).

## Milestone plan

| # | Milestone | Proof required |
|---|-----------|----------------|
| M0 | Documentation/config baseline commit captured by Entire | commit SHA + verified checkpoint ref |
| M1 | Deadline budget: monotonic clock, research cutoff, signing reserve, cancellable model calls | unit tests RED -> GREEN |
| M2 | Submission state machine: phase gating, draft snapshot, explicit omissions | unit tests RED -> GREEN |
| M3 | Draft validation: runtime schema, Decimal consistency, source-backed required values, dependency closure | unit tests RED -> GREEN |
| M4 | Observed-control fill, readback review against the draft | unit + local Chromium tests |
| M5 | TAN transaction: late request, newest exact-tender mail, process-only secret | unit tests RED -> GREEN |
| M6 | Signing and receipt: single owner, timeout observes before retry, receipt checks | unit tests RED -> GREEN |
| M7 | Planner safety gate driven by validated submission state (guards kept) | unit + local Chromium tests |
| M8 | Runtime coordinator wired into the entry point | unit tests with synthetic model/browser |
| M9 | Allowlist packaging script and manifest inspection | package tests + size check |
| M10 | Official sandbox result `eligible=true` | parent-run platform readback only |

## Recording rules

Each milestone entry lists: goal, changed components, exact test command and
result, RED and GREEN observations, known limitations, git SHA and Entire
checkpoint (only when really created and verified).

## Milestone log

### M0 — baseline (done)

- Commit `4b6d40e3a2f5e6bbf978108686e51c56c96da196` on `Leonie`, docs/config only, not pushed.
- Trailer `Entire-Checkpoint: 01M4KRP3DNN1XFDPD154M995K1`; local ref
  `refs/entire/checkpoints/K1/01M4KRP3DNN1XFDPD154M995K1` exists and holds the
  session transcript and metadata. `entire status` reports it as not yet on
  origin; the parent must push and read it back before calling it durable.

### M1–M9 — runtime, tests, package (working tree, NOT committed, awaiting parent review)

Test command (every run): `uv run --python 3.12 --frozen python -m unittest discover -s tests`

| Slice | RED observed | GREEN |
|-------|--------------|-------|
| 1. deadline, redaction, draft validation, submission state machine (`tests/test_submission.py`, 32 tests) | suite failed to load: `ImportError: cannot import name 'draft' from 'rfq_agent'`; 13 ran, 1 error | `tests.test_submission`: 32 passed |
| 2. gated planner controls, submission agent on a local Chromium page, mail owner, coordinator, model transport (`tests/test_submit_agent.py`, `tests/test_coordinator.py`, 17 tests) | `ModuleNotFoundError: No module named 'rfq_agent.submit_agent'`; 46 ran, 2 errors | full suite: 61 passed |
| 3. allowlist package (`tests/test_package.py`, 5 tests) | `FileNotFoundError: scripts/package.py` | full suite: 66 passed |

RED for the new modules was a missing-module load error, not a failing
assertion on existing behaviour; the assertions first ran at GREEN. Final
result: `Ran 66 tests ... OK` (12 baseline + 54 new), real local Chromium.

Package: `uv run --python 3.12 --frozen python scripts/package.py --out dist`
gives `dist/rfq-agent.tar.gz`, 69,576 bytes, 17 files: `agent.json`,
`pyproject.toml`, `uv.lock`, `src/rfq_agent/*.py`. Extracted into an empty
directory, `uv sync --python 3.12 --frozen --no-dev` finished in under one
second from a warm cache and `python -m rfq_agent` imported and stopped at the
missing-run message. Cold-cache setup time was not measured.

Changed components:

- `deadline.py` (new): one monotonic deadline from `started_at`/`expires_at`,
  research cutoff at 12 minutes, at least 6 minutes kept for filling/signing,
  `bounded()` cancels the pending call.
- `redact.py` (new): process-only `Secret`, redactor for env tokens, site
  credentials and TANs, stdout/stderr wrapper.
- `draft.py` (new): runtime JSON-schema subset check, Decimal calculator,
  source check for every answer value, bidder identity from evidence, every
  position priced or explicitly omitted, cross-position rule closure, all-omitted
  only with an observed capability, no_bid only with search evidence.
- `submission.py` (new): phases BOOT → IDENTIFY → PREPARE → VALIDATE → FILL →
  REVIEW → REQUEST_TAN → READ_TAN → SIGN → VERIFY_RECEIPT → ACCEPTED with owner,
  TAN and receipt checks.
- `submit_agent.py` (new): model-directed tender owner and mail owner loops.
- `coordinator.py` (new): research with cutoff/cancellation, draft preparation
  with validation feedback, submission hand-off.
- `planner.py`, `documents.py`: final-control and form-submit guards kept; they
  open only through an `authorize` callback set by the submission owner.
  `run_planner` takes a coordinator budget; observations include control values
  (never password fields).
- `__main__.py`: runs the coordinator; exit 0 only after a verified receipt.
- `agent.json`: setup is `uv sync --frozen --no-dev`.
- `scripts/package.py` (new), `tests/__init__.py` and four test modules (new).

Known limitations and unproven points:

- No live interaction was run by this worker. Nothing here shows the real
  portal accepts a bid, and no official `eligible=true` exists. All green tests
  use invented pages and values.
- The submission prompts and action set are generic guesses about a
  configurator; real form mechanics (multi-step wizard, where the TAN is
  typed, confirmation dialogs, omission controls) are unverified.
- Free-text `fill` is refused for the tender owner once a draft validates, so
  a search box inside the bid form cannot be used in that phase.
- "Newest" signing mail is the model's selection. Code checks the exact tender
  reference and the code on the observed page, that the observation follows the
  request, and that the code was not held for an earlier request. If one page
  shows several codes, code cannot tell them apart.
- Cross-position rules are listed by the model from the brief; code enforces
  that each listed rule is closed for each priced position, not that the list
  is complete.
- The schema checker covers common keywords only (`type`, `properties`,
  `required`, `additionalProperties`, `items`, `enum`, `const`, numeric and
  length bounds, `pattern`, `allOf/anyOf/oneOf`, local `$ref`); other keywords
  are ignored.
- `submission.kind` other than `site` ends as blocked; the API answer path is
  not wired.
- Python is not pinned by a `.python-version` file; `requires-python >=3.12`.
- Qwen may not produce a fully sourced draft within the budget; that is
  untested against the real model.
- Graph reported zero callers for `planner.observe`; its callers use a
  function-local import (`documents.InvestigationSession.observe`) the graph
  does not resolve. Checked in source.

Needed from the scout (mechanisms only, no scenario values):

1. Where the registered bidder company/VAT/email are shown, and which of them
   the configurator requires before it lets the bid continue.
2. Whether each position has an explicit omit control, or unfilled positions
   are shown as not offered in the review without one.
3. Whether a bid with every position omitted can be reviewed and signed.
4. Order of the signing step: is the TAN typed before the final control, or in
   a dialog after it; is there a separate confirmation dialog.
5. What the TAN mail shows (tender reference in subject/body, one code per
   mail, validity window) and whether the inbox needs a manual reload.
6. What the receipt page shows after signing (reference, identifier, wording)
   and whether it stays readable after reload.
7. Whether form controls are plain inputs/selects or custom widgets, whether
   decimals use a comma, and whether the form sits in an iframe or new tab.
8. Whether bid-form buttons are `type=submit` with labels that the planner's
   final-control pattern would or would not catch.

### R1 — fixes for the parent review (working tree, NOT committed, awaiting re-review)

The independent parent review failed the M1–M9 build on twelve points. This
section records the repair. The M1–M9 text above is left as written; where it
is now outdated (test counts, package size, the schema-subset and "newest mail"
limitations, the free-fill limitation) this section supersedes it. Still no
live interaction, no upload and no official `eligible=true`.

Procedure. Before each fix slice, signature-only stubs were added (ignored
keyword arguments, no-op methods, two data fields on `Evidence`) so that the
new regression tests would fail on their assertions instead of on a missing
name. Existing tests in `tests/test_submission.py`, `tests/test_submit_agent.py`
and `tests/test_coordinator.py` were then adapted to the new contracts; that
adaptation is fixture work, not RED/GREEN evidence.

| Slice | Command | RED (before the fix) | GREEN |
|-------|---------|----------------------|-------|
| A. controller, draft, mail, schema — review points 1, 2, 3, 4, 5, 6, 9, 10 (`tests/test_review_blockers.py`) | `uv run --python 3.12 --frozen python -m unittest tests.test_review_blockers` | first run invalid: the old code demanded a draft field the fixture lacked, so most tests stopped in setup (10 failures, 21 errors). After adding that field to the fixture: 32 run, 26 `AssertionError` failures, 2 errors (one fixture using the not-yet-existing `empty_total` source, one test stopped by the old review before reaching its assertion), 4 passing positive controls | 32 passed; later 33 with one added test |
| B. agent on local Chromium — review points 2 (failed request click), 5, 6, 7, 8, 9, 11 (`tests/test_review_blockers_browser.py`) | `uv run --python 3.12 --frozen python -m unittest tests.test_review_blockers_browser` | 10 run, 10 `AssertionError` failures | 9 passed, 1 failed on a test mistake (the review call did not read back the company field, which the fixed code rightly demands); test corrected, 10 passed |

Tests added after their code, with no RED run: the unzoned-timestamp test in
slice A, and the checklist and inventory-record tests in
`tests/test_coordinator.py`.

Final: `uv run --python 3.12 --frozen python -W error -m unittest discover -s tests`
→ `Ran 111 tests ... OK`, with no "never awaited", RuntimeWarning or
ResourceWarning line in the output (review point 12: the coordinator test now
uses a plain fake page instead of `AsyncMock`).

Package: `dist/rfq-agent.tar.gz`, 91,887 bytes, 18 files (adds
`src/rfq_agent/mailcheck.py`). `pyproject.toml`/`uv.lock` gain `jsonschema`
(4.26.0, with attrs, referencing, rpds-py, jsonschema-specifications). The
extracted archive passed `uv sync --python 3.12 --frozen --no-dev` and an
import check from a warm cache; cold-cache setup time is still unmeasured.

What changed, by review point:

1. Receipt: one quoted block must state acceptance and itself contain the
   receipt identifier and the exact reference; error, rejection and
   saved-draft wording is refused; a validation failure must state an error.
2. TAN: the mail owner quotes the one opened mail, its send time and any
   validity. Code refuses a mail sent before the request, a quote with a
   second code, a code held for an earlier request, and an expired code. A
   request counts only after its control was used without error.
3. Numbers: a brief rule must state the number; a calculation needs sourced
   inputs, no literals other than 0, 1 and 100, and no circular references.
4. Inventory and checklist: tender positions are separate evidence records
   (`kind: position`); the cross-position checklist comes from its own model
   call on the brief. A draft can shrink neither. `no_bid` needs
   `catalogue_search` evidence for every observed position.
5. Review: every number of a priced position, every top-level number and every
   entered value must be read back; a readback must come from the control that
   was filled; a value goes only into a control whose row names its position;
   non-empty controls not bound to a draft path and empty required fields block
   review; an omission is shown by the live state of its control or by text not
   seen before the omission.
6. Multi-page forms: `collect_readback` verifies a page's values before leaving
   it; a read-only summary is reviewed by exact quotes; the review is bound to a
   hash that signing rechecks.
7. Gating: login controls are not final controls; `open_form` enters a form
   through a final-looking control only before anything is entered; any other
   form change after review voids the review and the code; while a signing
   outcome is unresolved only links, search and login controls work.
8. Free fill after draft validation: search fields, and access-check fields
   whose value the page shows. Nothing else.
9. Revision: controls and omissions left by the earlier draft are tracked and
   must be re-entered, cleared or restored before review.
10. Schema: validated with `jsonschema` in the schema's dialect, Decimal-aware,
    with an empty registry so no reference is fetched.
11. Screenshots: none is sent to the model while any held code is on the page.
12. Coroutine warning fixed; suite runs with warnings as errors.

Unresolved after R1 (exact list):

- No live run. Real form mechanics are still unverified; scout findings were
  still "Pending" at each check, so the eight scout questions above stand.
- Acceptance, rejection and draft wording is recognized in English and German
  only. A portal in another language cannot be accepted or failed.
- Mail send time without any stated zone: whole-hour offsets are tried, so a
  mail sent a whole number of hours before the request (within about a minute)
  is not told apart from a fresh one. Send-time formats other than ISO, dotted
  day-month-year, slashed dates, month names, time-only and "n units ago" are
  refused. An absolute timestamp up to 60 seconds before the request passes.
- "Single opened mail" is the model's quote; code checks one code, the exact
  reference and the send time inside that quote, not the mailbox layout.
- The checklist is only as complete as the separate model call that lists it;
  inventory completeness depends on investigators recording positions. Code
  blocks drafting when either is missing, and does not prove either complete.
- A catalogue search record is the model's statement that a search finished;
  code checks its kind and position, not the search itself.
- Columns inside one row are not told apart: a value entered in the wrong
  column of the right position's row is caught only if its readback differs.
  When a control has no row container, the whole page text is used to find
  the position.
- An omission shown only by static text that was already visible before the
  omit action is refused, even if it is genuine; an omission without any
  control needs the `omission_without_control` capability.
- `not_on_form:<path>` and `all_positions_omitted` rest on a model-quoted page
  text; the all-omitted path remains unproven.
- A plain click on a non-link control after review voids the review, so the
  review must be done on the page that requests the code; a portal that forces
  a page change between review and code request needs that last page to carry
  the summary or the collected readbacks.
- Selects are not checked for unbound values; `clear_field` works on text
  inputs only.
- Screenshots are withheld only for held codes; other on-screen data is masked
  only for password fields.
- `submission.kind` other than `site` is still blocked; Python is still not
  pinned by a `.python-version` file; Qwen's ability to meet these contracts
  in the time budget is untested.
- Graph did not resolve callers of controller methods reached through
  attributes (`verify_receipt`, `review`); callers were taken from source.
