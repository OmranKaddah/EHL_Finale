# Using the toolkit as a Python library

The package is `hackathon_toolkit`; its distribution name is `hackathon-toolkit`.
Python 3.11+ is required. See [LIBRARY_AUDIT.md](LIBRARY_AUDIT.md) for the initial
findings, changes, and limits. The public imports below are supported interfaces;
underscore-prefixed helpers are internal.

## Install in your challenge project's environment

```bash
python -m pip install -e /absolute/path/to/EHL_Finale
# Or, from the toolkit repository:
python -m pip install -e .
```

Base installation requires only Pydantic. Install the extras for your task:

| Extra | Needed for |
| --- | --- |
| `llm` | Default OpenAI parsing, extraction, embeddings, and answering clients |
| `search` | Typesense HTTP requests; no Typesense Python SDK is needed |
| `http` | HTTP submission |
| `matching` | Unit conversion in numeric matching (unitless matching works without it) |
| `api` | FastAPI and Uvicorn |
| `local` | Docling and GLiNER; model weights load on first use |
| `office` | XLSX and local PDF parsing, plus the existing Office dependencies |
| `test` | Offline test suite, editable-build tooling, and lightweight test integrations |

For example, `python -m pip install -e '.[llm,search,matching]'` installs the live
retrieval/extraction path. Existing CLI users should add `llm` for the default
OpenAI commands. Installing a package does not start Typesense or other services.

All `await` snippets belong in an async function or an async notebook cell. In a
normal script, run your function with `asyncio.run(main())`. The complete example
below is a standalone script. Paths are relative to your working directory,
not the toolkit repository.

## Configuration and lifecycle

```python
from hackathon_toolkit.config import Settings
from hackathon_toolkit.pipeline import create_pipeline

settings = Settings(document_parser="tabular", chunk_size=2000, chunk_overlap=100)
pipeline = create_pipeline(settings=settings)  # no files, models, or services created
```

`Settings(...)` validates explicit values. Only `Settings.from_env()` reads
configuration from the environment; the CLI and default API factory call it.
Library factories default to `Settings()`. Components also accept individual
constructor arguments and do not require a Settings object.

Pass `cache=SQLiteCache(path)` explicitly to enable caching in library factories;
`Settings.enable_cache` controls CLI/API assembly. The factories do not create a
cache themselves. Constructing `SQLiteCache`, `JobStore`, or `LocalSubmitter`
explicitly creates its local resources. `JobProcessor.start()` starts its tasks;
`stop()` drains queued work and stops them. Merely importing any module does not
create databases, upload directories, requests, workers, or model instances.

Caller-injected clients belong to the caller: use `async with AsyncOpenAI(...)`
or `async with httpx.AsyncClient(...)` to close them. Default LLM clients are
created on first use and reused on the component; prefer injection for explicit
lifecycle management. Local ML weights may be downloaded on first inference.

## Ingestion and normalized models

```python
from hackathon_toolkit.ingestion import ingest_file, ingest_bytes, ingest_directory
from hackathon_toolkit.models import Document, ParsedDocument, chunk_document

document = ingest_bytes(b"model,memory_gb\nAX,64\n", "catalogue.csv")
# Alternatively: document = ingest_file("example.pdf", max_mb=20)
# documents = ingest_directory("inbox", recursive=True)
print(document.metadata.id)  # content SHA-256
```

`ingest_stream(stream, filename)`, `ingest_many(paths)`, and
`watch_directory(path, poll_seconds=1, stable_polls=2)` are also public.
The watcher is an async iterator; consume it with `async for` and cancel your
consumer to stop. A stream must be readable; use `ingest_bytes` when content must
remain in memory. Raw `Document` and normalized `ParsedDocument` are distinct.

## Document parsing

