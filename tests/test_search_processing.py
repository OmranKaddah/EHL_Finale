import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from hackathon_toolkit.cache import cache_key
from hackathon_toolkit.models import ProcessingRequest
from hackathon_toolkit.processing import Job, JobProcessor, JobStore
from hackathon_toolkit.search import TypesenseSearch
from hackathon_toolkit.workflows import Step, run_workflow


def test_embedding_cache_key_changes_with_configuration():
    assert cache_key("embedding", text="x", model="a", dimensions=3) != cache_key("embedding", text="x", model="b", dimensions=3)


def test_typesense_schema_dimensions():
    search = TypesenseSearch(api_key="test", dimensions=7)
    field = next(f for f in search.schema()["fields"] if f["name"] == "embedding")
    assert field["num_dim"] == 7


@pytest.mark.asyncio
async def test_workflow_dependency_and_parallelism():
    async def first(state): return 2
    async def second(state): return state["first"] * 2
    result = await run_workflow([Step("first", first), Step("second", second, depends_on=("first",))])
    assert result.state["second"] == 4
    with pytest.raises(ValueError):
        await run_workflow([Step("a", first, depends_on=("b",))])


@pytest.mark.asyncio
async def test_scheduler_deadline_dedup_and_persistence(tmp_path):
    async def worker(job):
        await asyncio.sleep(.005)
        return {"done": True}
    store = JobStore(tmp_path / "jobs.db")
    processor = JobProcessor(worker, store, concurrency=2, capacity=2)
    await processor.start()
    job = Job(ProcessingRequest(job_id="a", document_id="doc", deadline=datetime.now(timezone.utc) + timedelta(seconds=1)))
    assert await processor.submit(job)
    assert not await processor.submit(job)
    await processor.stop()
    assert store.get("a")[1].status == "completed"


@pytest.mark.asyncio
async def test_scheduler_expired_deadline(tmp_path):
    async def worker(job): return {"done": True}
    store = JobStore(tmp_path / "jobs.db")
    processor = JobProcessor(worker, store)
    await processor.start()
    job = Job(ProcessingRequest(job_id="expired", document_id="doc",
         deadline=datetime.now(timezone.utc) - timedelta(seconds=1)))
    await processor.submit(job)
    await processor.stop()
    assert store.get("expired")[1].status == "timed_out"


@pytest.mark.asyncio
async def test_recovery_replays_persisted_payload(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    request = ProcessingRequest(job_id="recover", document_id="doc")
    store.save(Job(request, payload="/tmp/document.txt"), "running")
    async def worker(job): return {"path": job.payload}
    processor = JobProcessor(worker, store, concurrency=1)
    await processor.start()
    assert await processor.recover() == 1
    await processor.stop()
    assert store.get("recover")[1].data["path"] == "/tmp/document.txt"


def test_submission_state_is_idempotent(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    assert store.begin_submission("job-1")
    assert store.begin_submission("job-1")  # pending can be reconciled/retried
    store.finish_submission("job-1", "external-1")
    assert not store.begin_submission("job-1")
