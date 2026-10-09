from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    parser_model: str = "gpt-4o-mini"
    extraction_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    local_model: str = "fastino/gliner2.5-multi-v1"
    document_parser: str = "llm"
    extraction_backend: str = "llm"
    pdf_detail: str = "auto"
    max_document_mb: int = 40
    chunk_size: int = 3000
    chunk_overlap: int = 200
    tabular_rows_per_table: int = 500
    max_workers: int = 4
    max_llm_requests: int = 4
    job_timeout_seconds: float = 150
    window_seconds: float = 180
    sqlite_path: str = "hackkit.db"
    typesense_host: str = "localhost"
    typesense_port: int = 8108
    typesense_protocol: str = "http"
    typesense_api_key: str = ""
    typesense_collection: str = "document_chunks_v1"
    enable_embeddings: bool = False
    enable_typesense: bool = False
    enable_cache: bool = True
    dry_run: bool = True
    processing_mode: str = "balanced"
    scheduling_policy: str = "earliest_deadline_first"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Settings:
        def get(name: str, default: object, convert=str):
            return convert(os.environ.get(name, str(default)))
        def boolean(value: str) -> bool:
            if value.lower() not in {"true", "false", "1", "0", "yes", "no"}:
                raise ValueError(f"invalid boolean: {value}")
            return value.lower() in {"true", "1", "yes"}
        value = cls(
            parser_model=get("OPENAI_PARSER_MODEL", cls.parser_model),
            extraction_model=get("OPENAI_EXTRACTION_MODEL", cls.extraction_model),
            embedding_model=get("OPENAI_EMBEDDING_MODEL", cls.embedding_model),
            embedding_dimensions=get("EMBEDDING_DIMENSIONS", cls.embedding_dimensions, int),
            local_model=get("LOCAL_EXTRACTION_MODEL", cls.local_model),
            document_parser=get("DOCUMENT_PARSER", cls.document_parser),
            extraction_backend=get("EXTRACTION_BACKEND", cls.extraction_backend),
            pdf_detail=get("LLM_PDF_DETAIL", cls.pdf_detail),
            max_document_mb=get("MAX_DOCUMENT_SIZE_MB", cls.max_document_mb, int),
            chunk_size=get("CHUNK_SIZE", cls.chunk_size, int),
            chunk_overlap=get("CHUNK_OVERLAP", cls.chunk_overlap, int),
            tabular_rows_per_table=get("TABULAR_ROWS_PER_TABLE", cls.tabular_rows_per_table, int),
            max_workers=get("MAX_CONCURRENT_WORKERS", cls.max_workers, int),
            max_llm_requests=get("MAX_CONCURRENT_LLM_REQUESTS", cls.max_llm_requests, int),
            job_timeout_seconds=get("JOB_TIMEOUT_SECONDS", cls.job_timeout_seconds, float),
            window_seconds=get("WINDOW_DURATION_SECONDS", cls.window_seconds, float),
            sqlite_path=get("SQLITE_PATH", cls.sqlite_path),
            typesense_host=get("TYPESENSE_HOST", cls.typesense_host),
            typesense_port=get("TYPESENSE_PORT", cls.typesense_port, int),
            typesense_protocol=get("TYPESENSE_PROTOCOL", cls.typesense_protocol),
            typesense_api_key=get("TYPESENSE_API_KEY", cls.typesense_api_key),
            typesense_collection=get("TYPESENSE_COLLECTION", cls.typesense_collection),
            enable_embeddings=get("ENABLE_EMBEDDINGS", cls.enable_embeddings, boolean),
            enable_typesense=get("ENABLE_TYPESENSE", cls.enable_typesense, boolean),
            enable_cache=get("ENABLE_CACHE", cls.enable_cache, boolean),
            dry_run=get("DRY_RUN", cls.dry_run, boolean),
            processing_mode=get("PROCESSING_MODE", cls.processing_mode),
            scheduling_policy=get("SCHEDULING_POLICY", cls.scheduling_policy),
            log_level=get("LOG_LEVEL", cls.log_level),
        )
        if value.chunk_size <= 0 or not 0 <= value.chunk_overlap < value.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than positive CHUNK_SIZE")
        if value.pdf_detail not in {"auto", "low", "high"}:
            raise ValueError("LLM_PDF_DETAIL must be auto, low, or high")
        if value.document_parser not in {"llm", "docling", "pymupdf", "tabular"}:
            raise ValueError("DOCUMENT_PARSER must be llm, docling, pymupdf, or tabular")
        if value.extraction_backend not in {"llm", "gliner", "auto"}:
            raise ValueError("EXTRACTION_BACKEND must be llm, gliner, or auto")
        if value.processing_mode not in {"fast", "balanced", "accurate"}:
            raise ValueError("PROCESSING_MODE must be fast, balanced, or accurate")
        if value.scheduling_policy not in {"fifo", "priority", "earliest_deadline_first"}:
            raise ValueError("invalid SCHEDULING_POLICY")
        if min(value.max_document_mb, value.embedding_dimensions, value.max_workers,
               value.tabular_rows_per_table,
               value.max_llm_requests, value.typesense_port) <= 0:
            raise ValueError("size, dimensions, worker count, and port must be positive")
        return value