```python
from hackathon_toolkit.ingestion import ingest_bytes
from hackathon_toolkit.parsing import TabularDocumentParser
from hackathon_toolkit.models import chunk_document

document = ingest_bytes(b"model,memory_gb\nAX,64\n", "catalogue.csv")
parsed = await TabularDocumentParser(rows_per_table=100).parse(document)
print(parsed.text())
chunks = chunk_document(parsed, size=2000, overlap=100)
```

CSV needs no extra dependencies; XLSX uses `office`. Other implementations share
`Parser.parse(document, options=None) -> ParsedDocument`:

```python
from openai import AsyncOpenAI
from hackathon_toolkit.ingestion import ingest_file
from hackathon_toolkit.parsing import LLMDocumentParser, ParseOptions

async with AsyncOpenAI(api_key="YOUR_API_KEY") as client:
    parsed = await LLMDocumentParser(client=client).parse(
        ingest_file("example.pdf"), ParseOptions(model="gpt-4o-mini", timeout_seconds=120)
    )
```

`DoclingDocumentParser(converter=None)` accepts an injected converter;
`PyMuPDFDocumentParser()` handles PDFs. Both expose `await parse`.
For example, after installing `office`:

```python
from hackathon_toolkit.parsing import PyMuPDFDocumentParser
from hackathon_toolkit.ingestion import ingest_file
parsed = await PyMuPDFDocumentParser().parse(ingest_file("example.pdf"))
```

Or, with `local` installed:

```python
from hackathon_toolkit.parsing import DoclingDocumentParser
from hackathon_toolkit.ingestion import ingest_file
parsed = await DoclingDocumentParser().parse(ingest_file("example.pdf"))
```

The low-level parsers take `Document`, not filenames. `DocumentPipeline.parse`
accepts either. `ParsedDocument.text_with_sources()` returns text and source
spans; sections, tables, and blocks retain source references where available.

## Extraction and validation

```python
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from hackathon_toolkit.ingestion import ingest_file
from hackathon_toolkit.extraction import OpenAIExtractionBackend

class Product(BaseModel):
    model: str | None
    memory_gb: int | None = Field(ge=0)

async with AsyncOpenAI(api_key="YOUR_API_KEY") as client:
    extractor = OpenAIExtractionBackend(client=client, model="gpt-4o-mini")
    result = await extractor.extract(ingest_file("example.pdf"), Product,
                                     instructions="Extract the offered product.")
    validated = Product.model_validate(result.data)
    print(validated.model_dump())
```

`ExtractionBackend.extract(source, schema, *, instructions="", timeout=120)`
accepts raw `Document`, `ParsedDocument`, or text for OpenAI. Its return value is
`ExtractionResult`, whose `data` is a dictionary; evidence, warnings, and token
counts are separate fields. Pydantic handles schema validation and custom
`field_validator`/`model_validator` rules. There is no separate validation engine.

Built-ins are `RFQ`, `TechnicalSpecification`, and `GeneralDocument` in
`hackathon_toolkit.schemas`. `load_schema("technical")` loads a built-in;
`load_schema("challenge_schema.json")` loads the supported JSON Schema subset
(objects, arrays, scalar types, required/nullable fields). It is not a complete
JSON Schema implementation; use your own Pydantic model for richer constraints.

Local extraction, after installing `local`:

```python
from pydantic import BaseModel
from hackathon_toolkit.extraction import GLiNERExtractionBackend

class Entities(BaseModel):
    manufacturer: str | None
    product_model: str | None

backend = GLiNERExtractionBackend()
result = await backend.extract("Acme manufactures AX.", Entities)

class Record(BaseModel):
    product_model: str | None
    memory: str | None

records = await backend.extract_records("AX: 64 GB; BX: 32 GB", Record, "products")
```

GLiNER accepts parsed documents or text, not raw files. Entity mode supports
string and string-list fields; record mode supports repeated flat records,
not arbitrary nested schemas. Pass `model=your_model` to inject a model.
`choose_backend` and `select_backend` remain public routing helpers; explicit
`gliner` avoids cloud fallback, while `auto` can select OpenAI.

