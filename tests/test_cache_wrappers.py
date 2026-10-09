import asyncio

import pytest
from pydantic import BaseModel

from hackathon_toolkit.cache import CachedExtractor, CachedParser, SQLiteCache
from hackathon_toolkit.ingestion import ingest_bytes
from hackathon_toolkit.models import ExtractionResult, ParsedDocument, Section, TextBlock
from hackathon_toolkit.parsing import ParseOptions


class FakeParser:
    def __init__(self):
        self.calls = 0

    async def parse(self, document, options):
        self.calls += 1
        await asyncio.sleep(.01)
        return ParsedDocument(metadata=document.metadata, sections=[Section(blocks=[TextBlock(text="model AX")])])


class SchemaA(BaseModel):
    name: str | None


class SchemaB(BaseModel):
    product_name: str | None


class FakeExtractor:
    model = "mock-v1"

    def __init__(self):
        self.calls = 0

    async def extract(self, source, schema, *, instructions, timeout):
        self.calls += 1
        return ExtractionResult(document_id=source.metadata.id, backend="fake",
                                data={name: "AX" for name in schema.model_fields})


@pytest.mark.asyncio
async def test_parse_cache_reuses_result_and_refreshes_file_metadata(tmp_path):
    parser = FakeParser()
    cache = CachedParser(parser, SQLiteCache(tmp_path / "cache.db"), version="one")
    one = ingest_bytes(b"same", "one.txt")
    two = ingest_bytes(b"same", "two.txt")
    results = await asyncio.gather(cache.parse(one, ParseOptions()), cache.parse(two, ParseOptions()))
    assert parser.calls == 1
    assert [result.metadata.filename for result in results] == ["one.txt", "two.txt"]
    await CachedParser(parser, cache.cache, version="two").parse(one, ParseOptions())
    assert parser.calls == 2


@pytest.mark.asyncio
async def test_extraction_cache_includes_schema_instructions_and_model(tmp_path):
    backend = FakeExtractor()
    cache = CachedExtractor(backend, SQLiteCache(tmp_path / "cache.db"))
    source = ingest_bytes(b"model AX", "spec.txt")
    await cache.extract(source, SchemaA)
    await cache.extract(source, SchemaA)
    assert backend.calls == 1
    await cache.extract(source, SchemaB)
    await cache.extract(source, SchemaA, instructions="Only exact identifiers")
    assert backend.calls == 3
    backend.model = "mock-v2"
    await cache.extract(source, SchemaA)
    assert backend.calls == 4
