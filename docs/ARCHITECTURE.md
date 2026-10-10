# Architecture

The entrypoint validates configuration and runtime access, opens the redacted event stream, attaches to the supplied
browser (or launches visible local Chromium), and starts one controller. No prior solution or starter-kit source was copied.

## Data flow

1. The browser observes visible text and controls across frames. Control handles are scoped to that observation;
   navigation refreshes them. Popups, browser dialogs and chosen downloads become new observations.
2. Qwen receives the sanitized brief, current observation, recent actions, record ledger and remaining budget. It
   returns one validated `AgentAction`; malformed actions receive a concise error on the next turn.
3. `cite` requires an exact excerpt in a retained observation. `record` validates typed source records and existing
   evidence IDs. The ledger preserves competing dated records; replacing a record emits a conflict event.
4. The rule engine selects effective quantities, revision-scoped engineering, authorized dated records and exact
   active materials. Pricing uses Decimal at precision 40 and explicit HALF_UP rounding.
5. Calculation returns a schema-valid answer or explicit unresolved dependencies. Partial mode excludes unresolved
   lines only after dependencies on the whole tender are available. It never invents missing prices.
6. Submission maps computed answer paths to model-selected visible controls. TAN values remain opaque to logs.
   Signing and receipt verification are separate states; an uncertain signing action is not automatically repeated.

## Interfaces

`RunContext`, `Observation`, `AgentAction`, and `EvidenceFact` define external data boundaries. Typed records represent
tender positions, specifications, ERP materials/conditions, search conclusions, Q&A and each authorized mail rule.
`PricingResult` carries an answer, omitted positions, unresolved dependencies and calculation audit.
`SubmissionState` distinguishes drafts, validated answers, TAN requested, attempted signing, scouting acknowledgment
and accepted sandbox submission.

One browser and several tabs are used. Independent parallel investigators are intentionally deferred until the
single-controller behavior is measured. Qwen-only inference has bounded retries and deadlines; there is no automatic
paid-provider fallback. No model-generated Python, JavaScript or shell is executed.

## Observability and privacy

Structured events are the shared source for stdout, durable JSONL and a localhost SSE viewer. Events carry run/action
identity, time, active site and tab. Slow viewers receive a bounded queue and cannot hold up the controller.
Known secrets and token-bearing URLs are redacted centrally. Screens containing login credentials/TANs are omitted;
editable screenshot fields are masked. Raw browser profiles, cookies and Playwright trace archives are not persisted.

The ledger proves where quoted evidence came from; semantic extraction and completeness judgments still depend on
the model. Synthetic tests validate the machinery, while public and sandbox rehearsals measure the actual model's
ability to obtain and interpret evidence. Neither is a substitute for the other.
