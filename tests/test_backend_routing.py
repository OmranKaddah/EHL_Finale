from hackathon_toolkit.extraction import choose_backend
from hackathon_toolkit.schemas import GeneralDocument, RFQ, TechnicalSpecification


def test_auto_backend_requires_local_parser_compatible_schema_and_model():
    assert choose_backend("auto", "docling", TechnicalSpecification, local_available=True) == "gliner"
    assert choose_backend("auto", "tabular", GeneralDocument, local_available=True) == "gliner"
    assert choose_backend("auto", "docling", RFQ, local_available=True) == "llm"
    assert choose_backend("auto", "docling", TechnicalSpecification, local_available=False) == "llm"
    assert choose_backend("auto", "llm", TechnicalSpecification, local_available=True) == "llm"
    assert choose_backend("gliner", "docling", RFQ, local_available=False) == "gliner"
