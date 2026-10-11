"""One monotonic run deadline with a research cutoff and a signing reserve."""

import asyncio
import time

RUN_LIMIT = 20 * 60
RESEARCH_LIMIT = 12 * 60
SIGNING_RESERVE = 6 * 60
EXIT_MARGIN = 20


class DeadlineExceeded(TimeoutError):
    pass


class RunClock:
    """Budgets derived from the live run window; wall time is read once, at start."""

    def __init__(self, task: dict, *, monotonic=time.monotonic, wall=time.time, run_limit: float = RUN_LIMIT,
                 research_limit: float = RESEARCH_LIMIT, signing_reserve: float = SIGNING_RESERVE,
                 exit_margin: float = EXIT_MARGIN):
        self._monotonic = monotonic
        start, now = monotonic(), wall()
        elapsed = 0.0
        started_at, expires_at = task.get("started_at"), task.get("expires_at")
        if isinstance(started_at, (int, float)) and not isinstance(started_at, bool):
            elapsed = max(0.0, now - started_at / 1000)
        left = run_limit - elapsed
        if isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool):
            left = min(left, expires_at / 1000 - now)
        self._deadline = start + max(0.0, left - exit_margin)
        self._research_cutoff = min(start - elapsed + research_limit, self._deadline - signing_reserve)

    def left(self) -> float:
        return max(0.0, self._deadline - self._monotonic())

    def research_left(self) -> float:
        return max(0.0, self._research_cutoff - self._monotonic())

    async def bounded(self, awaitable, *, cap: float | None = None, research: bool = False):
        """Await within the remaining budget; the pending call is cancelled at the deadline."""
        available = self.research_left() if research else self.left()
        if cap is not None:
            available = min(available, cap)
        if available <= 0:
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            raise DeadlineExceeded("research cutoff reached" if research else "run deadline reached")
        try:
            return await asyncio.wait_for(awaitable, available)
        except asyncio.TimeoutError as exc:
            raise DeadlineExceeded("research cutoff reached" if research else "run deadline reached") from exc
