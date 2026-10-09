import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from hackathon_toolkit.ingestion import ingest_bytes
from hackathon_toolkit.parsing import LLMDocumentParser, ParseOptions, ParsedStructure
from hackathon_toolkit.extraction import OpenAIExtractionBackend
from hackathon_toolkit.models import Section, TextBlock


class Schema(BaseModel):
    model: str | None
    ram_gb: int | None


class Responses:
    def __init__(self, output): self.output = output; self.calls = []
    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.output, status="completed", usage=SimpleNamespace(input_tokens=5, output_tokens=3))


def test_ingestion_deduplicates_content(tmp_path):
    one = ingest_bytes(b"hello", "one.txt")
    two = ingest_bytes(b"hello", "two.txt")
    assert one.metadata.id == two.metadata.id
    with pytest.raises(ValueError): ingest_bytes(b"x", "bad.exe")
    with pytest.raises(ValueError): ingest_bytes(b"x" * 1024 * 1024 * 2, "big.txt", max_mb=1)


@pytest.mark.asyncio
async def test_llm_parser_uses_structured_response():
    document = ingest_bytes(b"Model AX", "spec.txt")
    responses = Responses(ParsedStructure(title="Spec", sections=[Section(blocks=[TextBlock(text="Model AX")])]))
    parsed = await LLMDocumentParser(SimpleNamespace(responses=responses)).parse(document, ParseOptions())
    assert parsed.text() == "Model AX"
    assert responses.calls[0]["text_format"] is ParsedStructure


@pytest.mark.asyncio
async def test_direct_extraction_one_call():
    document = ingest_bytes(b"Model AX, 64 GB", "spec.txt")
    responses = Responses({"data": {"model": "AX", "ram_gb": 64}, "evidence": []})
    extracted = await OpenAIExtractionBackend(client=SimpleNamespace(responses=responses)).extract(document, Schema)
    assert extracted.data == {"model": "AX", "ram_gb": 64}
    assert extracted.input_tokens == 5
    assert len(responses.calls) == 1