## Shared pipeline API

```python
from pathlib import Path
from pydantic import BaseModel
from openai import AsyncOpenAI
from hackathon_toolkit.config import Settings
from hackathon_toolkit.pipeline import create_pipeline

class Product(BaseModel):
    model: str | None

async with AsyncOpenAI(api_key="YOUR_API_KEY") as client:
    pipeline = create_pipeline(Product, settings=Settings(), client=client, parse_first=True)
    result = await pipeline.extract(Path("example.pdf"), Product)
```

Without `parse_first`, the factory uses direct raw-document extraction when both
selected components are LLM based, preserving the CLI's one-request behavior.
Other parser/backend combinations parse first. Injected parsers and extractors
also parse first. For complete control, instantiate
`DocumentPipeline(parser=parser, extractor=extractor, direct=False)`.
`extract` treats strings as text and `Path` objects as filenames; `parse` treats
strings as filenames. Parsed documents bypass parsing.

`await pipeline.index(document, search, embedder=embedder)` parses, chunks,
ensures the collection, and indexes vectors. Omit `embedder` for keyword-only
indexing. `chunk_size` and `chunk_overlap` are keyword arguments. Components can
be called separately without ever creating a pipeline.

## Embeddings and Typesense

```python
from openai import AsyncOpenAI
import httpx
from hackathon_toolkit.embeddings import EmbeddingService
from hackathon_toolkit.search import TypesenseSearch
from hackathon_toolkit.ingestion import ingest_bytes
from hackathon_toolkit.parsing import TabularDocumentParser
from hackathon_toolkit.models import chunk_document

async with AsyncOpenAI(api_key="YOUR_API_KEY") as llm, httpx.AsyncClient() as http:
    embedder = EmbeddingService(client=llm, dimensions=1536, concurrency=2)
    search = TypesenseSearch(api_key="YOUR_TYPESENSE_KEY", client=http,
                             host="localhost", port=8108, embedder=embedder)
    parsed = await TabularDocumentParser().parse(
        ingest_bytes(b"model,memory_gb\nAX,64\n", "catalogue.csv"))
    chunks = chunk_document(parsed)
    vectors = await embedder.embed([chunk.text for chunk in chunks])
    await search.ensure_collection()
    await search.index(chunks, vectors=vectors)
    hits = await search.search("64 GB", mode="hybrid", top_k=5)
    print([hit.chunk.text for hit in hits])
```

This needs running Typesense and `llm,search` extras. For keyword-only retrieval,
instantiate `TypesenseSearch(api_key=..., client=http)` without an embedder and
call `search(..., mode="keyword")`. `health()`, `delete(chunk_id)`, and `schema()`
are public; `schema()` is synchronous and performs no I/O. Embedding model and
dimensions must match between indexing and querying.

## Retrieval-augmented answers

```python
from openai import AsyncOpenAI
import httpx
from hackathon_toolkit.config import Settings
from hackathon_toolkit.pipeline import create_search
from hackathon_toolkit.rag import ask

# Requires the collection indexed in the preceding example.
async with AsyncOpenAI(api_key="YOUR_API_KEY") as llm, httpx.AsyncClient() as http:
    search = create_search(settings=Settings(typesense_api_key="YOUR_TYPESENSE_KEY"),
                           client=http, embedding_client=llm)
    answer = await ask("Which model has 64 GB?", search, client=llm)
    print(answer.answer, answer.supported, answer.sources)
```

Any search object with async `search(query, mode=..., filters=..., top_k=...)`
returning `SearchHit` items can replace Typesense. `ask` returns `Answer` and
needs no OpenAI SDK when a compatible client is injected.

## Deterministic matching

```python
from hackathon_toolkit.matching import Constraint, Specification, match_requirements, normalize_requirement

requirement = normalize_requirement("at least 32", "memory_gb")
report = match_requirements([requirement], {"memory_gb": Specification(value=64)})
print(report.overall.value)  # PASS
```

