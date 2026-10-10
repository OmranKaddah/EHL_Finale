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

### M0 — baseline

- Status: in progress (see the commit that adds this file).
