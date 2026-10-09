from __future__ import annotations

import asyncio
import hashlib
import io
import time
from pathlib import Path
from typing import AsyncIterator, BinaryIO, Iterable

from .models import Document, DocumentMetadata

SUPPORTED = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".html", ".json", ".png", ".jpg", ".jpeg", ".eml"}


def ingest_stream(stream: BinaryIO, filename: str, *, max_mb: int = 40, source: str = "memory",
                  path: str | None = None) -> Document:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"unsupported file type: {suffix}")
    digest = hashlib.sha256()
    size = 0
    while part := stream.read(1024 * 1024):
        size += len(part)
        if size > max_mb * 1024 * 1024:
            raise ValueError("document exceeds configured size limit")
        digest.update(part)
    if size == 0:
        raise ValueError("empty document")
    hash_value = digest.hexdigest()
    return Document(metadata=DocumentMetadata(id=hash_value, filename=Path(filename).name, file_type=suffix[1:],
                                               size=size, sha256=hash_value, source=source), path=path)


def ingest_bytes(data: bytes, filename: str, **kwargs) -> Document:
    doc = ingest_stream(io.BytesIO(data), filename, **kwargs)
    doc.content = data
    return doc


def ingest_file(path: str | Path, *, max_mb: int = 40) -> Document:
    file = Path(path)
    if not file.is_file():
        raise ValueError("input must be a regular file")
    before = file.stat()
    with file.open("rb") as stream:
        document = ingest_stream(stream, file.name, max_mb=max_mb, source="file", path=str(file.resolve()))
    after = file.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("file changed during ingestion")
    return document


def ingest_many(paths: Iterable[str | Path], *, max_mb: int = 40) -> list[Document]:
    return [ingest_file(path, max_mb=max_mb) for path in paths]


def ingest_directory(directory: str | Path, *, recursive: bool = False, max_mb: int = 40) -> list[Document]:
    base = Path(directory)
    files = base.rglob("*") if recursive else base.iterdir()
    return ingest_many((p for p in files if p.is_file() and p.suffix.lower() in SUPPORTED), max_mb=max_mb)


async def watch_directory(directory: str | Path, *, poll_seconds: float = 1.0, stable_polls: int = 2,
                          min_age_seconds: float = 2.0, max_mb: int = 40) -> AsyncIterator[Document]:
    """Yield only files whose size and mtime stay unchanged for stable_polls scans."""
    seen: set[tuple[str, str]] = set()
    observations: dict[Path, tuple[int, int, int]] = {}
    while True:
        for path in Path(directory).iterdir():
            if not path.is_file() or path.suffix.lower() not in SUPPORTED:
                continue
            stat = path.stat()
            previous = observations.get(path)
            count = previous[2] + 1 if previous and previous[:2] == (stat.st_size, stat.st_mtime_ns) else 1
            observations[path] = (stat.st_size, stat.st_mtime_ns, count)
            if count < stable_polls or time.time() - stat.st_mtime < min_age_seconds:
                continue
            try:
                document = ingest_file(path, max_mb=max_mb)
            except (OSError, ValueError):
                continue
            key = (str(path), document.metadata.sha256)
            if key not in seen:
                seen.add(key)
                yield document
        await asyncio.sleep(poll_seconds)
