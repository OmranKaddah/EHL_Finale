import httpx
import pytest

from hackathon_toolkit.output import HTTPSubmitter, LocalSubmitter, export_results


@pytest.mark.asyncio
async def test_local_submission_and_export(tmp_path):
    submitter = LocalSubmitter(tmp_path)
    path = await submitter.submit("job-1", {"status": "completed"})
    assert (tmp_path / "job-1.json").is_file()
    assert await submitter.submit("job-1", {"status": "completed"}) == path
    assert "completed" in export_results([{"job_id": "job-1", "status": "completed"}], "csv")
    with pytest.raises(ValueError):
        await submitter.submit("../escape", {})


@pytest.mark.asyncio
async def test_http_submission_uses_idempotency_key():
    seen = []
    def handler(request):
        seen.append(request.headers.get("Idempotency-Key"))
        return httpx.Response(200, json={"accepted": True}, headers={"X-Submission-ID": "receipt"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        submitter = HTTPSubmitter("https://example.test/submit", client=client,
                                  response_validator=lambda response: response.json()["accepted"])
        assert await submitter.submit("job-1", {"x": 1}) == "receipt"
    assert seen == ["job-1"]
