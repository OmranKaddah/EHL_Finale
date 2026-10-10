# Next-session handoff: rebuild the mail policy, keep the browser tools

## Implementation update (read before the older handoff below)

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
