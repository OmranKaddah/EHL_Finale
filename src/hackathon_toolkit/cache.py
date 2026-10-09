from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .models import Document, ExtractionResult, ParsedDocument


def cache_key(kind: str, **parts: Any) -> str:
    raw = json.dumps({"kind": kind, **parts}, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class SQLiteCache:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def get(self, key: str) -> Any | None:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key: str, value: Any) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO cache(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value, default=str)))


def _backend_identity(backend: object) -> dict[str, str]:
    model = getattr(backend, "model_id", None) or getattr(backend, "model", None)
    return {"class": f"{type(backend).__module__}.{type(backend).__qualname__}",
            "model": model if isinstance(model, str) else "injected" if model is not None else "",
            "pdf_detail": str(getattr(backend, "pdf_detail", "")),
            "chunk_size": str(getattr(backend, "chunk_size", "")),
            "overlap": str(getattr(backend, "overlap", "")),
            "rows_per_table": str(getattr(backend, "rows_per_table", ""))}


class CachedParser:
    def __init__(self, parser, cache: SQLiteCache, *, version: str = "v1"):
        self.parser, self.cache, self.version = parser, cache, version
        self._locks: dict[str, asyncio.Lock] = {}

    async def parse(self, document: Document, options=None) -> ParsedDocument:
        config = options.model_dump(mode="json") if options is not None else {}
        key = cache_key("parsed-document", content_hash=document.metadata.sha256,
                        backend=_backend_identity(self.parser), options=config, version=self.version)
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                cached = self.cache.get(key)
                if cached is None:
                    parsed = await self.parser.parse(document, options)
                    self.cache.set(key, parsed.model_dump(mode="json"))
                    return parsed
                parsed = ParsedDocument.model_validate(cached)
                parsed.metadata = document.metadata
                return parsed
        finally:
            self._locks.pop(key, None)


def _source_fingerprint(source: Document | ParsedDocument | str) -> dict[str, Any]:
    if isinstance(source, Document):
        return {"kind": "document", "hash": source.metadata.sha256}
    if isinstance(source, ParsedDocument):
        return {"kind": "parsed", "hash": source.metadata.sha256, "title": source.title,
                "sections": [section.model_dump(mode="json") for section in source.sections],
                "values": source.values}
    return {"kind": "text", "hash": hashlib.sha256(source.encode()).hexdigest()}


class CachedExtractor:
    def __init__(self, extractor, cache: SQLiteCache, *, version: str = "v1"):
        self.extractor, self.cache, self.version = extractor, cache, version
        self._locks: dict[str, asyncio.Lock] = {}

    async def extract(self, source: Document | ParsedDocument | str, schema: type[BaseModel],
                      *, instructions: str = "", timeout: float = 120) -> ExtractionResult:
        key = cache_key("extraction", source=_source_fingerprint(source),
                        schema=schema.model_json_schema(), instructions=instructions,
                        backend=_backend_identity(self.extractor), version=self.version)
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                cached = self.cache.get(key)
                if cached is None:
                    result = await self.extractor.extract(source, schema, instructions=instructions, timeout=timeout)
                    self.cache.set(key, result.model_dump(mode="json"))
                    return result
                return ExtractionResult.model_validate(cached)
        finally:
            self._locks.pop(key, None)
