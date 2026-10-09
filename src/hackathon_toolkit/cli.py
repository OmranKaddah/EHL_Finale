from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .config import Settings
from .ingestion import ingest_file, ingest_directory, SUPPORTED
from .models import chunk_document
from .schemas import load_schema


async def _run(args) -> None:
    from .parsing import DoclingDocumentParser, LLMDocumentParser, PyMuPDFDocumentParser, TabularDocumentParser, ParseOptions
    from .extraction import GLiNERExtractionBackend, OpenAIExtractionBackend, choose_backend
    settings = Settings.from_env()
    if args.command == "ingest":
        docs = ingest_directory(args.path) if Path(args.path).is_dir() else [ingest_file(args.path)]
        print(json.dumps([d.metadata.model_dump(mode="json") for d in docs], indent=2))
    elif args.command in {"parse", "extract", "process-batch", "index"}:
        from .cache import CachedExtractor, CachedParser, SQLiteCache
        if not Path(args.path).exists():
            raise FileNotFoundError(f"document path does not exist: {args.path}")
        cache = SQLiteCache(settings.sqlite_path) if settings.enable_cache else None
        paths = sorted(p for p in Path(args.path).glob("*") if p.is_file() and p.suffix.lower() in SUPPORTED) if Path(args.path).is_dir() else [Path(args.path)]
        if not paths:
            raise ValueError(f"no supported documents found in {args.path}")
        parser_name = getattr(args, "parser", None) or settings.document_parser
        parser = (DoclingDocumentParser() if parser_name == "docling" else
                  PyMuPDFDocumentParser() if parser_name == "pymupdf" else
                  TabularDocumentParser(settings.tabular_rows_per_table) if parser_name == "tabular" else
                  LLMDocumentParser())
        if cache is not None:
            parser = CachedParser(parser, cache, version="parser-v2")
        schema = load_schema(args.schema) if args.command in {"extract", "process-batch"} else None
        backend_name = getattr(args, "backend", None) or settings.extraction_backend
        if schema is not None:
            backend_name = choose_backend(backend_name, parser_name, schema)
        backend = ((GLiNERExtractionBackend(settings.local_model) if backend_name == "gliner"
                   else OpenAIExtractionBackend(model=settings.extraction_model, pdf_detail=settings.pdf_detail))
                   if schema is not None else None)
        if cache is not None and backend is not None:
            backend = CachedExtractor(backend, cache, version="extraction-v2")
        output = []
        for path in paths:
            if not path.is_file():
                raise ValueError(f"document path is not a file: {path}")
            document = ingest_file(path, max_mb=settings.max_document_mb)
            if args.command in {"extract", "process-batch"} and parser_name == "llm" and backend_name == "llm" and not args.parse_first:
                result = await backend.extract(document, schema)
                output.append(result.model_dump(mode="json"))
                continue
            parsed = await parser.parse(document, ParseOptions(model=settings.parser_model, pdf_detail=settings.pdf_detail))
            if args.command == "parse": output.append(parsed.model_dump(mode="json")); continue
            if args.command == "index":
                from .embeddings import EmbeddingService
                from .search import TypesenseSearch
                embedder = EmbeddingService(model=settings.embedding_model, dimensions=settings.embedding_dimensions,
                                            cache=cache)
                search = TypesenseSearch(host=settings.typesense_host, port=settings.typesense_port,
                    protocol=settings.typesense_protocol, api_key=settings.typesense_api_key,
                    collection=settings.typesense_collection, dimensions=settings.embedding_dimensions,
                    embedding_model=settings.embedding_model, embedder=embedder)
                await search.ensure_collection()
                chunks = chunk_document(parsed, settings.chunk_size, settings.chunk_overlap)
                await search.index(chunks, vectors=await embedder.embed([c.text for c in chunks]))
                output.append({"document_id": document.metadata.id, "indexed_chunks": len(chunks)})
                continue
            result = await backend.extract(parsed, schema)
            output.append(result.model_dump(mode="json"))
        print(json.dumps(output[0] if len(output) == 1 else output, indent=2))
    elif args.command == "match":
        from .matching import Constraint, Specification, match_requirements
        payload = json.loads(Path(args.path).read_text())
        constraints = [Constraint.model_validate(item) for item in payload["requirements"]]
        specifications = {key: Specification.model_validate(value) for key, value in payload["specifications"].items()}
        print(match_requirements(constraints, specifications).model_dump_json(indent=2))
    elif args.command == "demo-rfq":
        from .demos import match_sample_rfq
        print(json.dumps(match_sample_rfq(args.rfq, args.specification), indent=2))
    elif args.command in {"search", "ask"}:
        from .embeddings import EmbeddingService
        from .search import TypesenseSearch
        from .rag import ask
        from .cache import SQLiteCache
        embedder = EmbeddingService(model=settings.embedding_model, dimensions=settings.embedding_dimensions,
                                    cache=SQLiteCache(settings.sqlite_path) if settings.enable_cache else None)
        search = TypesenseSearch(host=settings.typesense_host, port=settings.typesense_port,
            protocol=settings.typesense_protocol, api_key=settings.typesense_api_key,
            collection=settings.typesense_collection, dimensions=settings.embedding_dimensions,
            embedding_model=settings.embedding_model, embedder=embedder)
        result = await ask(args.query, search) if args.command == "ask" else await search.search(args.query, mode=args.mode)
        print(json.dumps(result.model_dump(mode="json") if hasattr(result, "model_dump") else
              [item.model_dump(mode="json") for item in result], indent=2))
    elif args.command in {"simulate", "benchmark"}:
        from .benchmarks import run_suite, render
        print(render(await run_suite(), args.format))
    elif args.command == "benchmark-backends":
        from .benchmarks import compare_extraction_backends, synthetic_extraction_cases, render_extraction
        from .schemas import TechnicalSpecification
        backends = {"llm": OpenAIExtractionBackend(model=settings.extraction_model),
                    "gliner": GLiNERExtractionBackend(settings.local_model)}
        results = await compare_extraction_backends(backends, TechnicalSpecification,
                                                     synthetic_extraction_cases(seed=args.seed, count=args.count))
        print(render_extraction(results, args.format))
    elif args.command == "run-worker":
        from .cache import CachedExtractor, CachedParser, SQLiteCache
        from datetime import datetime, timedelta, timezone
        from .ingestion import watch_directory
        from .models import ProcessingRequest
        from .processing import Job, JobProcessor, JobStore
        from .output import LocalSubmitter
        schema = load_schema(args.schema)
        backend_name = choose_backend(args.backend, args.parser, schema)
        parser = (DoclingDocumentParser() if args.parser == "docling" else
                  TabularDocumentParser(settings.tabular_rows_per_table) if args.parser == "tabular" else
                  LLMDocumentParser())
        backend = (GLiNERExtractionBackend(settings.local_model) if backend_name == "gliner"
                   else OpenAIExtractionBackend(model=settings.extraction_model, pdf_detail=settings.pdf_detail))
        if settings.enable_cache:
            cache = SQLiteCache(settings.sqlite_path)
            parser = CachedParser(parser, cache, version="parser-v2")
            backend = CachedExtractor(backend, cache, version="extraction-v2")
        limiter = asyncio.Semaphore(settings.max_llm_requests)
        submitter = LocalSubmitter(args.output)
        async def work(job: Job) -> dict:
            document = ingest_file(job.payload, max_mb=settings.max_document_mb)
            if args.parser == "llm" and backend_name == "llm" and not args.parse_first:
                async with limiter:
                    result = await backend.extract(document, schema)
            else:
                if args.parser == "llm":
                    async with limiter:
                        parsed = await parser.parse(document, ParseOptions(model=settings.parser_model, pdf_detail=settings.pdf_detail))
                else:
                    parsed = await parser.parse(document, ParseOptions(model=settings.parser_model, pdf_detail=settings.pdf_detail))
                if backend_name == "llm":
                    async with limiter: result = await backend.extract(parsed, schema)
                else:
                    result = await backend.extract(parsed, schema)
            data = result.model_dump(mode="json")
            if store.begin_submission(job.request.job_id):
                receipt = await submitter.submit(job.request.job_id, data)
                store.finish_submission(job.request.job_id, receipt)
            return data
        store = JobStore(settings.sqlite_path)
        processor = JobProcessor(work, store, concurrency=settings.max_workers,
                                 timeout=settings.job_timeout_seconds,
                                 policy="edf" if settings.scheduling_policy == "earliest_deadline_first" else settings.scheduling_policy)
        await processor.start()
        recovered = await processor.recover()
        print(f"worker ready; recovered {recovered} jobs; watching {args.path}", flush=True)
        try:
            async for document in watch_directory(args.path, max_mb=settings.max_document_mb):
                deadline = datetime.now(timezone.utc) + timedelta(seconds=settings.window_seconds)
                await processor.submit(Job(ProcessingRequest(job_id=document.metadata.id,
                    document_id=document.metadata.id, deadline=deadline), payload=document.path))
        finally:
            await processor.stop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="hackkit")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("ingest", "parse", "extract", "process-batch", "index", "match"):
        command = sub.add_parser(name)
        command.add_argument("path")
        if name in {"parse", "extract", "process-batch", "index"}:
            command.add_argument("--parser", choices=["llm", "docling", "pymupdf", "tabular"])
            command.add_argument("--schema", default="general")
            command.add_argument("--backend", choices=["llm", "gliner", "auto"])
            command.add_argument("--parse-first", action="store_true")
    for name in ("search", "ask"):
        command = sub.add_parser(name)
        command.add_argument("query")
        command.add_argument("--mode", choices=["keyword", "vector", "hybrid"], default="hybrid")
    demo = sub.add_parser("demo-rfq")
    demo.add_argument("rfq")
    demo.add_argument("specification")
    for name in ("simulate", "benchmark"):
        sub.add_parser(name).add_argument("--format", choices=["json", "csv", "markdown"], default="markdown")
    comparison = sub.add_parser("benchmark-backends")
    comparison.add_argument("--count", type=int, default=20)
    comparison.add_argument("--seed", type=int, default=42)
    comparison.add_argument("--format", choices=["json", "csv", "markdown"], default="markdown")
    worker = sub.add_parser("run-worker")
    worker.add_argument("path", help="directory to watch")
    worker.add_argument("--schema", default="general")
    worker.add_argument("--parser", choices=["llm", "docling", "tabular"], default="llm")
    worker.add_argument("--backend", choices=["llm", "gliner", "auto"], default="llm")
    worker.add_argument("--parse-first", action="store_true")
    worker.add_argument("--output", default="results")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__": main()
