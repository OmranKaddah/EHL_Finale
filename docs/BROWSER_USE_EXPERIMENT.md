# Browser-use navigation experiment

Branch: `experiment/browser-use-specialist`.

This development-only experiment compares the existing specialist loop with
browser-use 0.13.11 on synthetic stock lookups. It does not change the challenge
runtime, submission gates, dependency lock, or packaged agent.

Both backends use the configured Atira Qwen proxy. Each pair gets identical generated
records, paths, layouts and popup conditions, with a fresh Chrome profile for each
attempt. Four cases cover direct/hidden navigation with/without a blocking optional
survey. Backend order alternates to reduce order effects. Clef is disabled for both.

Browser-use uses its native navigation tools and DOM observations, up to five actions
per step, and two custom tools that capture observations and validate exact citations
through the existing EvidenceBook. It uses no screenshots or final judge call in this
probe. Its native tools have not been adapted to the challenge's full restrictions;
the harness only serves invented local data and cannot take a live task URL.

## Run

Create a separate Python 3.12 environment so this experiment cannot change the main
agent's installed dependencies:

```bash
uv venv .venv-browser-use --python 3.12
uv pip install --python .venv-browser-use/bin/python -r requirements-browser-use.txt
atira models proxy
```

In another terminal:

```bash
QWEN_BASE_URL=http://127.0.0.1:8765/qwen/v1 PYTHONPATH=src \
  .venv-browser-use/bin/python scripts/probe_browser_use.py --repeats 3
```

Use `--cases 1 --seconds 90` for a short integration check. `--backend current` or
`--backend browser-use` runs only that backend. `--seed` reproduces generated data;
the model itself remains nondeterministic. `--flash-mode` tests browser-use's shorter
reasoning/output mode. Chrome must be installed or supplied with
`--chrome /path/to/chrome`. The script starts and terminates its own local browsers.

## Assess results

Artifacts live in `.rfq-artifacts/browser-use-probe/<timestamp>/`:

- `config.json`: experiment settings and package version.
- `outcomes.json`: per-attempt wall time, HTTP model calls/time, reported completion,
  citation correctness and errors.
- `<repeat>-<case>-<backend>/evidence.json`: actual source observations and citations.

A pass requires reported completion **and** a stored exact citation containing the
requested product and correct stock, from the matching result URL and query. A prose
claim or built-in `done` response alone is insufficient. Failed attempts remain in
the results; the command exits nonzero if any attempt fails.

Wall time includes backend initialization and cleanup, but excludes Chrome startup.
Model time includes failed/in-flight requests and is a subset of wall time. Compare
success rates first, then time and calls among successful paired cases. This compares
whole navigation loops with their different prompts, tools and retry policies; it is
not a controlled comparison of browser drivers alone. Direct dependencies are pinned;
transitive dependencies are not yet locked.

Before a live specialist integration, require repeatable gains across the four cases,
then preserve origin/observed-URL restrictions, worker ownership, signing guards,
human-verification handling, evidence publication, tracing and deadline cancellation.
A successful synthetic lookup does not establish completion of a 20-minute RFQ run.

## Initial trial — 10 October 2026

One paired case (seed 42, direct navigation, no popup), using Qwen through the Atira
proxy with a 90-second limit:

| Backend | Wall time | Model calls | Correct citation | Finished within limit |
| --- | ---: | ---: | --- | --- |
| Current loop | 64.4 s | 7 | Yes | Yes |
| Browser-use, flash mode, final judge disabled | 90.4 s | 6 | Yes | No |

Both found the record. Browser-use timed out waiting for its final response after
saving the citation. These results do not demonstrate a speed benefit. Artifact:
`.rfq-artifacts/browser-use-probe/20261010-202126/outcomes.json`.

An earlier integration smoke test with browser-use's default reasoning and judge
also reached the 90-second limit (current loop: 67.0 seconds). It exposed background
CDP cleanup that is now handled with an explicit browser-session stop; the tuned
trial exited cleanly. These two checks covered only the first fixture, not the
four-layout benchmark or any live RFQ. Repeat across layouts before drawing a
performance conclusion. The final timing transport additionally counts failed
requests accurately; that change has unit coverage and was made after this trial
started, so the recorded successful-call timings used the earlier HTTP hooks.
