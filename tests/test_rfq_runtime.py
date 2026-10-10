import asyncio
from datetime import datetime, timedelta, timezone
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import zipfile

import httpx
import pytest

from hackathon_toolkit.rfq.browser import BrowserSession, document_text, origin
from hackathon_toolkit.rfq.evidence import EvidenceBook
from hackathon_toolkit.rfq.runtime import (Agent, ModelClient, agent_loop, compact_messages, run_seconds,
                                          save_artifacts, tool_definitions, wire_answer)
from test_rfq_pricing import bid


@pytest.fixture
def agent():
    book = EvidenceBook()
    obs = book.observe("https://tender.test/tender", "Invented test facts and prices.")
    book.cite(obs, "Invented test facts and prices.", "Synthetic calculation input")
    run = dict(brief="Synthetic testing task", access=[], submission={"kind": "site", "url": "https://tender.test"},
               answer_schema={"type": "object"})
    return Agent(SimpleNamespace(act=AsyncMock()), book, run)


def test_evidence_requires_real_exact_quote():
    book = EvidenceBook()
    obs = book.observe("https://example.test", "Material active. Stock 10.")
    assert book.cite(obs, "Stock 10", "Available inventory") == "ev-1"
    with pytest.raises(ValueError, match="exact"):
        book.cite(obs, "Stock 100", "Hallucinated inventory")
    with pytest.raises(ValueError, match="Unknown"):
        book.validate_references({"nested": [{"evidence_ids": ["absent"]}]})


async def test_calculation_and_receipt_gate(agent, bid):
    await agent.dispatch("calculate", bid)
    obs = agent.book.observe("https://mail.test", "Bid submitted")
    with pytest.raises(ValueError, match="submission site"):
        await agent.dispatch("finish", dict(observation_id=obs, receipt_quote="Bid submitted"))
    agent.reviewer = AsyncMock(return_value={"accepted": True, "reason": "Synthetic review checked"})
    review = agent.book.observe("https://tender.test/review", "Review SYNTHETIC-UNIT-TEST")
    await agent.dispatch("validate_submission", dict(observation_id=review, review_quote="Review SYNTHETIC-UNIT-TEST"))
    obs = agent.book.observe("https://tender.test/receipt", "Bid submitted. Receipt synthetic-123.")
    await agent.dispatch("finish", dict(observation_id=obs, receipt_quote="Bid submitted. Receipt synthetic-123."))
    assert agent.done and agent.receipt


async def test_partial_submission_requires_observed_tender_facts_and_receipt(agent):
    agent.book.observe("about:blank", "")
    agent.book.observe("about:srcdoc", "Not a tender")
    obs = agent.book.observe("https://tender.test/notice", "Tender REF-X has positions 01 and 02")
    citation = agent.book.cite(obs, "Tender REF-X has positions 01 and 02", "Tender reference and positions")
    with pytest.raises(ValueError, match="Observe the exact reference"):
        await agent.dispatch("partial_submission", dict(tender_reference="REF-Y",
            omitted_positions=["01", "02"], evidence_ids=[citation]))
    with pytest.raises(ValueError, match="unique"):
        await agent.dispatch("partial_submission", dict(tender_reference="REF-X",
            omitted_positions=["01", "01"], evidence_ids=[citation]))
    with pytest.raises(ValueError, match="each omitted"):
        await agent.dispatch("partial_submission", dict(tender_reference="REF-X",
            omitted_positions=["01", "03"], evidence_ids=[citation]))
    result = await agent.dispatch("partial_submission", dict(tender_reference="REF-X",
        omitted_positions=["01", "02"]))
    assert result["status"] == "partial_bid_authorized"
    agent.reviewer = AsyncMock(return_value={"accepted": True, "reason": "Explicit omissions checked"})
    review = agent.book.observe("https://tender.test/review", "REF-X omitted positions 01 and 02")
    await agent.dispatch("validate_submission", dict(observation_id=review, review_quote="REF-X omitted positions 01 and 02"))
    receipt = agent.book.observe("https://tender.test/receipt", "Bid submitted. Receipt 123.")
    await agent.dispatch("finish", dict(observation_id=receipt, receipt_quote="Bid submitted. Receipt 123."))
    assert agent.done and agent.partial["omitted_positions"] == ["01", "02"]


async def test_partial_submission_rejects_non_tender_evidence(agent):
    obs = agent.book.observe("https://mail.test", "Tender REF-X has positions 01 and 02")
    citation = agent.book.cite(obs, "Tender REF-X", "Copied reference")
    with pytest.raises(ValueError, match="tender-portal"):
        await agent.dispatch("partial_submission", dict(tender_reference="REF-X",
            omitted_positions=["01", "02"], evidence_ids=[citation]))


