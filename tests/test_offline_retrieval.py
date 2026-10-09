import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from hackathon_toolkit.cache import SQLiteCache
from hackathon_toolkit.embeddings import EmbeddingService
from hackathon_toolkit.extraction import GLiNERExtractionBackend
from hackathon_toolkit.ingestion import ingest_bytes
from hackathon_toolkit.models import ParsedDocument, Section, TextBlock
from hackathon_toolkit.parsing import DoclingDocumentParser
from hackathon_toolkit.search import TypesenseSearch


class LocalSchema(BaseModel):
    manufacturer: str | None
    supported_standards: list[str]


class FakeConverter:
    def convert(self, path):
        return SimpleNamespace(document=SimpleNamespace(export_to_markdown=lambda: "# Spec\nAcme supports ISO 9001"))


class FakeFrame:
    columns = ["Parameter", "Value"]

    def itertuples(self, *, index, name):
        assert index is False and name is None
        return iter([("RAM", "64 GB"), ("Power", "250 W")])


class OrderedDoclingDocument:
    def iterate_items(self):
        def item(label, text=None, page=None, self_ref=None):
            return SimpleNamespace(label=SimpleNamespace(name=label), text=text,
                prov=[SimpleNamespace(page_no=page)] if page else [], self_ref=self_ref)
        title = item("TITLE", "Hardware Specification", 1)
        heading = item("SECTION_HEADER", "Electrical", 2)
        table = item("TABLE", page=2, self_ref="#/tables/0")
        table.export_to_dataframe = lambda *, doc: FakeFrame()
        return iter([(title, 0), (item("TEXT", "Overview", 1), 1),
                     (heading, 0), (table, 1), (item("PICTURE", page=2), 1)])


class FakeGLiNER:
    def extract_entities(self, text, labels, **kwargs):
        return {"entities": {"manufacturer": [{"text": "Acme", "start": 7, "end": 11}],
                             "supported standards": [{"text": "ISO 9001", "start": 21, "end": 29}]}}


@pytest.mark.asyncio
async def test_docling_gliner_pipeline_with_injected_models(tmp_path):
    path = tmp_path / "spec.md"
    path.write_text("# Spec\nAcme supports ISO 9001")
    from hackathon_toolkit.ingestion import ingest_file
    doc = ingest_file(path)
    parsed = await DoclingDocumentParser(converter=FakeConverter()).parse(doc)
    extracted = await GLiNERExtractionBackend(model=FakeGLiNER()).extract(parsed, LocalSchema)
    assert extracted.data == {"manufacturer": "Acme", "supported_standards": ["ISO 9001"]}
    assert extracted.evidence["manufacturer"].excerpt == "Acme"


@pytest.mark.asyncio
async def test_docling_preserves_ordered_sections_table_and_pages(tmp_path):
    path = tmp_path / "spec.md"
    path.write_text("# Hardware Specification")
    from hackathon_toolkit.ingestion import ingest_file
    converter = SimpleNamespace(convert=lambda path: SimpleNamespace(document=OrderedDoclingDocument()))
    parsed = await DoclingDocumentParser(converter=converter).parse(ingest_file(path))
    assert parsed.title == "Hardware Specification"
    assert [section.heading for section in parsed.sections] == ["Hardware Specification", "Electrical"]
    assert parsed.sections[0].blocks[0].source.page == 1
    table = parsed.sections[1].tables[0]
    assert table.rows == [["RAM", "64 GB"], ["Power", "250 W"]]
    assert table.source.page == 2
    assert table.source.table == "#/tables/0"
    assert parsed.warnings == ["Image or chart content requires visual interpretation; local text extraction omitted it."]

    class MemorySchema(BaseModel):
        memory: str | None

    class MemoryModel:
        def extract_entities(self, text, labels, **kwargs):
            start = text.index("64 GB")
            return {"entities": {"memory": [{"text": "64 GB", "start": start, "end": start + 5}]}}

    extracted = await GLiNERExtractionBackend(model=MemoryModel()).extract(parsed, MemorySchema)
    evidence = extracted.evidence["memory"]
    assert (evidence.page, evidence.section, evidence.table, evidence.row) == (
        2, "Electrical", "#/tables/0", 1)


