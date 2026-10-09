import asyncio
import httpx
import pytest

from hackathon_toolkit.api import create_app
from hackathon_toolkit.config import Settings
from hackathon_toolkit.models import ExtractionResult, ParsedDocument


@pytest.mark.asyncio
async def test_upload_extract_and_job(tmp_path):
    async def fake_extract(document, request):
        return {"document_id": document.metadata.id, "schema": request.schema_name}
    app = create_app(settings=Settings(sqlite_path=str(tmp_path / "jobs.db")),
                     upload_dir=tmp_path / "uploads", extractor=fake_extract)
    async with app.router.lifespan_context(app):
      async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post("/documents?filename=spec.txt", content=b"Model AX")
        assert uploaded.status_code == 200
        document_id = uploaded.json()["id"]
        request = {"document_id": document_id, "schema_name": "technical"}
        assert (await client.post("/extract", json=request)).json()["document_id"] == document_id
        created = await client.post("/jobs", json=request)
        assert created.status_code == 200
        job_id = created.json()["job_id"]
        for _ in range(20):
            result = (await client.get(f"/jobs/{job_id}")).json()
            if result["status"] == "completed": break
            await asyncio.sleep(.01)
        assert result["status"] == "completed"
        assert (await client.get(f"/jobs/{job_id}/results")).json()["data"]["schema"] == "technical"
        assert (await client.post("/documents?filename=../bad.txt", content=b"x")).status_code == 400


@pytest.mark.asyncio
async def test_tabular_api_path_parses_all_rows_before_extraction(tmp_path, monkeypatch):
    class FakeBackend:
        def __init__(self, **kwargs):
            pass

        async def extract(self, source, schema, *, instructions="", timeout=120):
            assert isinstance(source, ParsedDocument)
            assert [row[0] for table in source.sections[0].tables for row in table.rows] == ["AX", "BX", "CX"]
            return ExtractionResult(document_id=source.metadata.id, backend="fake", data={"count": 3})

    monkeypatch.setattr("hackathon_toolkit.extraction.OpenAIExtractionBackend", FakeBackend)
    app = create_app(settings=Settings(sqlite_path=str(tmp_path / "jobs.db"), tabular_rows_per_table=2),
                     upload_dir=tmp_path / "uploads")
    async with app.router.lifespan_context(app):
      async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        uploaded = await client.post("/documents?filename=products.csv", content=b"model\nAX\nBX\nCX\n")
        assert uploaded.status_code == 200
        extracted = await client.post("/extract", json={"document_id": uploaded.json()["id"],
                                                  "schema_name": "technical", "parser": "tabular"})
        assert extracted.status_code == 200
        assert extracted.json()["data"] == {"count": 3}
