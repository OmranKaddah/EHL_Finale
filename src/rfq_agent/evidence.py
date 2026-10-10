"""Small, provenance-carrying evidence records selected by the planner."""

import asyncio
import hashlib
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Evidence:
    claim: str
    quote: str
    site_id: str
    url: str
    title: str
    step: int
    worker_id: str = ""

    @property
    def evidence_id(self) -> str:
        identity = "\0".join((self.site_id, self.url, self.title, self.quote))
        return "e-" + hashlib.sha256(identity.encode()).hexdigest()[:20]

    def to_dict(self) -> dict:
        return dict(asdict(self), evidence_id=self.evidence_id)


class EvidenceLedger:
    """Async-safe shared evidence for concurrent site investigators."""

    def __init__(self) -> None:
        self._items: list[Evidence] = []
        self._lock = asyncio.Lock()

    async def add(self, item: Evidence) -> bool:
        async with self._lock:
            # Avoid duplicate records when parallel investigators reach the same page.
            if not any((old.site_id, old.url, old.title, old.quote) == (item.site_id, item.url, item.title, item.quote)
                       for old in self._items):
                self._items.append(item)
                return True
            return False


    async def snapshot(self) -> list[Evidence]:
        async with self._lock:
            return list(self._items)