`Outcome` is `PASS`, `FAIL`, `UNKNOWN`, or `CONFLICT`. Unit conversion loads Pint
only when unit-bearing numeric comparisons occur. Supply a `hierarchy` mapping
for `or_better` comparisons. Matching scores are not an optimization solver.

## Caching, output, and submission adapters

```python
from hackathon_toolkit.cache import SQLiteCache, CachedParser, CachedExtractor, cache_key
from hackathon_toolkit.parsing import TabularDocumentParser
from hackathon_toolkit.extraction import OpenAIExtractionBackend
from hackathon_toolkit.output import export_results, LocalSubmitter, HTTPSubmitter, Submitter

cache = SQLiteCache("challenge-cache.db")
parser = CachedParser(TabularDocumentParser(), cache)
extractor = CachedExtractor(OpenAIExtractionBackend(), cache)
cache.set(cache_key("challenge", version=1), {"ready": True})
print(export_results([{"job_id": "j1", "status": "completed"}], "csv"))
receipt = await LocalSubmitter("results").submit("j1", {"answer": 42})
# No request occurs in dry-run mode:
receipt = await HTTPSubmitter("https://example.com/submit").submit("j1", {"answer": 42}, dry_run=True)
```

Exports support `json`, `jsonl`, `csv`, and `markdown`. Implement
`async submit(key, result, *, dry_run=False) -> str` to satisfy the `Submitter`
protocol. No registration or core modifications are required. HTTPSubmitter
accepts explicit `token`, `client`, `timeout`, `retries`, and
`response_validator`. Keys support remote idempotency if the receiver honors
them. Confirmed submission receipts can be persisted with JobStore.

## Asynchronous processing

```python
from hackathon_toolkit.models import ProcessingRequest
from hackathon_toolkit.processing import Job, JobProcessor, JobStore

async def solve(job):
    return {"answer": job.payload["number"] * 2}

store = JobStore("challenge-jobs.db")
processor = JobProcessor(solve, store, concurrency=2, policy="edf", timeout=30)
await processor.start()
try:
    await processor.recover()
    await processor.submit(Job(ProcessingRequest(job_id="challenge-1", document_id="input-1"),
                               payload={"number": 21}))
finally:
    await processor.stop()  # waits for submitted jobs
status, result = store.get("challenge-1")
print(status, result.data)
```

The worker is any async callable returning a dictionary. Payloads and results
must be JSON serializable; deadlines must be timezone aware. No FastAPI or
Typesense is involved. `ExtractionWorker(pipeline, schema, submitter=..., store=...)`
in `hackathon_toolkit.pipeline` adapts filename payloads to extraction plus
idempotent submission. A custom optimization solver can be wrapped in a worker
or workflow Step; no generic optimization problem/solver API is implemented.

## Complete challenge-specific pipeline (offline)

This standalone example works with the base installation, generates its own
input, validates a custom extraction schema, runs a dependency-ordered workflow,
selects a qualifying product, and writes a submission. The custom extractor is
deterministic for this CSV challenge; replace it with `OpenAIExtractionBackend`
for LLM extraction. Save as `challenge.py` in any project and run
`python challenge.py`. The test suite executes this exact block outside the repo.

