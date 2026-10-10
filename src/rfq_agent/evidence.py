"""Small, provenance-carrying evidence records selected by the planner."""

import asyncio
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

    def to_dict(self) -> dict:
        return asdict(self)


class EvidenceLedger:
    """Async-safe shared evidence for concurrent site investigators."""

    def __init__(self) -> None:
        self._items: list[Evidence] = []
        self._lock = asyncio.Lock()

    async def add(self, item: Evidence) -> None:
        async with self._lock:
            # Avoid duplicate records when parallel investigators reach the same page.
            if not any((old.site_id, old.url, old.quote) == (item.site_id, item.url, item.quote)
                       for old in self._items):
                self._items.append(item)


    async def snapshot(self) -> list[Evidence]:
        async with self._lock:
            return list(self._items)
