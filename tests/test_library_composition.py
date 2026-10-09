import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from hackathon_toolkit.config import Settings
from hackathon_toolkit.ingestion import ingest_bytes
from hackathon_toolkit.models import Document, ParsedDocument, ExtractionResult, ProcessingRequest
from hackathon_toolkit.pipeline import DocumentPipeline, ExtractionWorker, create_pipeline
from hackathon_toolkit.processing import Job, JobProcessor, JobStore


class Product(BaseModel):
    model: str


class Extractor:
    def __init__(self):
        self.sources = []

    async def extract(self, source, schema, *, instructions="", timeout=120):
        self.sources.append(source)
        return ExtractionResult(document_id=source.metadata.id, backend="test", data={"model": "AX"})


@pytest.mark.asyncio
async def test_factory_routing_preserves_direct_and_parsed_paths(monkeypatch):
    from hackathon_toolkit import extraction
    class Backend(Extractor):
        def __init__(self, **kwargs):
            super().__init__()
    monkeypatch.setattr(extraction, "OpenAIExtractionBackend", Backend)
    doc = ingest_bytes(b"model\nAX\n", "data.csv")
    direct = create_pipeline(Product)
    await direct.extract(doc, Product)
    assert isinstance(direct.extractor.sources[0], Document)
    parsed = create_pipeline(Product, parser_name="tabular")
    await parsed.extract(doc, Product)
    assert isinstance(parsed.extractor.sources[0], ParsedDocument)


@pytest.mark.asyncio
async def test_custom_parser_and_extractor_and_keyword_index():
    from hackathon_toolkit.parsing import TabularDocumentParser
    backend = Extractor()
    pipeline = create_pipeline(parser=TabularDocumentParser(), extractor=backend)
    doc = ingest_bytes(b"model\nAX\n", "data.csv")
    result = await pipeline.extract(doc, Product)
    assert result.data == {"model": "AX"}
    assert isinstance(backend.sources[0], ParsedDocument)
    class Search:
        ready = False
        async def ensure_collection(self): self.ready = True
        async def index(self, chunks, *, vectors):
            assert self.ready
            assert vectors is None
            assert "AX" in chunks[0].text
    assert await pipeline.index(doc, Search()) == 1


@pytest.mark.asyncio
async def test_extraction_worker_persists_custom_adapter_receipt(tmp_path):
    from hackathon_toolkit.parsing import TabularDocumentParser
    path = tmp_path / "input.csv"
    path.write_text("model\nAX\n")
    calls = []
    class Adapter:
        async def submit(self, key, result, *, dry_run=False):
            calls.append((key, result))
            return "receipt-1"
    store = JobStore(tmp_path / "jobs.db")
    worker = ExtractionWorker(DocumentPipeline(parser=TabularDocumentParser(), extractor=Extractor()),
                              Product, submitter=Adapter(), store=store)
    processor = JobProcessor(worker, store, concurrency=1)
    job = Job(ProcessingRequest(job_id="j1", document_id="d1"), payload=str(path))
    await processor.start()
    await processor.submit(job)
    await processor.stop()
    assert store.get("j1")[1].data["data"] == {"model": "AX"}
    await worker(job)
    assert len(calls) == 1
    assert not store.begin_submission("j1")


def test_programmatic_settings_validated_without_environment(monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE", "invalid")
    assert create_pipeline().parse_options.model == Settings().parser_model
    with pytest.raises(ValueError): Settings(chunk_size=0)
    with pytest.raises(ValueError): Settings.from_env()


@pytest.mark.asyncio
async def test_cli_calls_shared_pipeline(tmp_path, monkeypatch, capsys):
    from hackathon_toolkit import cli
    path = tmp_path / "input.csv"
    path.write_text("model\nAX\n")
    monkeypatch.setenv("ENABLE_CACHE", "false")
    await cli._run(SimpleNamespace(command="parse", path=str(path), parser="tabular",
                                   backend=None, parse_first=False, schema="general"))
    assert '"AX"' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_legacy_asgi_entrypoint_is_lazy_and_serves(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from hackathon_toolkit import api
    instance = FastAPI()
    @instance.get("/health")
    async def health(): return {"status": "ok"}
    calls = []
    def factory():
        calls.append(True)
        return instance
    monkeypatch.setattr(api, "_default_app", None)
    monkeypatch.setattr(api, "create_app", factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
        assert not calls
        assert (await client.get("/health")).json() == {"status": "ok"}
        assert (await client.get("/health")).status_code == 200
    assert len(calls) == 1