<!-- complete-pipeline -->
```python
import asyncio
from pathlib import Path
from pydantic import BaseModel, Field

from hackathon_toolkit.ingestion import ingest_bytes
from hackathon_toolkit.models import ExtractionResult
from hackathon_toolkit.parsing import TabularDocumentParser
from hackathon_toolkit.pipeline import DocumentPipeline
from hackathon_toolkit.matching import Constraint, Specification, match_requirements
from hackathon_toolkit.output import LocalSubmitter
from hackathon_toolkit.workflows import Step, run_workflow

class Product(BaseModel):
    model: str
    memory_gb: int = Field(ge=0)

class Catalogue(BaseModel):
    products: list[Product]

class CatalogueExtractor:
    async def extract(self, source, schema, *, instructions="", timeout=120):
        products = []
        for section in source.sections:
            for table in section.tables:
                for row in table.rows:
                    products.append(dict(zip(table.columns, row)))
        validated = schema.model_validate({"products": products})
        return ExtractionResult(document_id=source.metadata.id, backend="challenge-csv",
                                data=validated.model_dump())

async def main():
    document = ingest_bytes(b"model,memory_gb\nAX,64\nBX,16\n", "catalogue.csv")
    pipeline = DocumentPipeline(parser=TabularDocumentParser(), extractor=CatalogueExtractor())
    submitter = LocalSubmitter("challenge-output")

    async def extract(state):
        result = await pipeline.extract(state["document"], Catalogue)
        return Catalogue.model_validate(result.data)

    async def select(state):
        requirement = Constraint(attribute="memory_gb", operator="gte", value=32)
        for product in state["catalogue"].products:
            report = match_requirements([requirement], {
                "memory_gb": Specification(value=product.memory_gb)
            })
            if report.overall.value == "PASS":
                return {"selected": product.model, "match": report.model_dump(mode="json")}
        return {"selected": None, "reason": "No qualifying product"}

    async def submit(state):
        return await submitter.submit("catalogue", state["selection"])

    result = await run_workflow([
        Step("catalogue", extract),
        Step("selection", select, depends_on=("catalogue",)),
        Step("receipt", submit, depends_on=("selection",)),
    ], initial={"document": document})
    print(result.state["selection"])
    print(Path(result.state["receipt"]).resolve())

if __name__ == "__main__":
    asyncio.run(main())
```

Steps accept a state dictionary and can specify `when`, `timeout`, and `retries`.
Ready steps run concurrently; dependent steps receive upstream results.
`WorkflowResult` contains `state` and per-step `timings`.

## Benchmarks, demos, and cost measurement

```python
from decimal import Decimal
from hackathon_toolkit.observability import estimate_cost_usd
from hackathon_toolkit.benchmarks import run_suite, render, synthetic_extraction_cases
from hackathon_toolkit.demos import match_sample_rfq

print(render(await run_suite(), "markdown"))  # offline scheduler simulation
cases = synthetic_extraction_cases(seed=42, count=5)
# Supply YOUR current per-million token rates; the numbers here are illustrative:
print(estimate_cost_usd(input_tokens=100, output_tokens=20,
                       input_per_million_usd=Decimal("1"), output_per_million_usd=Decimal("2")))
# With your own files in the sample format:
# report = match_sample_rfq("rfq.txt", "technical_spec.txt")
```

`compare_extraction_backends(backends, schema, cases)` is async and returns
accuracy/latency results; `render_extraction(results, format)` formats them.
`LabeledCase(text, truth)` accepts custom labeled data. Supplied real backends
perform real inference; simulation alone does not establish extraction accuracy.

## Optional interfaces

The CLI calls the same pipeline and component APIs. FastAPI is optional:

```python
from hackathon_toolkit.api import create_app
from hackathon_toolkit.config import Settings

app = create_app(settings=Settings(sqlite_path="api-jobs.db"), upload_dir="api-uploads")
```

This explicit factory creates persistence resources; its lifespan starts workers.
Serve with `uvicorn hackathon_toolkit.api:create_app --factory` or the compatible
lazy `uvicorn hackathon_toolkit.api:app` entry point. `api.app` is now an ASGI
callable, not an eagerly constructed FastAPI instance; use `create_app()` if you
need `.routes`, `.state`, or other FastAPI attributes. Custom API extraction can
be injected with `extractor=async_callable(document, request)`; the standard
HTTP schema names remain limited to built-ins. Python extraction accepts any
Pydantic schema. Library use needs neither interface.
