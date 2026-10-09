from __future__ import annotations

import asyncio
import csv
import io
import json
import statistics
import tempfile
import time
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from pydantic import BaseModel

from .models import ProcessingRequest
from .processing import Job, JobProcessor, JobStore


@dataclass
class BenchmarkResult:
    scenario: str
    submitted: int
    completed: int
    failed: int
    timed_out: int
    elapsed_seconds: float
    throughput_per_second: float
    p50_seconds: float
    p95_seconds: float
    simulated_time: bool = False


@dataclass
class LabeledCase:
    text: str
    truth: dict[str, Any]


@dataclass
class ExtractionBenchmarkResult:
    backend: str
    cases: int
    precision: float
    recall: float
    f1: float
    exact_match: float
    mean_latency_seconds: float


def synthetic_extraction_cases(seed: int = 42, count: int = 20) -> list[LabeledCase]:
    rng = random.Random(seed)
    cases = []
    makers = ["Acme Systems", "Nordwerk GmbH", "Helios Robotics"]
    for i in range(count):
        maker = rng.choice(makers)
        model = f"AX-{rng.randint(10, 99)}"
        standard = rng.choice(["ISO 9001", "IEC 62368-1"])
        german = i % 2 == 1
        text = (f"Hersteller: {maker}. Modell: {model}. Norm: {standard}." if german else
                f"Manufacturer: {maker}. Model: {model}. Standard: {standard}.")
        cases.append(LabeledCase(text, {"manufacturer": maker, "model_code": model,
                                        "supported_standards": [standard]}))
    return cases


def _facts(data: dict[str, Any]) -> set[tuple[str, str]]:
    result = set()
    for key, value in data.items():
        if value is None: continue
        for item in value if isinstance(value, list) else [value]:
            result.add((key, str(item)))
    return result


async def compare_extraction_backends(backends: dict[str, Any], schema: type[BaseModel],
                                      cases: list[LabeledCase]) -> list[ExtractionBenchmarkResult]:
    results = []
    for name, backend in backends.items():
        true_positive = false_positive = false_negative = exact = 0
        latencies = []
        for case in cases:
            started = time.perf_counter()
            output = await backend.extract(case.text, schema)
            latencies.append(time.perf_counter() - started)
            predicted, truth = _facts(output.data), _facts(case.truth)
            true_positive += len(predicted & truth)
            false_positive += len(predicted - truth)
            false_negative += len(truth - predicted)
            exact += predicted == truth
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0
        results.append(ExtractionBenchmarkResult(name, len(cases), precision, recall,
            2 * precision * recall / (precision + recall) if precision + recall else 0,
            exact / len(cases) if cases else 0, statistics.mean(latencies) if latencies else 0))
    return results


def percentile(values: list[float], fraction: float) -> float:
    if not values: return 0.0
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)


async def run_scenario(name: str, *, count: int = 20, workers: int = 4,
                       delay: float = 0.01, failure_every: int = 0, deadline: float = 2.0,
                       arrivals: float = 0) -> BenchmarkResult:
    async def mock_worker(job: Job) -> dict:
        await asyncio.sleep(delay)
        if failure_every and int(job.request.job_id.split("-")[-1]) % failure_every == 0:
            raise ValueError("injected permanent failure")
        return {"value": job.request.job_id}
    with tempfile.TemporaryDirectory() as temp:
        store = JobStore(Path(temp) / "jobs.db")
        processor = JobProcessor(mock_worker, store, concurrency=workers, capacity=max(1, count), timeout=deadline)
        await processor.start()
        start = time.perf_counter()
        for i in range(count):
            request = ProcessingRequest(job_id=f"{name}-{i}", document_id=f"doc-{i}",
                deadline=datetime.now(timezone.utc) + timedelta(seconds=deadline))
            await processor.submit(Job(request=request, max_retries=0))
            if arrivals: await asyncio.sleep(arrivals)
        await processor.stop()
        elapsed = time.perf_counter() - start
        results = [store.get(f"{name}-{i}")[1] for i in range(count)]
    durations = [r.duration_seconds for r in results if r is not None]
    completed = sum(r.status == "completed" for r in results)
    return BenchmarkResult(name, count, completed, sum(r.status == "failed" for r in results),
        sum(r.status == "timed_out" for r in results), elapsed,
        completed / elapsed if elapsed else 0, percentile(durations, .5), percentile(durations, .95))


async def run_suite() -> list[BenchmarkResult]:
    return [await run_scenario("sequential", workers=1),
            await run_scenario("concurrent", workers=4),
            await run_scenario("continuous", workers=4, arrivals=.005),
            await run_scenario("burst", count=40, workers=2, deadline=.1),
            await run_scenario("failures", workers=4, failure_every=5)]


def render(results: list[BenchmarkResult], format: str = "markdown") -> str:
    rows = [asdict(item) for item in results]
    if format == "json": return json.dumps(rows, indent=2)
    if format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0]) if rows else [])
        if rows: writer.writeheader(); writer.writerows(rows)
        return output.getvalue()
    if format == "markdown":
        return "| Scenario | Completed | Failed | Timed out | Elapsed s | Throughput/s | P95 s |\n|---|---:|---:|---:|---:|---:|---:|\n" + "\n".join(
            f"| {r.scenario} | {r.completed}/{r.submitted} | {r.failed} | {r.timed_out} | {r.elapsed_seconds:.3f} | {r.throughput_per_second:.2f} | {r.p95_seconds:.3f} |" for r in results)
    raise ValueError("unsupported benchmark format")


def render_extraction(results: list[ExtractionBenchmarkResult], format: str = "markdown") -> str:
    rows = [asdict(item) for item in results]
    if format == "json": return json.dumps(rows, indent=2)
    if format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0]) if rows else [])
        if rows: writer.writeheader(); writer.writerows(rows)
        return output.getvalue()
    if format == "markdown":
        return "| Backend | Cases | Precision | Recall | F1 | Exact match | Mean latency s |\n|---|---:|---:|---:|---:|---:|---:|\n" + "\n".join(
            f"| {r.backend} | {r.cases} | {r.precision:.3f} | {r.recall:.3f} | {r.f1:.3f} | {r.exact_match:.3f} | {r.mean_latency_seconds:.3f} |" for r in results)
    raise ValueError("unsupported benchmark format")
