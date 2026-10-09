import pytest
from pydantic import BaseModel

from hackathon_toolkit.benchmarks import compare_extraction_backends, synthetic_extraction_cases
from hackathon_toolkit.models import ExtractionResult


class BenchmarkSchema(BaseModel):
    manufacturer: str | None
    model_code: str | None
    supported_standards: list[str]


class ExactMock:
    async def extract(self, source, schema):
        import re
        maker = re.search(r"(?:Manufacturer|Hersteller): (.*?)\. (?:Model|Modell):", source).group(1)
        model = re.search(r"(?:Model|Modell): (AX-\d+)", source).group(1)
        standard = re.search(r"(?:Standard|Norm): (.*?)\.", source).group(1)
        return ExtractionResult(document_id="mock", backend="mock", data={"manufacturer": maker,
            "model_code": model, "supported_standards": [standard]})


@pytest.mark.asyncio
async def test_synthetic_cases_and_backend_metrics_are_reproducible():
    cases = synthetic_extraction_cases(seed=7, count=6)
    assert cases == synthetic_extraction_cases(seed=7, count=6)
    result = (await compare_extraction_backends({"exact-mock": ExactMock()}, BenchmarkSchema, cases))[0]
    assert (result.precision, result.recall, result.f1, result.exact_match) == (1, 1, 1, 1)
    assert result.mean_latency_seconds >= 0
