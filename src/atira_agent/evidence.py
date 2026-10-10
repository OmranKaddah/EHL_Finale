from __future__ import annotations

import re
from collections import defaultdict

from .contracts import RECORD_TYPES, EvidenceFact, Observation, Sourced


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class EvidenceLedger:
    def __init__(self, telemetry):
        self.telemetry = telemetry
        self.observations: dict[str, Observation] = {}
        self.facts: dict[str, EvidenceFact] = {}
        self.records: dict[str, dict[str, Sourced]] = defaultdict(dict)
        self.rejected: dict[tuple[str, str], dict] = {}
        self.conflicts: list[dict] = []

    def reject(self, kind: str, data: dict, error: str):
        key = (kind, str(data.get("id", "missing-id")))
        self.rejected[key] = {"kind": kind, "data": data, "error": error}
        if len(self.rejected) > 50:
            self.rejected.pop(next(iter(self.rejected)))

    def observe(self, observation: Observation) -> None:
        self.observations[observation.id] = observation

    def cite(self, observation_id: str, excerpt: str, scope: dict | None = None) -> EvidenceFact:
        # A control reference unambiguously identifies its originating observation. Accept that spelling,
        # but still require the exact excerpt to exist in that observation's visible text.
        control = re.fullmatch(r"(o\d+)-f\d+-e\d+", observation_id)
        if control:
            observation_id = control.group(1)
        if observation_id not in self.observations:
            raise ValueError(f"Unknown observation {observation_id!r}; use current_observation.id, not an element ref")
        observation = self.observations[observation_id]
        if len(compact(excerpt)) < 3 or compact(excerpt) not in compact(observation.text):
            raise ValueError("Citation must be an exact visible excerpt from the named observation")
        fact = EvidenceFact(
            id=f"e{len(self.facts) + 1}", observation_id=observation_id, website=observation.url,
            url=observation.url, title=observation.title, excerpt=excerpt, action_id=observation.action_id,
            observed_at=observation.observed_at, scope=scope or {},
        )
        self.facts[fact.id] = fact
        self.telemetry.emit("evidence_added", evidence=fact.model_dump(mode="json"))
        return fact

    def record(self, kind: str, data: dict) -> Sourced:
        if kind not in RECORD_TYPES:
            raise ValueError(f"Unknown record kind: {kind}")
        record = RECORD_TYPES[kind].model_validate(data)
        missing = [ref for ref in record.evidence if ref not in self.facts]
        if missing:
            raise ValueError(f"Unknown evidence references: {missing}")
        old = self.records[kind].get(record.id)
        if old and old != record:
            self.conflicts.append({"kind": kind, "id": record.id, "previous": old.model_dump(mode="json"),
                                   "replacement": record.model_dump(mode="json")})
            self.telemetry.emit("conflict_detected", kind=kind, record_id=record.id,
                                previous=old.model_dump(mode="json"), replacement=record.model_dump(mode="json"))
        self.records[kind][record.id] = record
        self.rejected.pop((kind, record.id), None)
        self.telemetry.emit("record_added", kind=kind, record=record.model_dump(mode="json"))
        return record

    def all(self, kind: str) -> list:
        return list(self.records[kind].values())

    def snapshot(self) -> dict:
        return {kind: [v.model_dump(mode="json") for v in values.values()] for kind, values in self.records.items() if values}

    def summary(self) -> dict:
        return {"records": self.snapshot(), "rejected_records": list(self.rejected.values()),
                "extraction_replacements": self.conflicts[-20:], "evidence": [
            {"id": v.id, "scope": v.scope, "excerpt": v.excerpt[:120]} for v in self.facts.values()
        ]}