async def test_finish_rejects_receipt_without_validated_review(agent):
    receipt = agent.book.observe("https://tender.test/receipt", "Bid submitted. Receipt 123.")
    with pytest.raises(ValueError, match="No validated review"):
        await agent.dispatch("finish", dict(observation_id=receipt, receipt_quote="Bid submitted. Receipt 123."))


async def test_calculation_rejects_unknown_evidence_and_schema(agent, bid):
    bid["discount"]["evidence_ids"] = ["invented"]
    with pytest.raises(ValueError, match="Unknown"):
        await agent.dispatch("calculate", bid)
    bid["discount"]["evidence_ids"] = ["ev-1"]
    agent.run["answer_schema"] = {"type": "object", "required": ["not_a_real_field"]}
    import jsonschema
    with pytest.raises(jsonschema.ValidationError):
        await agent.dispatch("calculate", bid)
    assert agent.calculation is None


async def test_loop_recovers_tool_error_and_stops_prepare_only(agent, bid):
    agent.prepare_only = True
    def response(name, args):
        return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}
    model = SimpleNamespace(complete=AsyncMock(side_effect=[response("cite", {
        "observation_id": "missing", "quote": "bad", "meaning": "bad"}), response("calculate", bid)]))
    assert await agent_loop(agent, model, seconds=3) == "prepared"
    assert model.complete.await_count == 2
    assert not agent.browser.act.called


async def test_repeated_browser_error_is_logged_and_guidance_changes(agent, capsys):
    agent.log_secrets = ["private-token"]
    agent.browser.act.side_effect = ValueError("stale control private-token")
    def response(index):
        return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{
            "id": str(index), "type": "function", "function": {"name": "browser",
            "arguments": json.dumps({"operation": "click", "ref": "stale"})}}]}}]}
    model = SimpleNamespace(complete=AsyncMock(side_effect=[response(i) for i in range(3)]))
    with pytest.raises(StopAsyncIteration):
        await agent_loop(agent, model, seconds=3)
    output = capsys.readouterr().out
    assert "private-token" not in output
    assert '"error_type": "ValueError"' in output
    assert '"same_error_count": 3' in output


async def test_loop_deadline_interrupts_pending_model(agent):
    class SlowModel:
        async def complete(self, *_):
            await asyncio.sleep(10)
    with pytest.raises(TimeoutError):
        await agent_loop(agent, SlowModel(), seconds=.01)


async def test_finalization_reserve_changes_model_instruction(agent):
    model = SimpleNamespace(complete=AsyncMock(return_value={"choices": [{"message": {
        "role": "assistant", "content": "Working", "tool_calls": []}}]}))
    with pytest.raises(RuntimeError, match="step limit"):
        await agent_loop(agent, model, seconds=299, max_steps=1)
    messages = model.complete.await_args.args[0]
    instruction = next(message["content"] for message in messages if message.get("role") == "user"
                       and isinstance(message.get("content"), str) and message["content"].startswith("Time remaining:"))
    assert "FINALIZATION NOW" in instruction
    assert "partial_submission" in instruction


async def test_finalization_reserve_does_not_start_early(agent):
    model = SimpleNamespace(complete=AsyncMock(return_value={"choices": [{"message": {
        "role": "assistant", "content": "Working", "tool_calls": []}}]}))
    with pytest.raises(RuntimeError, match="step limit"):
        await agent_loop(agent, model, seconds=902, max_steps=1)
    messages = model.complete.await_args.args[0]
    instruction = next(message["content"] for message in messages if message.get("role") == "user"
                       and isinstance(message.get("content"), str) and message["content"].startswith("Time remaining:"))
    assert "FINALIZATION NOW" not in instruction


async def test_model_proxy_retries_transient_error_and_passes_tools(monkeypatch):
    calls = []
    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": []})
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = ModelClient(client, "https://proxy.test/qwen/v1", "secret")
        assert await model.complete([], tool_definitions()) == {"choices": []}
    assert len(calls) == 2
    assert calls[0].url.path == "/qwen/v1/chat/completions"
    assert calls[0].headers["authorization"] == "Bearer secret"
    assert json.loads(calls[0].content)["parallel_tool_calls"] is False


