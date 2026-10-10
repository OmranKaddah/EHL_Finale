# Verification and rehearsal report

Work continues on `fresh-start`; `main` and `origin/main` remain at `6fa31a6`. No remote push, scored submission,
paid-provider inference, or team-setting change was performed. New implementation code is independent of main.

## Synthetic and local verification

- Python 3.12, frozen `uv.lock`, runtime `uv sync --frozen --no-dev`; Windows development and Linux sandbox setup verified.
- Latest full suite: **81 passed**; `uv run ruff check .` passed. The changed browser fixture was subsequently rerun:
  five integration tests passed, including both signed mock layouts, frame handling, stale controls, real session
  renewal, archived mail, transient ERP failure, transient tooltips, dynamic screenshot dimensions and SSE delivery.
- Browser orchestration tests use an observation-conditioned **model double**. They do not prove live Qwen accuracy.
- Hosted Qwen smoke: real `READY` response in `artifacts/model-smoke-verified/`; real named-tool selection in
  `artifacts/native-tool-smoke/` selected the requested current synthetic control in 2.7 seconds.
- Local dashboard rendered and was inspected earlier in `artifacts/dashboard-verification.png`; endpoint/SSE tests
  cover the updated viewer. Sanitized local events, evidence and screenshots remain under ignored `artifacts/`.
- Archive tests verify repeated builds have identical hashes despite source mtime changes, exclude local state,
  and contain only regular files with a root manifest. Archive and exact CLI manifest are inspected before uploading.

## Public scouting

`scripts/run-local.ps1 -TraceDir artifacts/public-full-5` is the current visible rehearsal. Earlier attempts:

| Trace directory | Observed result |
| --- | --- |
| `artifacts/public-navigation/` | Tender navigation, modal recovery, selected documents and five position records; short step limit. |
| `artifacts/public-full/` | Hidden-password observation loop; fixed by exposing only `filled` and retaining opaque credential handles. |
| `artifacts/public-full-2/` | Citation used a control ref as page ID; fixed by resolving the ref to its observation while checking the quote. |
| `artifacts/public-full-3/` | Q&A reached; malformed record transport and unknown citation IDs prevented completion. |
| `artifacts/public-full-4/` | Real session-expiry recovery, one long Qwen timeout and missing action discriminator; stopped locally to apply native tools. |

No public scouting acknowledgment has been verified yet. A local run or open configurator is not a signed acknowledgment.

## Unscored sandbox runs

Started with the existing authenticated Adira CLI using:

```powershell
atira test-run . --challenge rfq --dry-run --json
atira test-run . --challenge rfq --no-open --json
uv run scripts/atira-debug.py get_run --run-id <id> --out artifacts/<name>.json
uv run scripts/atira-debug.py diagnose_run --run-id <id> --out artifacts/<name>.json
```

### First run — failed, no submitted answer