@pytest.mark.asyncio
async def test_gliner_record_extraction_validates_grouped_records():
    class Product(BaseModel):
        model_code: str | None
        memory_gb: int | None
        standards: list[str]

    text = "AX-64 has 64 GB and ISO 9001. BX-32 has 32 GB and IEC 62368."

    class FakeRecordModel:
        def extract_json(self, chunk, schema, **kwargs):
            assert schema == {"product": ["model_code::str", "memory_gb::str", "standards::list"]}
            assert kwargs == {"include_confidence": True, "include_spans": True}
            def field(value):
                start = chunk.index(value)
                return {"text": value, "start": start, "end": start + len(value), "confidence": .9}
            return {"product": [
                {"model_code": field("AX-64"), "memory_gb": field("64"), "standards": [field("ISO 9001")]},
                {"model_code": field("BX-32"), "memory_gb": field("32"), "standards": [field("IEC 62368")]},
            ]}

    backend = GLiNERExtractionBackend(model=FakeRecordModel())
    result = await backend.extract_records(text, Product, "product")
    assert result.data["product"] == [
        {"model_code": "AX-64", "memory_gb": 64, "standards": ["ISO 9001"]},
        {"model_code": "BX-32", "memory_gb": 32, "standards": ["IEC 62368"]},
    ]
    assert result.evidence["product[1].model_code"].char_start == text.index("BX-32")
    assert result.model_scores["product[0].model_code"] == .9


@pytest.mark.asyncio
async def test_embedding_cache_avoids_repeat_requests(tmp_path):
    class FakeEmbeddings:
        calls = 0
        async def create(self, **kwargs):
            self.calls += 1
            return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[float(i), 1.0]) for i, _ in enumerate(kwargs["input"])],
                                   usage=SimpleNamespace(total_tokens=7))
    fake = FakeEmbeddings()
    service = EmbeddingService(model="test", dimensions=2, client=SimpleNamespace(embeddings=fake),
                               cache=SQLiteCache(tmp_path / "cache.db"))
    assert await service.embed(["text"]) == [[0.0, 1.0]]
    assert await service.embed(["text"]) == [[0.0, 1.0]]
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_embedding_batches_deduplicate_and_run_concurrently():
    class FakeEmbeddings:
        def __init__(self):
            self.calls = []
            self.both_started = asyncio.Event()

        async def create(self, **kwargs):
            self.calls.append(kwargs["input"])
            if len(self.calls) == 2:
                self.both_started.set()
            await self.both_started.wait()
            return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[float(ord(kwargs["input"][0][0]))])],
                                   usage=SimpleNamespace(total_tokens=1))

    fake = FakeEmbeddings()
    service = EmbeddingService(model="test", dimensions=1, client=SimpleNamespace(embeddings=fake), concurrency=2)
    vectors = await asyncio.wait_for(service.embed(["AX", "BX", "AX"], batch_size=1), 2)
    assert vectors == [[65.0], [66.0], [65.0]]
    assert len(fake.calls) == 2
    assert service.requests == 2
    assert service.tokens == 2


@pytest.mark.asyncio
async def test_embedding_retries_rate_limit_once():
    class RateLimited(Exception):
        status_code = 429

    class FakeEmbeddings:
        calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RateLimited()
            return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[1.0])],
                                   usage=SimpleNamespace(total_tokens=2))

    fake = FakeEmbeddings()
    service = EmbeddingService(model="test", dimensions=1, client=SimpleNamespace(embeddings=fake), max_retries=1)
    assert await service.embed(["AX"]) == [[1.0]]
    assert service.requests == 2
    assert service.tokens == 2


@pytest.mark.asyncio
async def test_hybrid_query_preserves_filter_and_vector():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"hits": []})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        embedder = SimpleNamespace(model="test", dimensions=2, embed=lambda texts: __import__("asyncio").sleep(0, result=[[.1, .2]]))
        search = TypesenseSearch(api_key="test", client=client, embedder=embedder,
                                 embedding_model="test", dimensions=2)
        assert await search.search("RTX 4080", filters={"document_type": "pdf"}) == []
    params = requests[0].url.params
    assert "vector_query" in params
    assert "document_type" in params["filter_by"]
    assert params["q"] == "RTX 4080"
