"""Composable document intelligence toolkit.

Public convenience exports are lazy. Importing the package performs no I/O and
does not load optional integrations. Module-level APIs are documented in
LIBRARY_USAGE.md; caller-supplied clients remain caller-owned.
"""

from importlib import import_module

__version__ = "0.1.0"

_EXPORTS = {
    "Settings": ("config", "Settings"),
    "Document": ("models", "Document"),
    "ParsedDocument": ("models", "ParsedDocument"),
    "ExtractionResult": ("models", "ExtractionResult"),
    "ingest_file": ("ingestion", "ingest_file"),
    "ingest_bytes": ("ingestion", "ingest_bytes"),
    "LLMDocumentParser": ("parsing", "LLMDocumentParser"),
    "OpenAIExtractionBackend": ("extraction", "OpenAIExtractionBackend"),
    "EmbeddingService": ("embeddings", "EmbeddingService"),
    "TypesenseSearch": ("search", "TypesenseSearch"),
    "JobProcessor": ("processing", "JobProcessor"),
    "DocumentPipeline": ("pipeline", "DocumentPipeline"),
    "create_pipeline": ("pipeline", "create_pipeline"),
    "Step": ("workflows", "Step"),
    "run_workflow": ("workflows", "run_workflow"),
}
__all__ = ["__version__", *_EXPORTS]


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, attribute = _EXPORTS[name]
    value = getattr(import_module(f".{module}", __name__), attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
