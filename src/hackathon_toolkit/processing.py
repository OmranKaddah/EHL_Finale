from __future__ import annotations

import asyncio
import json
import random
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Literal

from .models import ProcessingRequest, ProcessingResult


@dataclass
class Job:
    request: ProcessingRequest
    payload: object = None
    max_retries: int = 2
    attempts: int = 0
    arrival_monotonic: float = field(default_factory=time.monotonic)


class JobStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, request TEXT NOT NULL, payload TEXT, attempts INTEGER NOT NULL, status TEXT NOT NULL, result TEXT, updated_at TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS submissions (key TEXT PRIMARY KEY, state TEXT NOT NULL, response TEXT)")

    def save(self, job: Job, status: str, result: ProcessingResult | None = None) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET attempts=excluded.attempts,status=excluded.status,result=excluded.result,updated_at=excluded.updated_at",
                (job.request.job_id, job.request.model_dump_json(), json.dumps(job.payload), job.attempts,
                 status, result.model_dump_json() if result else None,
                 datetime.now(timezone.utc).isoformat()))

    def get(self, job_id: str) -> tuple[str, ProcessingResult | None] | None:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT status,result FROM jobs WHERE id=?", (job_id,)).fetchone()
        return (row[0], ProcessingResult.model_validate_json(row[1]) if row[1] else None) if row else None

    def recoverable(self) -> list[Job]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT request,payload,attempts FROM jobs WHERE status IN ('queued','running')").fetchall()
        now = datetime.now(timezone.utc)
        return [Job(request=r, payload=json.loads(row[1]), attempts=row[2]) for row in rows
                if (r := ProcessingRequest.model_validate_json(row[0])).deadline is None or r.deadline > now]

    def begin_submission(self, key: str) -> bool:
        """Return False only after a confirmed submission; pending may be retried with the same key."""
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT state FROM submissions WHERE key=?", (key,)).fetchone()
            if row and row[0] == "submitted":
                return False
            db.execute("INSERT OR IGNORE INTO submissions(key,state) VALUES(?, 'pending')", (key,))
            return True

    def finish_submission(self, key: str, response_id: str) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE submissions SET state='submitted',response=? WHERE key=?",
                       (response_id, key))


Worker = Callable[[Job], Awaitable[dict]]


class JobProcessor:
    def __init__(self, worker: Worker, store: JobStore, *, concurrency: int = 4, capacity: int = 100,
                 policy: Literal["fifo", "edf", "priority"] = "edf", timeout: float = 150,
                 clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], datetime] | None = None):
        if concurrency <= 0 or capacity <= 0 or timeout <= 0:
            raise ValueError("concurrency, capacity, and timeout must be positive")
        if policy not in {"fifo", "edf", "priority"}:
            raise ValueError("invalid scheduling policy")
        self.worker, self.store = worker, store
        self.concurrency, self.timeout = concurrency, timeout
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=capacity)
        self.policy, self.clock = policy, clock
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._sequence = 0
        self._tasks: list[asyncio.Task] = []
        self._active = 0

    def _key(self, job: Job) -> tuple:
        self._sequence += 1
        if self.policy == "priority": return (-job.request.priority, self._sequence)
        if self.policy == "edf":
            return (job.request.deadline.timestamp() if job.request.deadline else float("inf"), self._sequence)
        return (self._sequence,)

    async def submit(self, job: Job) -> bool:
        if self.store.get(job.request.job_id): return False
        self.store.save(job, "queued")
        await self.queue.put((self._key(job), job))
        return True

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._run()) for _ in range(self.concurrency)]

    async def recover(self) -> int:
        jobs = self.store.recoverable()
        for job in jobs:
            await self.queue.put((self._key(job), job))
        return len(jobs)

    async def stop(self) -> None:
        await self.queue.join()
        for task in self._tasks: task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run(self) -> None:
        while True:
            _, job = await self.queue.get()
            self._active += 1
            started = self.clock()
            self.store.save(job, "running")
            try:
                while True:
                    try:
                        remaining = ((job.request.deadline - self.wall_clock()).total_seconds()
                                     if job.request.deadline else self.timeout)
                        if remaining <= 0: raise TimeoutError("deadline expired in queue")
                        data = await asyncio.wait_for(self.worker(job), min(self.timeout, remaining))
                        result = ProcessingResult(job_id=job.request.job_id, document_id=job.request.document_id,
                            status="completed", data=data, duration_seconds=self.clock() - started,
                            timings={"queue_wait": started - job.arrival_monotonic})
                        self.store.save(job, "completed", result)
                        break
                    except (TimeoutError, asyncio.TimeoutError) as exc:
                        result = ProcessingResult(job_id=job.request.job_id, document_id=job.request.document_id,
                            status="timed_out", errors=[str(exc)], duration_seconds=self.clock() - started)
                        self.store.save(job, "timed_out", result)
                        break
                    except Exception as exc:
                        job.attempts += 1
                        if job.attempts > job.max_retries or (job.request.deadline and job.request.deadline <= self.wall_clock()):
                            result = ProcessingResult(job_id=job.request.job_id, document_id=job.request.document_id,
                                status="failed", errors=[str(exc)], duration_seconds=self.clock() - started)
                            self.store.save(job, "failed", result)
                            break
                        await asyncio.sleep(min(0.1 * 2 ** job.attempts + random.uniform(0, 0.05), 2))
            finally:
                self._active -= 1
                self.queue.task_done()

    @property
    def active(self) -> int:
        return self._active
