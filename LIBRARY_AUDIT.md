# Library audit

The initial implementation already had a library-oriented core, but its interface
composition and import behavior were not consistently library-safe. This audit
was performed against the source before refactoring; capabilities below were
not inferred from the README alone.

| Question | Initial implementation | Result after changes |
| --- | --- | --- |
| 1. Importability | Hatchling `src` layout, distribution name, and editable-build configuration were present. Tests injected `src` via pytest, so they did not prove external installation. | Editable installation and imports are tested from an external consumer directory with isolated Python startup and no PYTHONPATH. |
| 2. Modularity | Parsing, extraction, embeddings, Typesense, matching, workflow execution, and the scheduler were separate modules. Validation lived in Pydantic models/extractors. No optimization module. | Existing imports retained; shared composition is now public in `pipeline.py`. Validation and optimization limits remain explicit. |
| 3. CLI independence | Core operations were importable, but `cli._run` contained backend/parser assembly, direct-versus-parsed routing, indexing composition, and extraction/submission worker logic. API extraction duplicated that logic. | CLI and API call `create_pipeline`, `DocumentPipeline`, `create_search`, and `ExtractionWorker`. Interfaces retain argument/request handling, serialization, and lifecycle control. |
| 4. Dependency independence | Most ML imports were lazy. `api.py` called `create_app()` at import, creating uploads, JobStore, and cache. Matching initialized a Pint registry on import. HTTP clients were imported eagerly by search/output. | API import has no resource initialization; old ASGI entry point is lazy. Pint registry and HTTP integrations load on use. Core imports work with optional packages unavailable. |
| 5. Configuration | Component constructors accepted clients/models/options; `Settings(...)` existed. However, only `Settings.from_env()` validated values, and CLI/API owned composition. | Settings validation also applies to explicit construction. Public factories default to explicit Settings and accept injected clients, parser, extractor, limiter, cache, and retrieval dependencies. |
| 6. Async support | Parsers, extractors, embeddings, search, RAG, workflow execution, submission, and JobProcessor already exposed async methods. | Preserved. New pipeline/worker methods are awaitable. Ingestion, validation, matching, and SQLite helpers remain synchronous. |
| 7. Extensibility | Custom Pydantic schemas, Parser/ExtractionBackend protocols, Step callbacks, and JobProcessor callbacks were available. Submission adapters were usable by duck typing. | Documented extension examples and a Submitter protocol added. Custom adapters plug into ExtractionWorker. Optimization can be application code inside a Step/worker; no solver framework is claimed. |
| 8. Packaging | Hatchling package discovery and CLI entry point were correct. OpenAI, Pint, and HTTPX were mandatory; package root only exposed the version. | Pydantic-only base; optional integration extras; lazy convenience exports; package description/readme metadata; editable metadata and outside-source execution tests. |

## Actual public APIs retained

- `ingestion.ingest_file(path)` / `ingest_bytes(data, filename)` produce `Document`.
- `parsing.LLMDocumentParser(client=...).parse(document, ParseOptions(...))`,
  `DoclingDocumentParser`, `PyMuPDFDocumentParser`, and `TabularDocumentParser`
  return `ParsedDocument` via `await`.
- `extraction.OpenAIExtractionBackend(client=...).extract(source, schema)` and
  `GLiNERExtractionBackend.extract(...)` return `ExtractionResult` via `await`.
  GLiNER also exposes `extract_records(source, record_schema, group)`.
- `embeddings.EmbeddingService(client=...).embed(texts)` returns vectors via `await`.
- `search.TypesenseSearch(api_key=..., client=..., embedder=...)` exposes async
  `ensure_collection`, `index`, `search`, `delete`, and `health`.
- `matching.match_requirements(requirements, specifications, hierarchy=...)`
  returns a deterministic `MatchReport`.
- `workflows.run_workflow([Step(...)], initial=...)` executes custom async steps.
- `processing.JobProcessor(worker, store)` exposes `start`, `submit`, `recover`,
  and `stop`; the worker is an injected async callable.
- `output.LocalSubmitter.submit` and `HTTPSubmitter.submit` are async;
  `export_results` is synchronous.
- `cache.CachedParser` / `CachedExtractor` wrap the same component interfaces.

For complete copy-paste examples, see [LIBRARY_USAGE.md](LIBRARY_USAGE.md).

## Verification and limits

Verification result: **48 tests passed**, including all 37 original tests. The
exact `pip install -e .` command also succeeded in a fresh environment with only
base dependencies. All core modules imported there, and the complete documented
pipeline executed from `/tmp` without any optional integrations installed.

The original tests are retained. Added tests install the distribution with pip
editable mode in a consumer environment, verify editable package metadata,
import all core modules with optional imports blocked, check API import side
effects, exercise injected async components, and execute the documented challenge
pipeline outside the source tree. Consumer tests use preinstalled test/build
dependencies and `--no-index --no-deps --no-build-isolation` to run offline; they
still perform a real editable build/install rather than changing sys.path.

No generic optimization problem model, solver, or separate validation service
exists. No automatic plugin discovery is required: injection, protocols, and
ordinary Python functions are the extension mechanisms. GLiNER has flat-schema
limits, and custom JSON Schema loading supports only a subset. Calling async
methods does not make every internal operation nonblocking: local file/SQLite
helpers and injected local model implementations can perform synchronous work.
Live OpenAI/Typesense requests and model downloads are not part of this offline
verification. Runtime import behavior and client contracts are tested with fakes.

The only installation migration is to request extras for integrations previously
included by default, e.g. `pip install -e '.[llm,search,matching,api]'`. Existing
component names, CLI commands, and HTTP endpoints are preserved. `api.app` remains
an ASGI entry point; direct FastAPI object consumers should use `create_app()`.
