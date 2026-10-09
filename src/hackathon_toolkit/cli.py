from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .config import Settings
from .ingestion import ingest_file, ingest_directory, SUPPORTED
from .schemas import load_schema
from .pipeline import create_pipeline, create_search, ExtractionWorker


async def _run(args) -> None:
    settings = Settings.from_env()
    if args.command == "ingest":
        docs = ingest_directory(args.path) if Path(args.path).is_dir() else [ingest_file(args.path)]
        print(json.dumps([d.metadata.model_dump(mode="json") for d in docs], indent=2))
    elif args.command in {"parse", "extract", "process-batch", "index"}:
        from .cache import SQLiteCache
        if not Path(args.path).exists():
            raise FileNotFoundError(f"document path does not exist: {args.path}")
        cache = SQLiteCache(settings.sqlite_path) if settings.enable_cache else None
        paths = sorted(p for p in Path(args.path).glob("*") if p.is_file() and p.suffix.lower() in SUPPORTED) if Path(args.path).is_dir() else [Path(args.path)]
        if not paths:
            raise ValueError(f"no supported documents found in {args.path}")
        schema = load_schema(args.schema) if args.command in {"extract", "process-batch"} else None
        pipeline = create_pipeline(schema, settings=settings, parser_name=args.parser,
                                   backend_name=args.backend, parse_first=args.parse_first, cache=cache)
        search = create_search(settings=settings, cache=cache) if args.command == "index" else None
        output = []
        for path in paths:
            document = ingest_file(path, max_mb=settings.max_document_mb)
            if args.command == "parse":
                result = await pipeline.parse(document)
            elif args.command == "index":
                count = await pipeline.index(document, search, embedder=search.embedder,
                                            chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
                output.append({"document_id": document.metadata.id, "indexed_chunks": count})
                continue
            else:
                result = await pipeline.extract(document, schema)
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
        from .rag import ask
        from .cache import SQLiteCache
        search = create_search(settings=settings,
                               cache=SQLiteCache(settings.sqlite_path) if settings.enable_cache else None)
        result = await ask(args.query, search) if args.command == "ask" else await search.search(args.query, mode=args.mode)
        print(json.dumps(result.model_dump(mode="json") if hasattr(result, "model_dump") else
              [item.model_dump(mode="json") for item in result], indent=2))
    elif args.command in {"simulate", "benchmark"}:
        from .benchmarks import run_suite, render
        print(render(await run_suite(), args.format))
    elif args.command == "benchmark-backends":
        from .benchmarks import compare_extraction_backends, synthetic_extraction_cases, render_extraction
        from .schemas import TechnicalSpecification
        from .extraction import GLiNERExtractionBackend, OpenAIExtractionBackend
        backends = {"llm": OpenAIExtractionBackend(model=settings.extraction_model),
                    "gliner": GLiNERExtractionBackend(settings.local_model)}
        results = await compare_extraction_backends(backends, TechnicalSpecification,
                                                     synthetic_extraction_cases(seed=args.seed, count=args.count))
        print(render_extraction(results, args.format))
    elif args.command == "run-worker":
        from .cache import SQLiteCache
        from datetime import datetime, timedelta, timezone
        from .ingestion import watch_directory
        from .models import ProcessingRequest
        from .processing import Job, JobProcessor, JobStore
        from .output import LocalSubmitter
        schema = load_schema(args.schema)
        cache = SQLiteCache(settings.sqlite_path) if settings.enable_cache else None
        pipeline = create_pipeline(schema, settings=settings, parser_name=args.parser,
                                   backend_name=args.backend, parse_first=args.parse_first,
                                   cache=cache, limiter=asyncio.Semaphore(settings.max_llm_requests))
        store = JobStore(settings.sqlite_path)
        work = ExtractionWorker(pipeline, schema, submitter=LocalSubmitter(args.output), store=store)
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