- Run: [run_208dd5bc4633b50f](https://ehl-challenge.atira.ai/runs/run_208dd5bc4633b50f)
- Rehearsal: `reh_20633baa2613f0fa`.
- Package: `c4d5ca89c1f8c7406281706dca161906eb49aa8997d1f81f988abae295753b0f`, 40 files, 104,288 compressed bytes.
- Official result: exit code 2 without submission; 20:07 elapsed, 95 model calls, 788,489 input and 52,918 output tokens.
- Final `get_run` diagnosis reports quality **0**, not eligible, and simulated cost **$0.1492**. The compact status
  endpoint returned `score: null`; there was no accepted answer to score. Qwen usage remains free to the participant.
- Artifacts: `artifacts/sandbox-first-final.json`, `artifacts/sandbox-first-diagnosis.json`,
  `artifacts/sandbox-first-logs.jsonl`, and later snapshot `artifacts/sandbox-snapshot.jsonl`.
- Official recording inventory initially reported **none**; no recording review is claimed.
- Fixed failures: serialized citation lists, ambiguous same-label loop detection, slow tooltip-by-tooltip inspection,
  rejected extraction retention and missing position-level setup/unit/bonus fields.

### Second run — failed, no submitted answer

- Run: [run_3ea40a1368cc156a](https://ehl-challenge.atira.ai/runs/run_3ea40a1368cc156a)
- Rehearsal: `reh_2e50be2628773075`.
- Package: `9c711652fdc4f1e0a607de61e81078a491bceec30f41ce7133569903ac745065`, 43 files, 109,303 compressed bytes.
- Live evidence: combined disclosure inspection successfully collected dated Q&A batches. Missing schema fields
  exposed position-specific setup and keyed bonus requirements; those were fixed locally after this upload.
- Artifacts: `artifacts/sandbox-second-launch.json`, `artifacts/sandbox-second-status.json`,
  `artifacts/sandbox-second-logs.jsonl`.
- This package predates the native named-tool interface and the latest business-rule corrections.
- Official result: eight consecutive tool/model failures; 12:40 elapsed, 81 calls, 912,885 input and 28,716 output
  tokens, quality **0**, not eligible, simulated cost **$0.1561**. No answer and no recording were available.
- Terminal blocker: repeatedly clicking a modal close button clipped by an iframe in the supplier document viewer,
  mixed with missing action discriminators. Generic keyboard activation after a confirmed pre-click viewport failure
  and native named tools address these failures; no public selector or route was added.
- Focused failure evidence: `artifacts/sandbox-second-errors.json` and `artifacts/sandbox-second-last-actions.json`.

## Local commits and Entire

| Commit | Verified checkpoint |
| --- | --- |
| `461e966` | `01M4K4NG1E9B81SVN4TW2DX4WE` |
| `ea3648e` | `01M4K4ZP2T6WY88FAN9FWX28GR` |

The hook was waiting on a hidden terminal confirmation. Interactive execution allowed normal capture and commit.
Entire also retained an earlier degraded-capture warning; the listed checkpoints were explicitly verified afterward.

## Remaining acceptance work

No live signed receipt is verified. Complete the current scouting run and evaluate the corrected package again.
Do not describe passing mocked tests or zero-quality failed runs as an
accepted sandbox submission. The 180-second reserve remains an initial setting until real signing duration is measured.

## Multi-agent rebuild status

The prior two sandbox attempts and public scouting traces above predate the four-browser architecture. The current
implementation uses a browserless coordinator, four CDP-pinned specialists and a shared cited ledger. Each specialist
writes a separate trace; the local dashboard renders four sanitized browser panels. Qwen dispatches opaque runtime
site assignments and each specialist remains model-directed inside its assigned browser. Clef may classify a sanitized
probable popup as advisory context only; it never chooses an action or solves a verification gate.

The new architecture has passed local synthetic/unit regression tests and an offline dependency-scheduling comparison.
It has **not** yet been exercised in public scouting or an unscored sandbox run. The benchmark is a schedule model,
not a claim about live Qwen latency: sequential 490 seconds, dependency-aware parallel 305 seconds under the declared
synthetic durations. When two specialists fail before the reserve, the coordinator runs one bounded sequential
recovery pass using an existing supplied browser.

## Four-browser public scouting rehearsal — 2026-10-10

Command: `./scripts/run-local.ps1 -MaxSteps 180 -TraceDir artifacts/multi-agent-rehearsal-1`.

This was a local, headful scouting rehearsal, not a sandbox evaluation and not a scored submission. Qwen dispatched
the four opaque site assignments and the four specialists concurrently reached their own login and consent flows.
The tender specialist registered participation, closed a delayed survey modal, opened the tender record and its
document/Q&A menu. The specifications specialist reached the document register. The ERP specialist handled a
transient service page, and the mail specialist reached the inbox. Per-agent screenshots and redacted event streams
are in the ignored `artifacts/multi-agent-rehearsal-1/` directory.

The ERP and mail pages then exposed explicit robot/CAPTCHA-style verification gates. The implementation now records
those as `verification_gate_skipped` and ends the affected research specialist without dragging, ticking, copying a
visual challenge, or attempting to bypass it. The coordinator can continue with independent evidence, but a final
submitting controller fails closed if a required gate remains. This is a safety boundary, not a completed bid.

The optional Clef proxy returned `NotFoundError` on the first popup-classification requests and subsequently became
unreachable because this machine could not resolve `ehl-challenge.atira.ai`. The failure was nonblocking and did not
alter browser actions. Clef remains limited to sanitized, advisory popup classification; its endpoint contract must
be verified against a reachable Atira proxy before claiming a successful Clef-assisted rehearsal.
