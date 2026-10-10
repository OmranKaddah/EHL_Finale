# Verification status and remaining risks

This file is updated from actual test/rehearsal results. Do not infer challenge completion from implemented modules.

## Verified so far

- Python 3.12 frozen dependency setup and the platform entrypoint.
- Hosted Qwen responds through the authenticated local Atira proxy without a personal API key.
- Deterministic pricing, evidence and runtime tests.
- Synthetic UI extraction, pricing and TAN-signed receipt on two layouts, including an iframe layout and transient error.
- Local dashboard HTTP state and browser protections.

## Risks to validate live

1. Qwen may spend too many turns gathering the complete four-site evidence within the signing reserve.
2. Semantic extraction/completeness claims remain model judgments; citations ensure real source excerpts, not perfect
   interpretation. Rehearsal scoring is needed to identify wrong field mappings.
3. Partial pricing deliberately blocks when any material/quantity remains unresolved because it can affect shared
   stock and other order dependencies. This is conservative and may reduce partial credit.
4. Setup allocation supports largest remainder, HALF_UP shares with residual on the last position, and floored shares
   with residual on the last position. An unfamiliar source rule is unresolved instead of silently approximated.
5. PDF images are available when text extraction is sparse. Non-PDF binary formats require the site's visible viewer.
6. Automatic receipt recognition requires a visible tender reference and confirmation identifier; unfamiliar receipt
   layouts must still be read and mapped by the model.

See the eventual rehearsal report for live run IDs, official scores and observed blockers.
