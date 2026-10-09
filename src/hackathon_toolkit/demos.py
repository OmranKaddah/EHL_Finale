"""Narrow sample workflows; core modules remain challenge-independent."""
from __future__ import annotations

import re
from pathlib import Path

from .ingestion import ingest_file
from .matching import Constraint, Specification, match_requirements, normalize_requirement


def match_sample_rfq(rfq_path: str | Path, specification_path: str | Path) -> dict:
    rfq_doc, spec_doc = ingest_file(rfq_path), ingest_file(specification_path)
    rfq = Path(rfq_path).read_text(encoding="utf-8")
    specification = Path(specification_path).read_text(encoding="utf-8")
    def required(pattern: str, text: str) -> re.Match:
        match = re.search(pattern, text, re.I)
        if match is None: raise ValueError(f"sample document lacks expected field: {pattern}")
        return match
    memory = required(r"at least\s+\d+\s+GB", rfq)
    power = required(r"must not exceed\s+\d+\s+W", rfq)
    gpu = required(r"RTX\s+\d+\s+or better", rfq)
    certification = required(r"support\s+(ISO\s+\d+)", rfq)
    requirements = [normalize_requirement(memory.group(), "memory"),
                    normalize_requirement(power.group(), "peak_power"),
                    normalize_requirement(gpu.group(), "gpu", mandatory=False),
                    Constraint(attribute="standards", operator="contains", value=certification[1],
                               evidence=certification.group())]
    spec_memory = required(r"Memory:\s*(\d+)\s*GB", specification)
    spec_power = required(r"(\d+)\s*W peak", specification)
    spec_gpu = required(r"GPU:\s*(RTX\s*\d+)", specification)
    spec_standards = required(r"Supported standards:\s*(.+)", specification)
    values = {"memory": Specification(value=float(spec_memory[1]), unit="GB", evidence=spec_memory.group()),
              "peak_power": Specification(value=float(spec_power[1]), unit="W", evidence=spec_power.group()),
              "gpu": Specification(value=spec_gpu[1], evidence=spec_gpu.group()),
              "standards": Specification(value=[s.strip() for s in spec_standards[1].split(",")],
                                         evidence=spec_standards.group())}
    report = match_requirements(requirements, values, hierarchy={"RTX 4080": ["RTX 4090"]})
    return {"rfq_document_id": rfq_doc.metadata.id, "specification_document_id": spec_doc.metadata.id,
            "report": report.model_dump(mode="json")}