def test_artifacts_redact_credentials_and_deadline_caps(agent, tmp_path):
    agent.notes.append("Never persist token-123 or password-456")
    save_artifacts(tmp_path, agent, ["token-123", "password-456"])
    stored = (tmp_path / "run.json").read_text()
    assert "token-123" not in stored and "password-456" not in stored
    assert "[REDACTED]" in stored
    run = {"expires_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()}
    assert 20 < run_seconds(run, 1185) <= 25
    with pytest.raises(ValueError, match="expired"):
        run_seconds({"expires_at": "2000-01-01T00:00:00Z"}, 1185)


def test_zip_member_requires_explicit_selection_and_no_extraction():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("../requirements.txt", "Selected test document")
        archive.writestr("other.txt", "Other data")
    payload = output.getvalue()
    assert "Selected test document" not in document_text(payload, "fixture.zip")
    assert document_text(payload, "fixture.zip", "../requirements.txt") == "Selected test document"


async def test_cdp_only_and_action_invalidation():
    chromium = SimpleNamespace(connect_over_cdp=AsyncMock(), launch=AsyncMock())
    with pytest.raises(ValueError, match="one and four"):
        await BrowserSession.connect(SimpleNamespace(chromium=chromium), [], EvidenceBook(), ["https://t.test"])
    with pytest.raises(ValueError, match="local"):
        await BrowserSession.connect(SimpleNamespace(chromium=chromium), ["http://remote.test:9222"], EvidenceBook(), ["https://t.test"])
    chromium.launch.assert_not_called()
    page = SimpleNamespace(url="https://t.test", is_closed=lambda: False, bring_to_front=AsyncMock(), frames=[], main_frame=None)
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[page])])
    page.context = browser.contexts[0]
    session = BrowserSession([browser], EvidenceBook(), ["https://t.test"])
    handle = SimpleNamespace(click=AsyncMock(side_effect=TimeoutError("action may have succeeded")))
    session.controls["c"] = (0, 0, handle)
    with pytest.raises(TimeoutError):
        await session.act("click", ref="c")
    assert not session.controls
    with pytest.raises(ValueError, match="outside"):
        await session.act("navigate", url="https://outside.test")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://u:p@example.test", "javascript:alert(1)"])
def test_navigation_rejects_unsafe_schemes_and_credentials(url):
    with pytest.raises(ValueError):
        origin(url)


def test_context_compaction_preserves_complete_tool_groups():
    messages = [{"role": "system", "content": "instructions"}, {"role": "user", "content": "brief"}]
    for i in range(20):
        messages.extend([{"role": "user", "content": f"Time remaining: {20-i} seconds."},
                         {"role": "assistant", "tool_calls": [{"id": str(i)}]},
                         {"role": "tool", "tool_call_id": str(i), "content": "x" * 200}])
    compacted = compact_messages(messages, limit=2000)
    assert compacted[:2] == messages[:2]
    assert len(compacted) < len(messages)
    calls = {call["id"] for message in compacted for call in message.get("tool_calls", [])}
    results = {message["tool_call_id"] for message in compacted if message["role"] == "tool"}
    assert calls == results


def test_wire_numbers_refuse_loss_of_cents():
    from decimal import Decimal
    assert wire_answer(Decimal("12.34")) == 12.34
    with pytest.raises(ValueError, match="faithfully"):
        wire_answer(Decimal("9007199254740991.99"))


async def test_clef_decide_and_retries(monkeypatch):
    from hackathon_toolkit.rfq.clef import ClefClient
    calls = []
    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"decisions": {"test": {"decision": "retry"}}})
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        clef = ClefClient(client, "https://proxy.test/clef", "secret-token")
        result = await clef.choose({"page": "error"}, "What next?", {"retry": "Retry"})
        assert result == {"decisions": {"test": {"decision": "retry"}}}
        assert len(calls) == 2
        assert calls[0].url.path == "/clef/v1/decide"
        assert calls[0].headers["authorization"] == "Bearer secret-token"
        content = json.loads(calls[0].content)
        assert content["state"] == {"page": "error"}
        assert content["questions"]["choice"]["type"] == "choice"


async def test_agent_decide_tool(agent):
    # When Clef is not set:
    res = await agent.dispatch("decide", {"question_type": "noul", "instructions": "is relevant?"})
    assert res["error"] == "ClefUnavailable"

    # When Clef is set:
    mock_clef = AsyncMock()
    mock_clef.decide.return_value = {"decisions": {"d": {"probability": 0.9}}}
    agent.clef = mock_clef
    agent.browser.act = AsyncMock(return_value={"image_url": "data:image/png;base64,abc"})

    res = await agent.dispatch("decide", {
        "question_type": "noul",
        "instructions": "is relevant?",
        "include_screenshot": True,
        "page": 1,
        "state": {"title": "Spec"},
    })
    assert res == {"decisions": {"d": {"probability": 0.9}}}
    agent.browser.act.assert_called_once_with("screenshot", page=1)
    mock_clef.decide.assert_called_once()
    _, kwargs = mock_clef.decide.call_args
    assert kwargs["state"] == {"title": "Spec"}
    assert kwargs["images"] == ["data:image/png;base64,abc"]
    assert kwargs["questions"]["decision"]["type"] == "noul"


def test_tool_definitions_includes_decide():
    tools = tool_definitions()
    names = [t["function"]["name"] for t in tools]
    assert "decide" in names
