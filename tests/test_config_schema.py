import json

import pytest

from hackathon_toolkit.config import Settings
from hackathon_toolkit.schemas import load_schema


def test_env_validation(monkeypatch):
    monkeypatch.setenv("ENABLE_EMBEDDINGS", "true")
    monkeypatch.setenv("CHUNK_SIZE", "100")
    monkeypatch.setenv("CHUNK_OVERLAP", "10")
    assert Settings.from_env().enable_embeddings
    monkeypatch.setenv("CHUNK_OVERLAP", "100")
    with pytest.raises(ValueError): Settings.from_env()


def test_custom_json_schema_is_validated(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(json.dumps({"type": "object", "properties": {"model": {"type": "string"}},
                                "required": ["model"]}))
    schema = load_schema(str(path))
    assert schema.model_validate({"model": "AX"}).model == "AX"
    with pytest.raises(Exception): schema.model_validate({})
