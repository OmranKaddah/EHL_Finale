from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field, create_model


class RequirementRecord(BaseModel):
    attribute: str
    operator: str
    value: str | float | bool | None
    unit: str | None = None
    mandatory: bool = True
    evidence: str | None = None


class RFQ(BaseModel):
    customer_name: str | None
    product_category: str | None
    requirements: list[RequirementRecord]
    quantity: int | None
    delivery_deadline: str | None
    budget: str | None
    required_certifications: list[str]
    optional_conditions: list[str]


class TechnicalSpecification(BaseModel):
    manufacturer: str | None
    product_model: str | None
    model_code: str | None
    cpu: str | None
    gpu: str | None
    memory: str | None
    operating_temperature: str | None
    power_consumption: str | None
    dimensions: str | None
    supported_standards: list[str]


class GeneralDocument(BaseModel):
    organizations: list[str]
    dates: list[str]
    prices: list[str]
    locations: list[str]
    people: list[str]
    contractual_obligations: list[str]
    deadlines: list[str]


BUILTIN_SCHEMAS = {"rfq": RFQ, "technical": TechnicalSpecification, "general": GeneralDocument}


def _type_from_json_schema(spec: dict[str, Any]) -> Any:
    kind = spec.get("type", "string")
    nullable = isinstance(kind, list) and "null" in kind
    if isinstance(kind, list):
        kind = next((x for x in kind if x != "null"), "string")
    if kind == "object":
        fields = {}
        required = set(spec.get("required", []))
        for key, child in spec.get("properties", {}).items():
            field_type = _type_from_json_schema(child)
            fields[key] = (field_type if key in required else field_type | None,
                           Field(default=... if key in required else None, description=child.get("description")))
        result = create_model(spec.get("title", "CustomExtraction"), **fields)
    elif kind == "array":
        result = list[_type_from_json_schema(spec.get("items", {"type": "string"}))]
    else:
        result = {"string": str, "number": float, "integer": int, "boolean": bool}.get(kind)
        if result is None:
            raise ValueError(f"unsupported JSON Schema type: {kind}")
    return result | None if nullable else result


def load_schema(name_or_path: str) -> type[BaseModel]:
    if name_or_path in BUILTIN_SCHEMAS:
        return BUILTIN_SCHEMAS[name_or_path]
    spec = json.loads(Path(name_or_path).read_text())
    model = _type_from_json_schema(spec)
    if not isinstance(model, type) or not issubclass(model, BaseModel):
        raise ValueError("root extraction schema must be an object")
    return model
