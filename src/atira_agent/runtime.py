from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field

import httpx

from .contracts import RunContext

USER_AGENT = "ehl-atira-independent-agent/0.1"


async def load_run(env=None, transport=None) -> RunContext:
    env = os.environ if env is None else env
    if not env.get("CHALLENGE_RUN_TOKEN"):
        raw = env.get("CHALLENGE_SCOUTING")
        if not raw:
            raise ValueError("Load scouting access: atira scout --env | Out-String | Invoke-Expression")
        return RunContext.model_validate(json.loads(raw))
    base = env.get("CHALLENGE_API_URL", "").rstrip("/")
    if not base:
        raise ValueError("Missing CHALLENGE_API_URL")
    async with httpx.AsyncClient(transport=transport, timeout=25, headers={
        "User-Agent": USER_AGENT, "x-api-key": env["CHALLENGE_RUN_TOKEN"],
    }) as client:
        for attempt in range(3):
            try:
                response = await client.get(base + "/v1/runs/current")
                response.raise_for_status()
                return RunContext.model_validate(response.json())
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise RuntimeError(f"Cannot read run: HTTP {exc.response.status_code}") from None
                if attempt == 2:
                    raise RuntimeError("Cannot read run after three attempts") from None
                await asyncio.sleep(2 ** attempt)
    raise AssertionError("unreachable")


@dataclass
class Deadline:
    budget: float
    reserve: float
    expires_at_ms: int | None = None
    started: float = field(default_factory=time.monotonic)

    @property
    def remaining(self) -> float:
        remaining = self.budget - (time.monotonic() - self.started)
        if self.expires_at_ms is not None:
            remaining = min(remaining, self.expires_at_ms / 1000 - time.time())
        return max(0, remaining)

    @property
    def submission_due(self) -> bool:
        return self.remaining <= self.reserve

    def timeout(self, preferred: float = 90, investigation: bool = False) -> float:
        available = self.remaining - (self.reserve if investigation else 0)
        if available <= 0:
            raise TimeoutError("Deadline budget exhausted")
        return min(preferred, available)
