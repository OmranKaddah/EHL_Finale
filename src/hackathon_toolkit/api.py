from __future__ import annotations

import asyncio
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .config import Settings
from .ingestion import SUPPORTED, ingest_file
from .matching import Constraint, Specification, match_requirements
from .models import Document, ProcessingRequest
from .processing import Job, JobProcessor, JobStore
from .schemas import BUILTIN_SCHEMAS
from .pipeline import create_pipeline, create_search


class MatchRequest(BaseModel):
    requirements: list[Constraint]
    specifications: dict[str, Specification]


class ExtractRequest(BaseModel):
    document_id: str
    schema_name: str = "general"
    parser: Literal["llm", "docling", "pymupdf", "tabular"] = "llm"
    backend: Literal["llm", "gliner", "auto"] = "llm"
    parse_first: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    filters: dict[str, str] | None = None
    top_k: int = Field(default=5, ge=1, le=100)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    filters: dict[str, str] | None = None
    top_k: int = Field(default=5, ge=1, le=20)


def _search_engine(settings: Settings):
    from .cache import SQLiteCache
    return create_search(settings=settings,
                         cache=SQLiteCache(settings.sqlite_path) if settings.enable_cache else None)


def create_app(*, settings: Settings | None = None, upload_dir: str | Path = ".hackkit_uploads",
               extractor: Callable[[Document, ExtractRequest], Any] | None = None,
               search=None) -> FastAPI:
    settings = settings or Settings.from_env()
    directory = Path(upload_dir)
    directory.mkdir(parents=True, exist_ok=True)
    documents: dict[str, Document] = {}
    for sidecar in directory.glob("*.json"):
        try:
            doc = Document.model_validate_json(sidecar.read_text())
            if doc.path and Path(doc.path).is_file(): documents[doc.metadata.id] = doc
        except (ValueError, OSError):
            continue
    store = JobStore(settings.sqlite_path)
    processor: JobProcessor | None = None
    llm_limiter = asyncio.Semaphore(settings.max_llm_requests)
    if settings.enable_cache:
        from .cache import SQLiteCache
        cache = SQLiteCache(settings.sqlite_path)
    else:
        cache = None

    async def extract_document(document: Document, request: ExtractRequest) -> dict:
        if extractor is not None:
            result = await extractor(document, request)
            return result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        schema = BUILTIN_SCHEMAS[request.schema_name]
        pipeline = create_pipeline(schema, settings=settings, parser_name=request.parser,
                                   backend_name=request.backend, parse_first=request.parse_first,
                                   cache=cache, limiter=llm_limiter)
        return (await pipeline.extract(document, schema)).model_dump(mode="json")

    async def job_worker(job: Job) -> dict:
        payload = ExtractRequest.model_validate(job.payload)
        doc = documents.get(payload.document_id)
        if doc is None: raise ValueError("document missing after recovery")
        return await extract_document(doc, payload)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal processor
        processor = JobProcessor(job_worker, store, concurrency=settings.max_workers,
                                 timeout=settings.job_timeout_seconds,
                                 policy="edf" if settings.scheduling_policy == "earliest_deadline_first" else settings.scheduling_policy)
        await processor.start()
        await processor.recover()
        try:
            yield
        finally:
            await processor.stop()

    app = FastAPI(title="Hackathon Toolkit", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/documents")
    async def upload(request: Request, filename: str = Query(min_length=1, max_length=255)):
        if Path(filename).name != filename or Path(filename).suffix.lower() not in SUPPORTED:
            raise HTTPException(400, "unsupported or unsafe filename")
        limit, size = settings.max_document_mb * 1024 * 1024, 0
        with tempfile.NamedTemporaryFile(dir=directory, suffix=Path(filename).suffix, delete=False) as temp:
            temp_path = Path(temp.name)
            try:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit: raise HTTPException(413, "document exceeds upload limit")
                    temp.write(chunk)
            except BaseException:
                temp_path.unlink(missing_ok=True)
                raise
        try:
            doc = ingest_file(temp_path, max_mb=settings.max_document_mb)
            final_path = directory / f"{doc.metadata.id}{Path(filename).suffix.lower()}"
            temp_path.replace(final_path)
            doc.metadata.filename, doc.path = filename, str(final_path.resolve())
            (directory / f"{doc.metadata.id}.json").write_text(doc.model_dump_json())
            documents[doc.metadata.id] = doc
            return doc.metadata
        except (OSError, ValueError) as exc:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(400, str(exc)) from exc

    @app.post("/extract")
    async def extract(request: ExtractRequest):
        if request.schema_name not in BUILTIN_SCHEMAS: raise HTTPException(400, "unknown schema")
        doc = documents.get(request.document_id)
        if doc is None: raise HTTPException(404, "document not found")
        try: return await extract_document(doc, request)
        except Exception as exc: raise HTTPException(502, f"extraction failed: {exc}") from exc

    @app.post("/match")
    async def match(request: MatchRequest):
        return match_requirements(request.requirements, request.specifications)

    @app.post("/search")
    async def search_endpoint(request: SearchRequest):
        engine = search or _search_engine(settings)
        return await engine.search(request.query, mode=request.mode,
                                   filters=request.filters, top_k=request.top_k)

    @app.post("/ask")
    async def ask_endpoint(request: AskRequest):
        from .rag import ask
        engine = search or _search_engine(settings)
        return await ask(request.question, engine, top_k=request.top_k, filters=request.filters)

    @app.post("/jobs")
    async def create_job(request: ExtractRequest):
        if request.schema_name not in BUILTIN_SCHEMAS: raise HTTPException(400, "unknown schema")
        if request.document_id not in documents: raise HTTPException(404, "document not found")
        job_id = uuid.uuid4().hex
        deadline = datetime.now(timezone.utc) + timedelta(seconds=settings.window_seconds)
        job = Job(ProcessingRequest(job_id=job_id, document_id=request.document_id, deadline=deadline),
                  payload=request.model_dump())
        assert processor is not None
        await processor.submit(job)
        return {"job_id": job_id, "status": "queued"}

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str):
        result = store.get(job_id)
        if result is None: raise HTTPException(404, "job not found")
        return {"job_id": job_id, "status": result[0], "result": result[1]}

    @app.get("/jobs/{job_id}/results")
    async def get_job_result(job_id: str):
        result = store.get(job_id)
        if result is None: raise HTTPException(404, "job not found")
        if result[1] is None: raise HTTPException(202, "job still processing")
        return result[1]

    return app


_default_app: FastAPI | None = None


async def app(scope, receive, send):
    """Lazy ASGI compatibility entry point; prefer create_app with --factory.

    Merely importing this module does not read settings or create application
    resources. The ASGI server initializes the default app on its first call.
    """
    global _default_app
    if _default_app is None:
        _default_app = create_app()
    await _default_app(scope, receive, send)
