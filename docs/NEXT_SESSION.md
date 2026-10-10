# Next-session handoff: finish the minimum signed bid

## Resume here — session wrapped at the user's request

**A diagnostic run is still active. Do not start a duplicate.**
[Run run_7e7a499f1661e8ab](https://ehl-challenge.atira.ai/runs/run_7e7a499f1661e8ab)
passed document-access enrollment, collected the complete position list in 14
actions, and validated the all-omitted proposal. The latest observed log is
`minimum bid validated; 5 positions to omit`. This verifies the enrollment fix
on a fresh platform account; it does not establish wizard/signing success.

Resume monitoring with:

```sh
atira status run_7e7a499f1661e8ab
atira logs run_7e7a499f1661e8ab --follow
```

The existing CLI follower has tool session ID `67315` if still available. There
is no local scouting rehearsal left running. The platform run continues remotely
if the follower disconnects. It was intentionally left active for this handoff.
Run metadata is in `artifacts/platform-diagnostic-v2/run.json`.

Next actions, in order:

1. Collect that run's final result and logs; inspect its actual review/signing UI
   before changing guards. Do not equate a successful click with wizard progress.
2. Verify the fresh code sequence: mailbox baseline before exactly one request,
   a newer original TAN bound to the runtime reference, validated review, signed
   receipt. Baseline currently has 60 seconds and retrieval 90 seconds; these
   limits and localization of review values are still unverified bottlenecks.
3. After a real receipt, record platform eligibility separately from quality.
   The current diagnostic intentionally omits all positions and proves no
   pricing/specification accuracy. Keep discount and TAN missions separate.
4. Resume the partial-quality work in `MVP_PLAN.md` only after the signing path
   works. Full workflow answer retention, partial-coverage handling, optional
   breakdown validation and setup-cost allocation remain planned fixes.

Preserve all uncommitted work, including untracked `docs/MVP_PLAN.md`; no commit
was made. Default `agent.json` still runs the full workflow and the model default
remains nano/low. The diagnostic's isolated staged manifest explicitly selects
mini/medium and `--eligibility --steps 100`. Do not upload the repository directly:
use `package.py`/an allowlisted staging folder. No scored publication is authorized.
No new tests in `tests/`: this session used compilation, schema/assertion checks,
live scouting and diagnostic platform runs. Older history below is chronological
and can contain superseded claims; this section and the redeployment update win.

## Redeployment check and registration progress — 11 October 2026

Fresh scouting inputs report challenge version 6, public-1. All four supplied
website roots returned HTTP 200 after login redirects. The platform exposed no
deployment identifier, so reachability does not establish which build is deployed.
Tender and mailbox authentication have succeeded; complete ERP/customer extraction
has not been reverified. The team already has an `OPENAI_API_KEY` secret configured.

Live diagnostics use `gpt-5-mini`, medium reasoning, explicitly; the default model
and default full-workflow manifest have not changed. A focused mailbox identity
mission succeeded, with source quotes preserved in
`artifacts/redeploy-contact/verified`. Registration then actually advanced from
bidder data to bid type, followed by position omission, in
`artifacts/runs/20261011-005755-619000-eligibility`. The email was discovered from
the authenticated bidder account, not guessed or copied into runtime code.
That rehearsal subsequently drifted into other websites and was interrupted;
it did **not** request a TAN or produce a signed receipt.

Changes since the earlier handoff:

- Bidder identity is extracted separately from bid scalars. A model-selected
  `find_identity` mission retrieves a missing registration field with quoted
  source support, preserving the tender form. Field meaning and native read-back
  are checked before continuing.
- Accessible account/profile facts can be recorded when an unrelated message
  body remains locked; protected body content is still masked and provenance
  checks remain in place.
- Submission navigation is restricted to the runtime submission website.
  Focused identity and signing helpers handle the other websites.
- Omission proposal review checks actual runtime rules without inventing optional
  disclaimer requirements. One earlier proposal failed only that invented
  requirement; the corrected audit accepted it.
- Each eligibility rehearsal preserves its own timestamped directory under
  `artifacts/runs`, with submission observations, action history, screenshots and
  result checkpoints. Optional `RFQ_TRACE_DIR` captures credential-redacted local
  observations. These artifacts are excluded from the submission archive.

No new tests were added. Compile/schema/targeted assertion checks passed. The
rehearsal using `artifacts/redeploy-eligibility-v3` reached the totals form after
all five omissions, recovered registration after session expiry, then looped on
premature review. It was interrupted with no TAN request or receipt; checkpoints
are in `artifacts/runs/20261011-010315-346000-eligibility/submission`.

The follow-up fixes retain exact bidder identity sources by source index (rather
than asking for a retyped quote), expose review only when all required omission
identifiers occur in the current view, and preserve label/value word boundaries
when validating review numbers. Inline checks and compilation passed; no tests
were added. To verify the reported sandbox redeployment too, we started an
authorized **diagnostic**, not scored, platform run before another local restart:

- Run: `run_3ef20e834242c106`, rehearsal: `reh_a4c20dcda4161435`
- URL: https://ehl-challenge.atira.ai/runs/run_3ef20e834242c106
- Staged runtime only: `/private/tmp/rfq-minimum-diagnostic-20261011-011123`
- Command: `env OPENAI_MODEL=gpt-5-mini OPENAI_REASONING_EFFORT=medium uv run --no-sync python -m rfq_agent --eligibility --steps 100`
- Upload: 22 files, ~107 KB; no credentials, artifacts, docs or tests.

The first platform run **failed** with `agent_exit`, without attempting a bid.
Setup, supplied CDP browser, OpenAI proxy and authentication worked. The fresh
account needed a participation acknowledgment to release documents; our access
classifier rejected it at action 15. The investigator then wandered to unrelated
tenders and exhausted 40 actions. The scouting account did not present this
enrollment requirement in the local rehearsals. The access classifier now explicitly
allows document-access enrollment without requiring a receipt/code form; signing
and bid submission retain their separate guards. A second diagnostic is running:
`run_7e7a499f1661e8ab` / `reh_cc49d4720945ed9c`, staged from
`/private/tmp/rfq-minimum-diagnostic-20261011-011756`.
That second run passed enrollment and original position-list extraction; its
final submission result is pending at handoff.

First-run evidence is in `artifacts/platform-diagnostic`: result JSON, logs and
locally extracted recording frames. Atira's live frame feed stayed empty and its
recorded-frame endpoint returned 502; HLS recording extraction with local ffmpeg
worked. `recorded-03.png` shows the unlocked document-access enrollment form.
Do not infer a site or model outage from that frame-service failure.
Receipt/eligibility/quality remain unverified. No scored publication authorized.
Keep TAN retrieval and discount approval verification as separate missions.

## Current implementation order — 11 October 2026

Follow [MVP_PLAN.md](MVP_PLAN.md) for new work. It reviews the current runtime code,
official rules and supplied workboard, and prioritizes real registration → signed
minimum bid → platform eligibility → verified position coverage. The user requested
no more tests in `tests/`; use live scouting and platform rehearsals for this work.
The review also identified answer retention, partial-coverage gates, optional-field
validation and reported setup surcharge as concrete follow-up fixes. These are
planned, not implemented by the review. Preserve the history below.

## Implementation update (read before the older handoff below)

CRITICAL screenshot finding (00:19:48): the public rehearsal reached the submission
URL but remained at bidder-data step 1. The company-name field contained EUR and
the page reported bidder not registered. Earlier narration of configurator
progress overstated actual advancement: validated scalar paths did not validate
field semantics. Stopped the rehearsal at submission step 32, without a confirmed
receipt. Current `artifacts/eligibility` records this failure. Do not call it a
successful wizard, omission or signing run.

`review_field_entry` now independently audits each selected answer/bidder field's
label/name/row/form context against the answer path or runtime-brief quote before
entry. Generic non-search fill on the submission site also receives this audit,
so it cannot bypass bidder/answer checks. A currency-to-company mapping is rejected
in the synthetic regression. The actual public fix remains unverified. Submission
review now additionally requires ALL supplied omissions to have been marked;
filling a header alone cannot enable review. Focused submission suite: 12 passed.
Latest full suite: 126 tests, 121 passed, five live-model tests skipped. A separate
real mini-medium probe with invented data rejected currency-to-company entry and
accepted the correctly quoted company entry. This verifies the model audit on a
synthetic mapping, not actual public registration, signing or receipt success.

2026-10-11 continuation: submission now uses an observed-control structured
decision schema. Answer paths are enumerated, read-only fields excluded, review
requires successful entry or complete omission marking, TAN/commit/receipt actions
are gated by state, and three consecutive malformed decisions after repair stop
the worker. Navigation remains model-selected. Signing baseline retrieval now
returns to observation before the request click, avoiding stale targets; only
successful clicks/fills update entry progress.

New regression tests verify selecting two documents in a separate reading frame,
opening each disclosure, fresh content with an unchanged parent URL, rejection of
invented answer paths/read-only targets/early commit, and target renumbering during
mail baseline retrieval. Synthetic signing passes, but is not public success.

Public diagnostics: the new submission schema removed invalid-path failures, but
the worker tried to review source documents as a bid. Stopped and archived in
`artifacts/archive/eligibility-premature-document-review`; review-stage restriction
added. A subsequent rehearsal selected the position overview but rejected its
first evidence quote, then could not repair it because MissionProgress blocked
ALL record_evidence actions on unchanged content. Stopped and archived in
`artifacts/archive/eligibility-quote-repair-blocked`. MissionProgress now keys
evidence attempts by quote, permitting corrections and distinct facts while still
blocking identical quotes (even with a changed claim). Source matching remains
strict. A further public rehearsal is checking these corrections; do not infer
receipt, fresh TAN timing or full-site evidence coverage from passing fixtures.

Latest rehearsal update: the narrowed minimum-bid investigation collected the
position list and the independently audited all-omitted proposal passed. The
submission worker then repeated invalid answer paths; the rehearsal was stopped
with status unconfirmed, without a confirmed signed receipt. Current artifacts
are in `artifacts/eligibility`. Do not claim public signing success. Submission
now exposes exact validated scalar paths/values, includes allowed paths in error
feedback, and retains rejected paths in history. This correction still needs a
public retest. The shared investigation prompt now explicitly explains document
selectors that reveal a separate lower/adjacent reading pane, nested frames and
disclosures. Read selected contents before switching documents; original quantities
must not be treated as current without amendment checks. No screenshot values,
labels or routes were added to runtime code.

The latest full suite before these prompt/path diagnostics changes was 121 tests:
116 passed, five live-model tests skipped. Platform test upload is still pending;
the user has requested a diagnostic test run, not a scored publication.

Minimum-bid integration update: opt-in `--eligibility --steps 80` discovers the
runtime tender's complete position identifier list, builds an all-omitted bid
only with quoted runtime permission and a source audit, validates the runtime
schema and zero arithmetic, then calls the existing submission worker. Default
full-workflow/package command is unchanged; this flag DOES attempt submission.
No public identifiers or labels were added to runtime defaults. `eligibility.py`
and `tests/test_eligibility.py` are new and must be preserved.

Signing now uses a separate context within the attached browser: baseline BEFORE
the model-selected signing request, latch before the click so a timeout cannot
cause a second request, retrieval strictly above baseline for the exact tender
reference, original-source audit, then tender TAN entry and fresh review before
commit. `retrieve_tan` can retry reading the existing request. Native confirmation
dialogs are accepted only during authorized commit. Omitted positions require
current review quotes; bidder fields require verbatim runtime-brief quotes.
Mailbox contexts close in finally. TAN values are absent from console logs.

Latest suite: 118 tests, 113 passed, five opt-in live-model tests skipped. Synthetic
browser signing verifies baseline-before-request ordering, runtime credentials,
reference-bound retrieval, preserved tender form, native confirm acceptance and
receipt. This uses mocked mailbox/model decisions and is NOT public reliability.

One mini-medium scouting eligibility rehearsal FAILED BEFORE SIGNING. It collected
the complete original position list but continued seeking a reference inside that
document, suffered a 180-second model timeout, session recovery trouble and then
APIConnectionError. No signing request or bid was attempted. Preserved artifacts:
`artifacts/archive/eligibility-first`. The investigation objective was narrowed
afterward to position IDs only; runtime brief supplies the reference and submission
review verifies it. That prompt correction has NOT been publicly retested. Do not
claim eligible, fresh TAN timing, or three successful rehearsals. Local package
rebuilt, not uploaded. Next: verify public minimum-bid flow once model transport
works, then fresh-TAN timing and repeated receipt success; keep discount separate.

Portal follow-up: single-site dispatch now explicitly limits its goal to the only
available website. Screenshot requests are bounded across incidental changes and
are unavailable for already parsed documents. Selected documents no longer inherit
parent-page gate/visual metadata. Repeated captions include generic record/row
context; extra relevance review applies to duplicate captions rather than every
short navigation link. Browser observation retries once after execution-context
errors, detached selected frames return to the parent, and failed debug runs retain
history plus redacted error details. No site-specific routes/labels were added.

Public mini-medium tender check completed in 13 actions, quoting one original
quantity document. This does NOT verify latest amendments/current quantities.
An earlier mini customer diagnostic exhausted 35 actions with zero evidence;
it still used the overbroad short-link critic. The follow-up reached the document
release form but was blocked by the old generic form-submit guard; it exhausted
30 actions and recorded only access instructions, which is NOT technical evidence.
The guard now uses a model classification of the observed form to allow a single
read-access submit, restoring policy immediately afterward; commit/signature
authorization stays disabled. Focused evidence now receives a relevance/support
audit before being stored. These last changes are not yet publicly verified on
the customer portal; an invented live receipt/form test passed with mini medium
in 31 seconds (selected image code, grouped unlock, receipt, acknowledgment,
model-verified unfamiliar access submit, then source evidence). Latest browser
regression suite passed all 47 tests. Do not equate this with public customer success.
Original reported runs are archived under
`artifacts/archive/portal-reported`, and the failed customer diagnostic under
`artifacts/archive/customer-diagnostic`. Latest suite: 108 tests, 103 passed,
five paid live-model tests skipped (later suite reached 110; one further source
review unit test added). Default nano-low remains unverified on these
portal changes. Package rebuilt locally; not submitted.

Explicit `--mission tan`, `baseline`, `discount`, `--goal`, `--after` and bounded
mission timeout/steps now exist. TAN calls the actual mail API engine; discount
uses `missions.py` with quoted result fields and a model applicability audit.
Artifacts are separated by mission. Existing business/submission work is preserved.
Generic grouped gate execution, disclosure provenance, structural search-submit
support and persistent navigation-cycle guards were added. Model navigation is
still required; no public codes or selectors were copied into runtime code.

Evaluation so far is diagnostic, not a reliability benchmark: nano low/medium
failed harder invented mail missions. Mini medium passed both invented missions
on an earlier revision. Public mini TAN original-body extraction completed in
110 seconds without a baseline; freshness and the 60-second target are NOT proven.
Public discount runs at 180 seconds and 60 actions failed, often following export
decoys. Their artifacts are preserved under `artifacts/archive`. Later cycle and
ambiguity guards have not yet established public discount success. Do not integrate
signing based on these results or claim the mail workflow is fixed.

Latest user steering: ERP access image is visible, slider/robot are complete,
but receipt input remains empty and the investigator repeatedly reopens the site.
Observation now reports visible canvas/images independent of UI language and
supplies screenshots; prompt distinguishes unlocking from finishing required
access fields. Shared progress prevents repeatedly reopening an incomplete form.
An invented image-only receipt test passed with mini medium: image read, field
filled, acknowledgment checked, continue selected, source recorded. Public ERP
access-only rehearsal also passed with mini medium: temporary-service retry,
slider and robot verification, image receipt field filled, acknowledgment and
continue, workspace heading recorded at step 12. Artifacts: `artifacts/sites/erp`.
This verifies access, not material matching, pricing or full bid completion.
Default nano low is unchanged; its image-form performance is not established.

Latest complete suite before final image/cycle tests: 101 tests, five opt-in tests
skipped, all others passed. Added image browser regression passed in the 43-test
regression suite. Recheck final counts and rebuild package after final changes.

The historical sections below describe the starting state and failures; statements
that explicit missions have not been implemented are now historical.

Written after the 2026-10-10 debugging session. This is a development handoff,
not a runtime prompt or submission input. The package builder excludes docs,
tests, screenshots, artifacts and `.env`. Do not copy public scenario facts,
credentials or signing codes into runtime code, prompts, configuration or defaults.

## What the user wants next

The user is frustrated with repeated patches and tests that pass while the real
mail run still fails. Their last question was whether we are going in circles
hardcoding the website layout. The recommended direction was accepted as the
basis for this handoff, but implementation of that replacement has NOT begun.

Replace the navigation policy and clarify mission handling. Do not rebuild the
whole project. Keep reusable browser/document/evidence infrastructure and the
business-rule pipeline. The agent must work on private websites with different
software, names, labels, layouts, navigation, data and distribution of facts.

No more website-specific patches or retries of paid tests until one happens to
pass. Test mechanics separately from the model's ability to pursue its objective.
Report public reliability honestly. A synthetic pass is not proof of reliability.

## Workspace and operational constraints

- Repository: `/Users/vladmoroshan/Desktop/Repos/EHL_Finale`; zsh, Python 3.12,
  Playwright, uv. User branch is `vlad`.
- There are MANY modified and untracked files. They contain the accumulated
  implementation. Inspect `git status`; do not reset, overwrite or delete them
  wholesale. There is no clean committed baseline of all recent work.
- Local `.env` contains an OpenAI key. Never print or package it.
- Local default is `openai/gpt-5-nano`, with code default reasoning effort `low`.
  Reasoning effort was discussed and official documentation read, but was NOT
  changed. Qwen remains selectable explicitly.
- In scored runs, models must use the platform proxy and browsers must attach
  to supplied CDP sessions. Own Chromium is only a local development option.
- Sequential debugging is the default; `--parallel` is opt-in. User explicitly
  wanted concise logs and one website at a time.
- Sandbox Chromium launch on this Mac requires escalation; sandbox launch can
  fail with macOS MachPort permission errors. The unittest command prefix and
  several exact live-model test commands have existing approvals. Follow actual
  tool permissions. Live-model tests spend API credits.
- Do not spawn subagents unless explicitly authorized by the user or applicable
  repository instructions. Read any applicable AGENTS.md before implementation.
- No external messages, publishing or submission was authorized by this handoff.

## Official material to verify before implementation

Read the current contents rather than treating our compliance notes as authority:

- https://ehl-challenge.atira.ai/start.md
- https://ehl-challenge.atira.ai/challenges/rfq.md
- https://ehl-challenge.atira.ai/challenges/rfq#rules
- https://ehl-challenge.atira.ai/docs/fair-play.md
- https://ehl-challenge.atira.ai/docs/building-an-agent.md
- https://ehl-challenge.atira.ai/docs/run-contract.md
- https://ehl-challenge.atira.ai/docs/scoring.md
- https://ehl-challenge.atira.ai/docs/submitting.md
- https://ehl-challenge.atira.ai/docs/mcp.md
- https://ehl-challenge.atira.ai/llms.txt
- https://ehl-challenge.atira.ai/llms-full.txt

The user also supplied a screenshot walkthrough at
https://claude.ai/artifact/Ai4aKmuYCdC6PmJnibNeTx and pasted its mail mission.
The pasted instructions are available in conversation history; artifact access
was not established here. Do not assume its contents were successfully fetched.

Rules supplied by the user: the model must choose every navigation/search/source
at runtime. Fixed click paths, crawlers collecting everything for one model call,
and copied public scenario values are rejected. Helpers may execute model choices,
parse selected content, calculate, validate and retry. No human input or external
help during scored runs. No public UI labels as fixed navigation selectors. Private
data changes both the UI and where facts are found. Recheck exact official wording.

## Essential distinction: two different mail missions

1. Signing-code retrieval: newest original signing mail, request number above a
   baseline captured before the tender portal requests a new code. Return a code.
2. Discount investigation: latest authoritative discount approval for the runtime
   tender, including percentage, exact reference, sender/authority, date, conditions,
   supersession/withdrawal and any related approval facts needed by the brief.

The current `--site mail` command does NOT mean TAN retrieval. It asks the model
dispatcher to derive an investigation from the full RFQ brief. Recent objectives
explicitly requested discount approvals. The navigator nevertheless opened signing
mail, read its body and recorded a code. That is extraction success for the wrong
mission, NOT completion of the assigned discount investigation.

The user-provided mail API contract is:

```python
async def latest_tan_number(page, access: dict) -> int | None: ...
async def get_tan(page, access: dict, after: int | None = None,
                  timeout_s: int = 90) -> str: ...
```

These functions already exist in `src/rfq_agent/mail.py`. They are standalone;
they are not what `--site mail` calls, and are not integrated into the full signing
worker. Do not pretend the debug investigator's evidence output implements them.

TAN constraints supplied by the user: highest request number, not first row;
original body only, never preview/draft; request number strictly greater than
`after`; never request a TAN from the mail website; poll/revisit roughly every
three seconds; return within 60 seconds of arrival; codes expire after five minutes.
Shared scouting accounts can accumulate many signing messages from other runs.
Do not infer freshness merely from being the highest number visible.

## Failure history and what it actually established

### Initial four-worker implementation

- Four browsers investigated portals/mail/ERP concurrently. Logs were enormous.
- Modal overlays blocked actions; agents followed acceptance/export decoys.
- Sliders did not reach maximum reliably; checkboxes were selected prematurely;
  disabled fields were filled; stale IDs and session expiry disrupted access.
- Repeat prevention incorrectly blocked legitimate reauthentication after expiry.
- Worker budgets exhausted with zero evidence. API timeouts were counted as
  completed investigators in some summaries. No bid was submitted.

### Robustness rewrite / transport work

- A large robustness plan was implemented. Initial runs then stopped at startup
  with TimeoutError and zero sources. Dispatcher/model calls were too slow and
  insufficiently diagnosable. Longer bounded timeouts, retries and phase logs added.
- Hosted Qwen took tens/hundreds of seconds per action. User requested the cheapest
  OpenAI alternative using the key already in `.env`; gpt-5-nano became default.
- Faster runs exposed workers visiting the wrong runtime site, invalid key presses,
  missing targets, repeated credential fills, invalid JSON and poor recovery.
- Browser isolation, runtime action schemas and guards were added. Some safeguards
  were too broad and blocked productive choices. Full bid success remains unproven.

### Simplification and repeated mail gate patches

- A shared `BrowserLoop` was introduced and dead code/docs reduced.
- User then saw no slider actions, only checkbox clicks and unrelated navigation.
- Schema was changed to associate gate controls and require slider maximum before
  offering its checkbox; runtime premature-checkbox guard also added.
- An overbroad gate-priority policy prevented use of search while gates were pending.
  That restriction has since been relaxed for accessible search forms.
- Gesture uses pointer input, with native End-key fallback for a selected native
  range control. It verifies the resulting value. No JS write to unlock gate state.

### Hidden screenshot/action loops

- Saved history showed 38 actions requesting screenshots, despite only a few
  being printed in the terminal. The third body gate was reached near step 60.
- Added state-scoped limits for screenshots, notes and ineffective scrolls, and
  printed screenshot requests. Scroll positions now participate in state hashing.
- Automatic screenshot detection still relies partly on language regexes. This is
  not a robust, language-independent accessibility strategy.
- A deliberate wait used to clear rejected/attempted choices, re-enabling loops.
  Current code no longer clears attempted targets simply because it waited.

### Original-body extraction versus mission completion

- Public screenshots show independent access controls for message list, reading
  pane and embedded body. They are scouting observations, not a universal layout.
- Original body may be under a disclosure and inside an iframe. Preview/draft
  content can contain false codes. Multiple similarly named original links can
  include decoys; screenshots alone do not prove a specific link is real.
- A plain-text locked fieldset with no disabled buttons was mistakenly treated
  as accessible. `protected_locked` now checks the fieldset itself.
- Public runs eventually extracted the exact original TAN body. They then kept
  toggling its disclosure and recording duplicate quotes until the action limit.
- First evidence sometimes consisted only of title/date/gate text. Added guarded
  disclosure/body filtering, duplicate reporting, and exclusion of collapsing an
  already-open summary. These policies are still heuristics, not universal proof
  of original-message provenance.
- One recorded claim said no tender reference was visible while its own quote
  contained the tender reference. Claim quality/relevance is not enforced well.
- Most recent public run: discount objective, original TAN recorded at step 33,
  later duplicate rejected, unrelated signing messages revisited, exhausted with
  one evidence record. User screenshot proves body was unlocked and readable.
  It does NOT prove the discount approval was found.

### Harder synthetic navigation tests

- Earlier easy tests had one obvious relevant message and only access gates. They
  passed, but did not test the real failure: pursuing the objective amid distractions.
- The live test was strengthened: signing-code distraction visible, delivery
  message initially hidden until a topic search, three independent access gates.
- Several runs FAILED: unrelated signing mail selected, empty searches submitted,
  repeated screenshots/waits, no evidence, or BadRequestError from an empty anyOf.
- Text `fill` incorrectly accepted sliders/checkboxes as candidates. Those types
  are now excluded from schemas and rejected at execution.
- Added a `purpose` field, prominent objective, zero-width cleanup for model input,
  separate model-based link relevance review and focused completion review.
- Relevance review initially saw surrounding gate/page context and accepted the
  unrelated row. Now it sees actual link text/label/destination, not the whole gate.
- Empty search submits/keypresses and redundant opening of the current homepage
  are excluded where observable. No-op alternatives were consuming the budget.
- Sending a schema to the provider did not establish local enforcement. The shared
  loop now validates JSON with jsonschema, allows one bounded repair, then rejects
  invalid responses before execution. Planner stops if its schema has no branches.
- Most recent harder synthetic run PASSED: rejected distraction, entered search,
  opened relevant delivery message, selected body frame, unlocked inner gate,
  recorded body at step 22 and finished after two repeated-evidence blocks.
  Duration about 76 seconds. Earlier failures MUST remain part of the evaluation;
  this one pass does not establish dependable navigation or the TAN timing target.

## Current code map

- `__main__.py`: CLI/dispatch, sequential debug/full workflow, artifacts. No
  `--mission` or `--goal` flags yet. Single-site mode runs `planner.run_planner`;
  enables focused completion review; prints objective and provider/model.
- `planner.py`: a very large mixed module containing prompts, dispatcher,
  observation, gate association, action schema, executor, evidence checks,
  repetition logic, model relevance/completion checks and investigator loop.
  Main replacement target. Do not keep adding policy here.
- `loop.py`: shared bounded observe/model/execute transport and local schema
  validation/repair. Preserve the timeout and validation mechanisms.
- `documents.py`: selected tabs/frames/downloads/ZIPs. Frame metadata checks
  visibility and parent access. Reads selected sources rather than crawling.
- `browser.py`: local Chromium versus provided CDP, isolated worker tabs.
- `model.py`: local dotenv, configurable OpenAI/Qwen, proxy enforcement in scored
  runs, bounded transport retries. Keep keys out of diagnostics.
- `mail.py`: independent TAN/baseline mission, request/code validation. Needs
  completion/provenance/freshness improvements and wiring into explicit CLI/signing.
- `evidence.py`: source/provenance IDs and ledger; `add()` returns whether a record
  was new. Identical quote is deduplicated even if claim wording changes.
- `submission.py`: validated form filling, signing and receipt logic; do not
  accidentally authorize final commit from a single-site debug command.
- `records.py`, `resolution.py`, `pricing.py`, `answer.py`, `investigation.py`:
  source contracts, normalization/audit, authority/date resolution, Decimal math,
  schema checking and business gaps. Preserve outside this mail refactor.
- `package.py`: explicit allowlist of manifests plus runtime Python, 20 MB limit.
- `docs/AGENT_SPEC.md`, `docs/COMPLIANCE.md`: architecture/limitations/audit notes.
  `docs/ROBUSTNESS.md` is now just a pointer, NOT the original lengthy plan.

Current fragile policy to inspect/remove or replace:

- `gateFor`: ancestor containing exactly one slider and a fieldset; not general.
- Global gate-choice priority: solving every visible gate before relevance is known.
- Language regexes in access/safety/visual detection and credential identification.
- Pending-source flags that can trap the agent in a frame or conflate opening
  metadata with reading an original body.
- Disclosure text heuristics and model assertion of `source_kind='original'`.
- Automatic screenshots of the parent page while the selected context is a frame.
- Small-model judgments used as if they proved record coverage or freshness.

## Latest artifacts and tests

Inspect these BEFORE another run overwrites them:

- `artifacts/sites/mail/evidence.json`
- `artifacts/sites/mail/workflow.json`
- Screenshot: `/Users/vladmoroshan/Desktop/Screenshot 2026-10-10 at 21.50.38.png`

Latest artifact contains one exact original signing-body quote. It is unrelated
to the assigned discount goal, and its claim contradicts part of its quote.
Do not reproduce the code or public identifiers in this handoff or runtime logic.
Earlier artifacts may have been overwritten; conversation logs contain the history.

Last full regression run: 86 tests, 83 passed, 3 opt-in tests skipped. Then the
harder opt-in mail test passed once as described above. No code changes after
that pass except this handoff. Do not infer stability from one paid test success.

```sh
.venv/bin/python -m unittest discover -s tests
RFQ_LIVE_MODEL_TEST=1 .venv/bin/python -m unittest discover -s tests \
  -p test_live_navigation.py -k independent_mail -v
```

The paid live test routes invented websites locally; it is NOT the public mailbox.
Mock tests formerly supplied empty observations while asking for nonexistent
targets. These mocks were corrected after local schema validation was introduced.

User's local reproduction:

```sh
eval "$(atira scout --challenge rfq --env)"
uv run --no-sync python -m rfq_agent --site mail --steps 60
```

Stop an old process before restarting: running Python keeps the previously loaded
code. Never assume updating files changes an already-running investigation.

## Concrete implementation plan

### 1. Establish the baseline and scope

- Read current official rules, repository instructions, this handoff and relevant
  code. Preserve current public artifacts separately before running new tests.
- Summarize failures by access, relevance, extraction, validation, termination and
  timing; stop treating all failures as slider failures.
- Inspect whether running process/import paths and model/provider match expectations.
- Keep full RFQ work intact. No unrelated pricing, ERP or submission changes.

### 2. Make the debug mission explicit

- Add `--mission tan`, `--mission discount`, and a generic `--goal` override with
  sensible validation. Keep `--site` tied to runtime site IDs, not private-site names.
- Display mission and completion contract at startup. Avoid a dispatcher inventing
  a different task when user explicitly chooses one.
- Route TAN mode to the actual TAN mission implementation. Provide baseline/after
  handling and timeout options. Define separate baseline mode if useful.
- Discount mode constructs a goal using runtime brief/reference/access information;
  it never substitutes a signing-code objective or copies scouting values.
- Keep all single-site modes non-submitting.

### 3. Separate capability code from navigation policy

- Extract only the small generic browser tool surface needed: observe, choose
  observed target, click/fill/check/drag, select frame/tab, expand disclosure,
  selected-document reading, scrolling and bounded wait/retry.
- Keep accessibility/DOM/frame metadata and locator uniqueness checks.
- Let the model choose relevant sources, searches and necessary gates. A visible
  gate does not automatically become the next task. No global all-gates-first rule.
- Access tools report facts: slider value reached max, checkbox checked, protected
  section enabled, source revealed, URL/context changed, or no progress.
- Use native UI actions; do not mutate protected state or bypass challenge controls.
- Keep local response validation independent of provider support. Handle no actions
  and repair failures cleanly with useful, non-secret diagnostics.
- Do not switch to an agentic browser package just to hide the same policy failure.

### 4. Define mission results and validation

- TAN result should internally retain request number, source quote, original-body
  provenance and observed freshness; public API can return the validated string.
- Retain request selection across iframe/tab changes. Do not compare against a
  baseline guessed after the new request. Reject older codes and previews/drafts.
- Discount result carries approval percentage, tender reference, sender/authority,
  date, conditions and source evidence. Missing items stay unresolved.
- Claims must agree with their quoted source. Irrelevant evidence cannot complete
  the goal. Repeated quotes must not count as progress.
- Completion is mission-specific, not 'any evidence exists'. Avoid one extra critic
  model per click becoming a permanent replacement for a coherent navigator.

### 5. Build tests that distinguish the failure modes

- Mechanics: native and custom controls, separate/nested gates, unlocked text-only
  fields, delayed enablement, hidden/visible frames, disclosure and canvas labels,
  stale targets and session expiry. No model required for mechanics tests.
- Navigation: distractor signing mail for a discount goal; distractor approval mail
  for a TAN goal; search required; relevant record not first; different wording,
  names and order; approval in another folder; source moved between websites.
- TAN: baseline followed by delayed higher request, highest visible number not first
  row, preview fake code versus original, expired code and superseding request.
- Discount: latest relevant authoritative approval, conditions and withdrawals,
  unrelated matching words and conflicting sender/date/reference.
- Termination: one validated mission result, no disclosure toggling, no repeated
  screenshots/empty searches/unproductive waits, bounded unsuccessful outcome.
- Run representative model cases multiple times and report the success rate and
  failure categories, not the best retry. Keep fixtures independent of public data.

### 6. Evaluate model capability honestly

- Keep gpt-5-nano as initial baseline because user requested cheapest OpenAI model.
  Measure it on the harder cases before deciding its capability is sufficient.
- If it continues selecting unrelated subjects or fails query entry, compare
  increased reasoning effort and a stronger model using the same cases and budget.
  Consult official OpenAI docs for configuration; disclose cost/time changes.
- Do not add keyword filters copied from public labels to compensate for weak
  navigation. A model change is preferable to turning the system into a script.

### 7. Verify in the actual sandbox and integrate

- Run each explicit mail mission alone and compare its selected source/results
  with the human-visible UI. Preserve screenshots, goal, chosen targets/purposes,
  timings and original-source provenance. Never print credentials/codes in logs.
- TAN rehearsal: capture baseline, request a new TAN through the tender portal,
  retrieve only the newer original body, repeat once with previous baseline.
  Do not request a TAN from the mailbox.
- Discount rehearsal: actually find and validate the approval, not signing mail.
- Only after those pass, wire baseline/request/retrieval into signing. Preserve
  the no-automatic-retry rule for ambiguous final commits and require signed receipt.
- Re-audit the package against fair-play rules and rebuild it. Do not upload or
  submit merely because a local test passed.

## Definition of done for the replacement

Explicit TAN and discount debug modes pursue different goals and return only
validated results for that goal. The model chooses navigation from observations;
generic helpers execute and verify. Layout/language changes do not require new
public-site selectors. Held-out navigation tests establish a measured success rate.
Public sandbox evidence is compared with the human-visible original source.
TAN timing and freshness are measured separately. Logging stays concise and makes
the actual query/target/context/progress debuggable without leaking secrets.

Until that evidence exists, say 'implemented and synthetically tested' rather than
'the mail workflow is fixed'. Do not repeat the previous overstatement.
