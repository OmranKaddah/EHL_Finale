from types import SimpleNamespace

import pytest

from hackathon_toolkit.models import DocumentChunk
from hackathon_toolkit.rag import GroundedAnswer, ask
from hackathon_toolkit.search import SearchHit


class FakeSearch:
    async def search(self, *args, **kwargs):
        return [SearchHit(chunk=DocumentChunk(id="c1", document_id="d1", text="Memory: 64 GB",
            filename="spec.txt", document_type="txt", page=2))]


class FakeResponses:
    async def parse(self, **kwargs):
        return SimpleNamespace(status="completed", output_parsed=GroundedAnswer(
            answer="64 GB [1]", supported=True, cited_indices=[1, 99]), usage=None)


@pytest.mark.asyncio
async def test_rag_maps_only_real_citations():
    result = await ask("How much memory?", FakeSearch(), client=SimpleNamespace(responses=FakeResponses()))
    assert result.supported
    assert len(result.sources) == 1
    assert result.sources[0].document_id == "d1"
    assert result.sources[0].page == 2
