from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceReference(BaseModel):
    document_id: str
    page: int | None = None
    section: str | None = None
    table: str | None = None
    row: int | None = None
    excerpt: str | None = None
    char_start: int | None = None
    char_end: int | None = None


class DocumentMetadata(BaseModel):
    id: str
    filename: str
    file_type: str
    size: int
    sha256: str
    ingested_at: datetime = Field(default_factory=utcnow)
    source: str = "file"
    status: str = "ingested"


class Document(BaseModel):
    metadata: DocumentMetadata
    path: str | None = None
    content: bytes | None = Field(default=None, exclude=True)


class TextBlock(BaseModel):
    text: str
    source: SourceReference | None = None


class Table(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    source: SourceReference | None = None


class Section(BaseModel):
    heading: str | None = None
    blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    source: SourceReference | None = None


class ParsedDocument(BaseModel):
    metadata: DocumentMetadata
    title: str | None = None
    sections: list[Section] = Field(default_factory=list)
    values: dict[str, str | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    def text_with_sources(self) -> tuple[str, list[tuple[int, int, SourceReference]]]:
        parts: list[str] = []
        spans: list[tuple[int, int, SourceReference]] = []
        length = 0

        def append(value: str, reference: SourceReference | None) -> None:
            nonlocal length
            if not value:
                return
            if parts:
                parts.append("\n")
                length += 1
            start = length
            parts.append(value)
            length += len(value)
            if reference is not None:
                spans.append((start, length, reference))

        for section in self.sections:
            fallback = SourceReference(document_id=self.metadata.id, section=section.heading)
            if section.heading:
                append(section.heading, section.source or fallback)
            for block in section.blocks:
                append(block.text, block.source or fallback)
            for table in section.tables:
                table_ref = table.source or fallback
                match = re.search(r"!rows-(\d+)-\d+$", table_ref.table or "")
                first_row = int(match.group(1)) if match else 1
                if table.columns:
                    append(" | ".join(table.columns), table_ref.model_copy(update={"row": 1 if match else 0}))
                for row_number, row in enumerate(table.rows, 1):
                    append(" | ".join(row), table_ref.model_copy(update={"row": first_row + row_number - 1}))
        return "".join(parts), spans

    def text(self) -> str:
        return self.text_with_sources()[0]


class DocumentChunk(BaseModel):
    id: str
    document_id: str
    text: str
    title: str | None = None
    filename: str
    document_type: str
    section: str | None = None
    page: int | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    document_id: str
    backend: str
    data: dict[str, Any]
    evidence: dict[str, SourceReference] = Field(default_factory=dict)
    model_scores: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class ProcessingRequest(BaseModel):
    job_id: str
    document_id: str
    priority: int = 0
    deadline: datetime | None = None
    mode: Literal["fast", "balanced", "accurate"] = "balanced"

    @field_validator("deadline")
    @classmethod
    def deadline_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("deadline must include a timezone")
        return value


class ProcessingResult(BaseModel):
    job_id: str
    document_id: str
    status: Literal["completed", "failed", "timed_out", "review"]
    data: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float = 0
    timings: dict[str, float] = Field(default_factory=dict)


def chunk_document(parsed: ParsedDocument, size: int = 3000, overlap: int = 200) -> list[DocumentChunk]:
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("invalid chunk size or overlap")
    chunks: list[DocumentChunk] = []
    for section_no, section in enumerate(parsed.sections):
        text = "\n".join(([section.heading] if section.heading else []) + [b.text for b in section.blocks] +
                         [" | ".join(row) for t in section.tables for row in [t.columns, *t.rows]])
        for start in range(0, len(text), size - overlap):
            part = text[start:start + size]
            if not part:
                break
            chunks.append(DocumentChunk(id=f"{parsed.metadata.id}-{section_no}-{start}", document_id=parsed.metadata.id,
                                        text=part, title=parsed.title, filename=parsed.metadata.filename,
                                        document_type=parsed.metadata.file_type, section=section.heading,
                                        page=section.source.page if section.source else None))
            if start + size >= len(text):
                break
    return chunks
