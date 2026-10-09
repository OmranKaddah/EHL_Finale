"""Exercise the installed distribution from a separate consumer project."""
import json
import os
from pathlib import Path
import subprocess
import sys
import site
import textwrap
import venv

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def consumer(tmp_path_factory):
    directory = tmp_path_factory.mktemp("external-consumer")
    environment = directory / "venv"
    # Reuse test dependencies without network; install our own editable distribution.
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    library = subprocess.check_output([str(python), "-I", "-c",
                                       "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip()
    # Share only dependency directories. Their .pth files are not processed, so
    # the source checkout's editable path is not inherited by this environment.
    (Path(library) / "test-dependencies.pth").write_text("\n".join(site.getsitepackages()) + "\n")
    result = subprocess.run([str(python), "-I", "-m", "pip", "install", "--no-deps",
                             "--no-build-isolation", "--no-index", "-e", str(ROOT)],
                            cwd=directory, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return directory, python


def run_consumer(consumer, script):
    directory, python = consumer
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "OPENAI_"))}
    result = subprocess.run([str(python), "-I", "-B", "-c", textwrap.dedent(script)],
                            cwd=directory, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_editable_metadata_and_imports_without_optional_dependencies(consumer):
    run_consumer(consumer, f'''
        import importlib.abc
        import importlib.metadata
        import json
        from pathlib import Path
        import sys
        blocked = {{"openai", "fastapi", "uvicorn", "pint", "httpx", "docling", "gliner2",
                    "openpyxl", "pymupdf", "fitz", "torch", "transformers"}}
        class BlockOptional(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] in blocked:
                    raise AssertionError("optional dependency imported: " + fullname)
        sys.meta_path.insert(0, BlockOptional())
        before = set(Path.cwd().iterdir())
        import hackathon_toolkit as toolkit
        import pkgutil
        for module in pkgutil.iter_modules(toolkit.__path__):
            if module.name != "api":
                __import__("hackathon_toolkit." + module.name)
        for name in toolkit.__all__:
            getattr(toolkit, name)
        from hackathon_toolkit.pipeline import create_pipeline, create_search
        create_pipeline()
        create_search()
        toolkit.LLMDocumentParser()
        toolkit.OpenAIExtractionBackend()
        toolkit.EmbeddingService()
        toolkit.TypesenseSearch(api_key="test")
        from hackathon_toolkit.extraction import GLiNERExtractionBackend
        GLiNERExtractionBackend()
        assert set(Path.cwd().iterdir()) == before
        assert not (blocked & set(sys.modules))
        distribution = importlib.metadata.distribution("hackathon-toolkit")
        direct = json.loads(distribution.read_text("direct_url.json"))
        assert direct["dir_info"]["editable"] is True
        assert direct["url"] == {ROOT.as_uri()!r}
        assert Path(toolkit.__file__).resolve() == Path({str(ROOT / 'src/hackathon_toolkit/__init__.py')!r})
        requirements = distribution.requires
        assert [r for r in requirements if ";" not in r] == ["pydantic>=2.8"]
        from hackathon_toolkit.matching import Constraint, Specification, match_requirements
        assert match_requirements([Constraint(attribute="ram", operator="gte", value=32)],
                                  {{"ram": Specification(value=64)}}).overall == "PASS"
    ''')


def test_import_api_does_not_initialize_resources(consumer):
    run_consumer(consumer, '''
        from pathlib import Path
        from unittest.mock import patch
        import asyncio
        import socket
        import sqlite3
        from hackathon_toolkit.config import Settings
        before = set(Path.cwd().iterdir())
        def forbidden(*args, **kwargs):
            raise AssertionError("import started a resource")
        with patch.object(Settings, "from_env", forbidden), \
             patch.object(sqlite3, "connect", forbidden), \
             patch.object(socket.socket, "connect", forbidden), \
             patch.object(asyncio, "create_task", forbidden):
            import hackathon_toolkit.api as api
            assert api._default_app is None
            assert callable(api.app)
        assert set(Path.cwd().iterdir()) == before
    ''')


def test_injected_async_components_without_openai_sdk(consumer):
    run_consumer(consumer, '''
        import asyncio
        import importlib.abc
        import sys
        from types import SimpleNamespace
        from pydantic import BaseModel
        class NoSDK(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] == "openai":
                    raise AssertionError("injected client should not need the SDK")
        sys.meta_path.insert(0, NoSDK())
        from hackathon_toolkit.ingestion import ingest_bytes
        from hackathon_toolkit.parsing import LLMDocumentParser
        from hackathon_toolkit.extraction import OpenAIExtractionBackend
        from hackathon_toolkit.embeddings import EmbeddingService
        from hackathon_toolkit.rag import ask
        from hackathon_toolkit.models import chunk_document
        from hackathon_toolkit.search import SearchHit
        class Schema(BaseModel):
            model: str
        class Responses:
            async def parse(self, **kwargs):
                name = kwargs["text_format"].__name__
                data = ({"sections": [{"blocks": [{"text": "Model AX"}]}]} if name == "ParsedStructure"
                        else {"answer": "AX [1]", "supported": True, "cited_indices": [1]} if name == "GroundedAnswer"
                        else {"data": {"model": "AX"}, "evidence": []})
                return SimpleNamespace(output_parsed=data, status="completed")
        class Embeddings:
            async def create(self, **kwargs):
                return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[1., 0.])])
        async def main():
            client = SimpleNamespace(responses=Responses(), embeddings=Embeddings())
            parsed = await LLMDocumentParser(client=client).parse(ingest_bytes(b"Model AX", "x.txt"))
            extracted = await OpenAIExtractionBackend(client=client).extract(parsed, Schema)
            assert extracted.data == {"model": "AX"}
            assert await EmbeddingService(client=client, dimensions=2).embed([parsed.text()]) == [[1., 0.]]
            class Retrieval:
                async def search(self, *args, **kwargs):
                    return [SearchHit(chunk=chunk_document(parsed)[0])]
            assert (await ask("model?", Retrieval(), client=client)).supported
        asyncio.run(main())
    ''')


def test_complete_documented_pipeline_from_external_project(consumer):
    # Extract the actual copy-paste example so documentation cannot silently drift.
    guide = (ROOT / "LIBRARY_USAGE.md").read_text()
    script = guide.split("<!-- complete-pipeline -->\n```python\n", 1)[1].split("\n```", 1)[0]
    run_consumer(consumer, script)
    directory, _ = consumer
    output = json.loads((directory / "challenge-output" / "catalogue.json").read_text())
    assert output["selected"] == "AX"
    assert output["match"]["overall"] == "PASS"


def test_retrieval_and_scheduler_in_external_project(consumer):
    run_consumer(consumer, '''
        import asyncio
        import httpx
        from hackathon_toolkit.ingestion import ingest_bytes
        from hackathon_toolkit.parsing import TabularDocumentParser
        from hackathon_toolkit.models import ProcessingRequest, chunk_document
        from hackathon_toolkit.search import TypesenseSearch
        from hackathon_toolkit.processing import Job, JobProcessor, JobStore
        async def main():
            parsed = await TabularDocumentParser().parse(ingest_bytes(b"model\\nAX\\n", "input.csv"))
            chunk = chunk_document(parsed)[0]
            def handler(request):
                assert request.url.params["q"] == "AX"
                assert "vector_query" not in request.url.params
                return httpx.Response(200, json={"hits": [{"document": chunk.model_dump(), "text_match": 1}]})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                search = TypesenseSearch(api_key="test", client=client)
                async def worker(job):
                    hits = await search.search(job.payload, mode="keyword")
                    return {"text": hits[0].chunk.text}
                store = JobStore("external-jobs.db")
                processor = JobProcessor(worker, store, concurrency=1)
                await processor.start()
                try:
                    await processor.submit(Job(ProcessingRequest(job_id="retrieval", document_id=chunk.document_id),
                                               payload="AX"))
                finally:
                    await processor.stop()
                status, result = store.get("retrieval")
                assert status == "completed"
                assert "AX" in result.data["text"]
        asyncio.run(main())
    ''')
