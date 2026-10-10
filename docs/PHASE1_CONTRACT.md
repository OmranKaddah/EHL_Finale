# Phase 1 delivery contract — eligible first

## Outcome

The parent orchestrator accepts this milestone only when the official sandbox result confirms `eligible=true` for an accepted, TAN-signed tender-portal submission completed within 20 minutes. Tests, a saved draft, process exit 0 and a locally printed receipt are not enough. Official review `passed` is a separate gate for scored leaderboard visibility.

## Authority

The user's full EHL Challenge brief, complete Fair play and supplemental rules are authoritative. The live run brief/schema supply runtime scenario inputs. No public-scenario values, copied answers, credentials, reference identifiers, TANs or fixed navigation paths may enter the package or runtime prompts/notes/defaults. Local research, Obsidian and Entire history are development-only, never runtime evidence.

## Minimal architecture

Preserve Playwright supplied-CDP control and model-directed page/search/document decisions. Add a deadline-bounded coordinator and a transactional submission controller. Model-selected helpers may observe/extract/parse/paginate/calculate/validate/retry/fill. No complete-site crawler, fixed click sequence, extra run browser, local model or external runtime service.

State sequence: BOOT -> IDENTIFY -> INVESTIGATE/PREPARE -> VALIDATE -> FILL -> REVIEW -> REQUEST_TAN -> READ_TAN -> SIGN -> VERIFY_RECEIPT -> ACCEPTED.

Research cutoff must leave at least six minutes for filling/signing; live expires_at can shorten the budget. One mutation owner per browser/page. The tender owner alone signs; mail owner returns only the newest matching requested TAN. Do not persist TAN or credential values in long-term traces.

## Partial-bid policy

First investigate the real configurator prerequisites under scouting. Whether all positions can be explicitly omitted and still signed is an experiment, not a proven fallback. Prefer one or more evidence-backed complete positions when viable, with all unfinished positions explicitly omitted in the UI/review. Do not invent a material, unit price, bidder registration or approval to satisfy required fields. Never use no_bid merely because research is incomplete. A genuine no_bid requires a completed narrow catalogue search with no active exact match.

A position can depend on other lines: shared material demand/commitment, whole-order base-goods discount threshold, setup pools and eligible bonus. Preserve these dependencies; optional breakdown blanks are not known zero and cannot become zero inputs to a final price. Resolve or omit affected positions.

## Test-first and delivery

For new runtime behavior: one vertical RED -> GREEN -> REFACTOR cycle at a time. First demonstrate missing behavior with a real assertion, then implement minimally and run full regressions. Baseline: Python 3.12, `uv run --python 3.12 --frozen python -m unittest discover -s tests -v`; 12 baseline tests passed. Use invented fixtures excluded from the submitted package.

Test wrong tender/TAN, stale receipt, draft-only save, repeat signing after timeout, stale controls, explicit omission review, schema/Decimal consistency, deadline cancellation, and supplied-CDP-only run mode. Eligibility smoke tests must not require all pricing rules when the UI supports honest explicit omissions.

Package using an explicit file allowlist: manifest, frozen dependencies, runtime source and generic prompts only. Exclude tests, docs with scenario facts, Obsidian, .env, artifacts, browser profiles, .entire stores/transcripts and Brain. Setup <=5 minutes; compressed payload <=20 MB; Python 3.12 supported. All runtime model calls use the run proxy.

## Agent ownership

- Codex scout: live local scouting investigation only, model-directed; no production edits, git commits, scored submission or test-run uploads. Write sanitized findings to ignored/local scratch, no scenario facts in package.
- Claude implementation: runtime/test/packaging implementation on Leonie, with TDD; no live/scored submission, no push/merge, no interaction with teammate runs. May create one documentation/setup baseline commit once captured by Entire; code commits require parent review.
- Hermes parent: interpret scouting findings, enforce integration/contract, independent review, run real validation, commit/push milestones and read back exact GitHub/Entire refs, then launch authorized test-run. Never disturb the other team branches or running jobs.

## Recording

Each substantive milestone records goal, changed components, exact test command/result, known limitations, git SHA and Entire checkpoint. An Entire-Checkpoint commit trailer alone does not prove the checkpoint was captured/pushed; verify the ref/content. Development transcripts are private and must not be bundled in solver packages.
