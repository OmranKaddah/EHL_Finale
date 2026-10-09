from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Awaitable, Callable

Worker = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass
class Step:
    name: str
    worker: Worker
    depends_on: tuple[str, ...] = ()
    when: Callable[[dict[str, Any]], bool] | None = None
    timeout: float | None = None
    retries: int = 0


@dataclass
class WorkflowResult:
    state: dict[str, Any]
    timings: dict[str, float] = field(default_factory=dict)


async def run_workflow(steps: list[Step], initial: dict[str, Any] | None = None) -> WorkflowResult:
    pending = {s.name: s for s in steps}
    if len(pending) != len(steps): raise ValueError("duplicate workflow step names")
    state = dict(initial or {})
    timings: dict[str, float] = {}
    while pending:
        ready = [s for s in pending.values() if all(dep in state for dep in s.depends_on)]
        if not ready: raise ValueError("workflow has missing or cyclic dependencies")
        async def execute(step: Step):
            started = perf_counter()
            try:
                if step.when and not step.when(state): return None
                for attempt in range(step.retries + 1):
                    try:
                        coro = step.worker(dict(state))
                        return await asyncio.wait_for(coro, step.timeout) if step.timeout else await coro
                    except Exception:
                        if attempt == step.retries: raise
                        await asyncio.sleep(min(0.1 * 2 ** attempt, 2))
            finally:
                timings[step.name] = perf_counter() - started
        results = await asyncio.gather(*(execute(s) for s in ready))
        for step, value in zip(ready, results):
            state[step.name] = value
            del pending[step.name]
    return WorkflowResult(state, timings)
