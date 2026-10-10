# Architecture

The entrypoint validates configuration and runtime access, opens the redacted event stream, then starts a browserless
coordinator and four domain specialists. Each specialist attaches exclusively to one supplied CDP browser (or, locally,
launches one visible Chromium) and is restricted to its assigned runtime website. No prior solution or starter-kit source was copied.

## Data flow

1. Tender, specification, ERP and mail specialists observe visible text and controls across their own browser frames.
   A short browserless Qwen dispatch assigns the opaque runtime sites once; invalid or unavailable dispatch falls back
   to a one-to-one runtime-metadata mapping. The coordinator publishes a dependency-aware role brief and shares only typed,
   cited ledger records rather than raw histories. Control handles are scoped to that observation;
   navigation refreshes them. Popups, browser dialogs and chosen downloads become new observations.
2. Qwen receives the sanitized brief, current observation, recent actions, record ledger and remaining budget. It
   selects one named tool, normalized into a validated `AgentAction`. This avoids a redundant nested action field;
   malformed arguments receive a concise error on the next turn. A real hosted-Qwen tool call verifies compatibility.
3. `cite` requires an exact excerpt in a retained observation. `record` validates typed source records and existing
   evidence IDs. Inline citations can accompany batches. Rejected records remain separate from usable evidence,
   with missing fields retained for correction. The ledger preserves competing dated records and extraction replacements.
4. The rule engine selects effective quantities, revision-scoped engineering, authorized dated records and exact
   active materials. Pricing uses Decimal at precision 40 and explicit HALF_UP rounding.
5. Calculation returns a schema-valid answer or explicit unresolved dependencies. Partial mode excludes unresolved
   lines only after dependencies on the whole tender are available. It never invents missing prices.
6. Submission maps computed answer paths to model-selected visible controls. TAN values remain opaque to logs.
   Signing and receipt verification are separate states; an uncertain signing action is not automatically repeated.

`inspect_controls` captures each transient disclosure before clicking the next model-selected control.
`read_links` reads at most six links explicitly selected from the current observation and restores the source tab.
Neither helper discovers targets. Each resulting observation retains source identity and acquisition action.
Position-level setup amendments, quantity units and keyed bonus membership are resolved before whole-order pricing.

## Interfaces

`RunContext`, `Observation`, `AgentAction`, and `EvidenceFact` define external data boundaries. Typed records represent
tender positions, specifications, ERP materials/conditions, search conclusions, Q&A and each authorized mail rule.
`PricingResult` carries an answer, omitted positions, unresolved dependencies and calculation audit.
`SubmissionState` distinguishes drafts, validated answers, TAN requested, attempted signing, scouting acknowledgment
and accepted sandbox submission.

Four browser-pinned specialists perform safe discovery concurrently. The ERP specialist consumes resolved requirements,
and the mail specialist consumes the tender reference; both can still learn their site safely while those dependencies
are pending. A failed specialist is isolated, its unresolved evidence stays explicit, and the coordinator makes a
bounded targeted recovery pass before partial-bid policy applies. Pricing, schema validation and portal signing remain
centralized. The tender specialist fills the portal; after it requests a TAN, the mail specialist retrieves the newest
matching message and hands the opaque value back without logging it. Qwen-only inference has bounded retries and
deadlines; there is no automatic paid-provider fallback. No model-generated Python, JavaScript or shell is executed.
If two or more specialists fail before the submission reserve, the coordinator stops pursuing agent count and reuses
the already supplied tender browser for one bounded sequential recovery pass across the runtime sites. It does not
launch another browser or retry uncertain signing actions.

## Observability and privacy

Structured events are the shared source for sandbox stdout, durable JSONL and a localhost SSE viewer. Every specialist
writes an independent redacted trace directory; the browserless coordinator owns the shared ledger and pricing trace.
The local dashboard renders four sanitized browser panels plus a merged timeline and dependency/pricing state. Events
carry agent/run/action identity, time, active site and tab. Slow viewers receive a bounded queue and cannot hold up an agent.
Known secrets and token-bearing URLs are redacted centrally. Screens containing login credentials/TANs are omitted;
editable screenshot fields are masked. Raw browser profiles, cookies and Playwright trace archives are not persisted.
Pixel actions require a fresh image and use its actual dimensions. The archive helper normalizes timestamps and
ownership to produce reproducible regular-file-only tarballs, independently of the Atira CLI upload packer.

The ledger proves where quoted evidence came from; semantic extraction and completeness judgments still depend on
the model. Synthetic tests validate the machinery, while public and sandbox rehearsals measure the actual model's
ability to obtain and interpret evidence. Neither is a substitute for the other.
