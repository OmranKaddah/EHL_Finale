# Teammate review — 11 October 2026

Development notes only; excluded from the submission archive. Reviewed the supplied
`Adira-run_f05251da9da4734c` runtime files and the score pasted by the user.
The directory contains no complete fact/calculation log tying the supplied score
to a particular execution path. Its `r28.out.tmp` is a partial log. Do not assume
this source version exactly reproduces the scored answer.

## What the result establishes

The teammate achieved an eligible signed bid and 37.4/100. Our code has not yet
established an eligible receipt. Architectural complexity does not establish
superiority over a working submission.

| Area | Supplied score | Implication |
| --- | --- | --- |
| Decision/reference | 10/10 | Correct submission identity |
| Quantities | All five correct | Quantity changes, units and withdrawals were handled successfully in this answer |
| Materials | All five wrong | Exact effective requirements and material status need investigation |
| Prices/components | Almost entirely wrong or absent | Correct inputs and units must precede arithmetic |
| Delivery | Two lines correct | Shared stock and applicable commitments need verification |
| Arithmetic | 5/5 | Internal consistency does not prove source correctness |
| Discount | 5/5 | Preserve authoritative approval selection |
| Withdrawn Q&A check | 5/5 | Preserve the nonwithdrawn governing answer |
| Scenario-date metal index | 0/5 | Resolve index key, date window and mass from evidence |

The very small base prices are a reason to inspect price unit, scale and currency;
they are not proof of which conversion failed. The current `pricing.compute()`
already divides by price unit and includes every optional breakdown. Missing
breakdowns in the score may reflect the model-calculator fallback, an earlier
code version or different entered fields. Inspect actual facts and wizard inputs
before diagnosing a specific formula from the score.

## Reusable design choices

- Collect the governing technical requirements before launching exact-material
  searches. Quantities in pieces precede scale selection. Site allocation stays
  model-selected from runtime access, because facts can move on the private data.
- Preserve documents already selected by the model when a worker deadline expires.
- Reserve substantial time for the wizard, signing code and actual receipt.
- Separate raw fact extraction from deterministic Decimal arithmetic.
- Fill related form fields efficiently, while reobserving dependent controls and
  checking their actual saved values.
- Treat only the signed receipt as success. A saved draft and a returned answer
  object are insufficient for a website submission.

## Techniques we should not copy directly

Their extraction/calculation prompts insist on the closest material when an exact
match is missing, assume unclear material status is active, and permit guesses for
unknown inputs. Those can keep a bid moving but conflict with accurate technical
resolution. Keep unknown facts unresolved and explicitly omit unfinished lines
when the runtime brief permits it. Never convert incomplete investigation into
proof that no matching material exists.

Their tools directly assign slider values/events, read hidden/collapsed frame HTML,
automatically close overlays, and accept every browser dialog. We retain verified
native gate gestures, model-selected navigation, visible original-source evidence,
and an explicitly authorized commit. Fair-play allows helpers executing model
choices; it does not establish that every technique in an eligible test package
will pass scored review or transfer to a different private UI.

## Changes made in this session

- Root manifest explicitly selects OpenAI gpt-5-nano/low through Atira's proxy,
  with no Qwen warm-up.
- Typed bidder identity values exclude labels/punctuation; malformed extraction
  gets one bounded retry, and each value remains a verbatim source substring.
- Model reports the current business stage and sees a focused goal for that stage;
  there is no fixed route, German selector or predetermined wizard sequence.
- Browser observation is bounded to 30 seconds with one reread; action execution
  is bounded to 45 seconds. This exposes stalled browser reads instead of waiting
  for nearly the whole run deadline.
- Submission schema works from a blank page using the runtime submission site.
- Failed later evidence reviews retain the prior validated answer. Review transport
  errors preserve the candidate and evidence; full workflow reserves eight minutes
  and can attempt a source-audited all-omitted fallback if commercial resolution fails.
- Surcharge breakdown includes ordinary and allocated setup cost per piece.
- Answer validation accepts absent optional breakdowns, as the runtime schema permits.

No scenario answers, public identifiers, prices or credentials were copied into
runtime code. No new files were added under tests/. Compilation, inline identity,
price-unit/setup, optional-breakdown and submission-schema checks passed. Platform
diagnostics and remaining limitations are tracked in NEXT_SESSION.md.

## Next acceptance criteria

First: a fresh unattended minimum diagnostic reaches an actual signed receipt and
platform eligibility. Then: one offered line with its governing requirement,
exact active material, quantity, valid condition/scale/unit/FX, source-backed costs
and delivery verified against the entered wizard. Add the remaining positions
only as their evidence dependencies become complete. Run separate discount and
fresh post-request TAN missions; one does not prove the other.
