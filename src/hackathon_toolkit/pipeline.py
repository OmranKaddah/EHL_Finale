"""Reusable composition shared by Python callers, the CLI, and the HTTP API.

Factories use explicit Settings (never environment variables) and do not open
databases, start workers, load models, or make requests. Inject a cache to opt in.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import BaseModel

from .cache import CachedExtractor, CachedParser, SQLiteCache
from .config import Settings
from .extraction import ExtractionBackend
from .ingestion import ingest_file
from .models import Document, ExtractionResult, ParsedDocument, chunk_document
from .parsing import ParseOptions, Parser


class DocumentPipeline:
    """Compose independent parser/extractor implementations without a scheduler.

    ``extract`` accepts a Document, ParsedDocument, text, or Path. Strings are
    text; use Path or ingest_file for filenames. Set direct=True only when the
    extractor supports raw Documents. Injected clients remain caller-owned.
    """

    def __init__(self, *, parser: Parser | None = None,
                 extractor: ExtractionBackend | None = None,
                 parse_options: ParseOptions | None = None, direct: bool = False,
                 max_document_mb: int = 40, limiter: asyncio.Semaphore | None = None,
                 parser_uses_llm: bool = False, extractor_uses_llm: bool = False):
        self.parser, self.extractor = parser, extractor
        self.parse_options = parse_options or ParseOptions()
        self.direct, self.max_document_mb = direct, max_document_mb
        self.limiter = limiter
        self.parser_uses_llm, self.extractor_uses_llm = parser_uses_llm, extractor_uses_llm

    @asynccontextmanager
    async def _limit(self, enabled: bool):
        if enabled and self.limiter is not None:
            async with self.limiter:
                yield
        else:
            yield

    async def parse(self, document: Document | str | Path) -> ParsedDocument:
        """Ingest a filename if needed, then return normalized document content."""
        if self.parser is None:
            raise ValueError("a parser is required")
        if not isinstance(document, Document):
            document = ingest_file(document, max_mb=self.max_document_mb)
        async with self._limit(self.parser_uses_llm):
            return await self.parser.parse(document, self.parse_options)

    async def extract(self, source: Document | ParsedDocument | str | Path,
                      schema: type[BaseModel], *, instructions: str = "",
                      timeout: float = 120) -> ExtractionResult:
        """Extract into a caller-defined Pydantic schema; errors propagate."""
        if self.extractor is None:
            raise ValueError("an extractor is required")
        if isinstance(source, Path):
            source = ingest_file(source, max_mb=self.max_document_mb)
        if isinstance(source, Document) and not self.direct:
            source = await self.parse(source)
        async with self._limit(self.extractor_uses_llm):
            return await self.extractor.extract(source, schema, instructions=instructions, timeout=timeout)

    async def index(self, source: Document | ParsedDocument | str | Path, search,
                    *, embedder=None, chunk_size: int = 3000, chunk_overlap: int = 200) -> int:
        """Parse and upsert chunks; omit embedder for keyword-only indexing."""
        parsed = source if isinstance(source, ParsedDocument) else await self.parse(source)
        chunks = chunk_document(parsed, chunk_size, chunk_overlap)
        await search.ensure_collection()
        vectors = await embedder.embed([chunk.text for chunk in chunks]) if embedder is not None else None
        await search.index(chunks, vectors=vectors)
        return len(chunks)


def create_pipeline(schema: type[BaseModel] | None = None, *, settings: Settings | None = None,
                    parser_name: str | None = None, backend_name: str | None = None,
                    parse_first: bool = False, parser: Parser | None = None,
                    extractor: ExtractionBackend | None = None, client=None,
                    cache: SQLiteCache | None = None,
                    limiter: asyncio.Semaphore | None = None) -> DocumentPipeline:
    """Build the standard extraction path. Custom injected parsers run first.

    A schema enables backend construction and auto routing. No schema is needed
    for parsing/indexing or when an extractor is injected. A supplied OpenAI
    client is shared by the default parser and extractor.
    """
    from .extraction import GLiNERExtractionBackend, OpenAIExtractionBackend, choose_backend
    from .parsing import DoclingDocumentParser, LLMDocumentParser, PyMuPDFDocumentParser, TabularDocumentParser

    settings = settings or Settings()
    parser_name = parser_name or settings.document_parser
    backend_name = backend_name or settings.extraction_backend
    injected_parser = parser is not None
    injected_extractor = extractor is not None
    if parser is None:
        factories = {"llm": lambda: LLMDocumentParser(client=client),
                     "docling": DoclingDocumentParser, "pymupdf": PyMuPDFDocumentParser,
                     "tabular": lambda: TabularDocumentParser(settings.tabular_rows_per_table)}
        if parser_name not in factories:
            raise ValueError(f"unknown parser: {parser_name}")
        parser = factories[parser_name]()
    if extractor is None and schema is not None:
        backend_name = choose_backend(backend_name, parser_name, schema)
        extractor = (GLiNERExtractionBackend(settings.local_model) if backend_name == "gliner" else
                     OpenAIExtractionBackend(model=settings.extraction_model,
                                             pdf_detail=settings.pdf_detail, client=client))
    if cache is not None:
        parser = CachedParser(parser, cache, version="parser-v2")
        if extractor is not None:
            extractor = CachedExtractor(extractor, cache, version="extraction-v2")
    return DocumentPipeline(parser=parser, extractor=extractor,
        parse_options=ParseOptions(model=settings.parser_model, pdf_detail=settings.pdf_detail),
        direct=(parser_name == backend_name == "llm" and not parse_first
                and not injected_parser and not injected_extractor),
        max_document_mb=settings.max_document_mb, limiter=limiter,
        parser_uses_llm=parser_name == "llm", extractor_uses_llm=backend_name == "llm")


def create_search(*, settings: Settings | None = None, client=None, embedder=None,
                  embedding_client=None, cache: SQLiteCache | None = None):
    """Build Typesense retrieval with an injected or lazy embedding service."""
    from .embeddings import EmbeddingService
    from .search import TypesenseSearch

    settings = settings or Settings()
    if embedder is None:
        embedder = EmbeddingService(model=settings.embedding_model, dimensions=settings.embedding_dimensions,
                                    client=embedding_client, cache=cache)
    return TypesenseSearch(host=settings.typesense_host, port=settings.typesense_port,
        protocol=settings.typesense_protocol, api_key=settings.typesense_api_key,
        collection=settings.typesense_collection, dimensions=settings.embedding_dimensions,
        embedding_model=settings.embedding_model, client=client, embedder=embedder)


class ExtractionWorker:
    """JobProcessor callback for filename payloads and optional submission.

    Supply both a submitter and a JobStore to persist submission receipts.
    Custom async submitters need only implement the Submitter protocol.
    """

    def __init__(self, pipeline: DocumentPipeline, schema: type[BaseModel], *, submitter=None, store=None):
        if submitter is not None and store is None:
            raise ValueError("submission requires a store")
        self.pipeline, self.schema, self.submitter, self.store = pipeline, schema, submitter, store

    async def __call__(self, job) -> dict:
        result = await self.pipeline.extract(Path(job.payload), self.schema)
        data = result.model_dump(mode="json")
        if self.submitter is not None and self.store.begin_submission(job.request.job_id):
            receipt = await self.submitter.submit(job.request.job_id, data)
            self.store.finish_submission(job.request.job_id, receipt)
        return data


__all__ = ["DocumentPipeline", "create_pipeline", "create_search", "ExtractionWorker"]
