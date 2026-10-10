"""Run-local observations and citations. No credentials or page content in stdout logs."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone


class EvidenceBook:
    def __init__(self):
        self.observations: dict[str, dict] = {}
        self.facts: dict[str, dict] = {}

    def observe(self, url: str, text: str) -> str:
        key = f"obs-{len(self.observations) + 1}"
        self.observations[key] = {"url": url, "text": text,
                                  "sha256": hashlib.sha256(text.encode()).hexdigest(),
                                  "observed_at": datetime.now(timezone.utc).isoformat()}
        return key

    def cite(self, observation_id: str, quote: str, meaning: str) -> str:
        observation = self.observations[observation_id]
        if not quote.strip() or quote not in observation["text"]:
            raise ValueError("Citation must be an exact nonempty substring of the observation")
        key = f"ev-{len(self.facts) + 1}"
        self.facts[key] = {"observation_id": observation_id, "quote": quote, "meaning": meaning}
        return key

    def validate_references(self, value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "evidence_ids":
                    if not child or any(ref not in self.facts for ref in child):
                        raise ValueError("Unknown or empty evidence references")
                else:
                    self.validate_references(child)
        elif isinstance(value, list):
            for child in value:
                self.validate_references(child)

    def dump(self):
        return {"observations": self.observations, "facts": self.facts}
