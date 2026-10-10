from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import json
import pytest

from hackathon_toolkit.rfq.evidence import EvidenceBook
from hackathon_toolkit.rfq.runtime import Agent, BrowserWorker, ModelClient
from hackathon_toolkit.rfq.validation import check_answer
from hackathon_toolkit.rfq.trace import Trace


@pytest.fixture
def agent():
    book = EvidenceBook()
    browser = SimpleNamespace(act=AsyncMock(), control_info={"sign": {"text": "Angebot signieren"}})
    agent = Agent(browser, book, {"submission": {"url": "https://portal.test"}, "answer_schema": {}})
    agent.partial = {"tender_reference": "TEST-REF", "omitted_positions": ["A", "B"]}
    agent.reviewer = AsyncMock(return_value={"accepted": True, "reason": "Review matches omissions"})
    return agent


async def validate(agent, text="Review TEST-REF: omitted A, B"):
    obs = agent.book.observe("https://portal.test/review", text)
    return await agent.dispatch("validate_submission", {"observation_id": obs, "review_quote": text})


async def test_signing_is_blocked_until_review(agent):
    with pytest.raises(ValueError, match="validate_submission"):
        await agent.dispatch("browser", {"operation": "click", "ref": "sign"})
    agent.browser.act.assert_not_awaited()
    await validate(agent)
    await agent.dispatch("browser", {"operation": "click", "ref": "sign"})
    assert agent.phase == "signing"


async def test_wrong_reference_and_missing_omission_are_rejected(agent):
    with pytest.raises(ValueError, match="exact tender reference"):
        await validate(agent, "Review WRONG-REF")
    agent.reviewer.assert_not_awaited()
    agent.reviewer.return_value = {"accepted": False, "reason": "B has not been omitted"}
    with pytest.raises(ValueError, match="B has not been omitted"):
        await validate(agent, "Review TEST-REF: omitted A")
    assert agent.validation is None


async def test_saved_draft_is_not_receipt(agent):
    await validate(agent)
    agent.reviewer.return_value = {"accepted": False, "reason": "Only draft saved"}
    obs = agent.book.observe("https://portal.test", "TEST-REF draft saved")
    with pytest.raises(ValueError, match="Only draft saved"):
        await agent.dispatch("finish", {"observation_id": obs, "receipt_quote": "TEST-REF draft saved"})
    assert not agent.done


async def test_edit_after_review_invalidates_gate(agent):
    await validate(agent)
    agent.browser.act.return_value = {"url": "https://portal.test/edit"}
    await agent.dispatch("browser", {"operation": "fill", "ref": "quantity", "value": "5"})
    assert agent.validation is None


async def test_login_and_submission_entry_do_not_require_signing_gate(agent):
    for label in ["Sign in", "Submit login", "Angebot abgeben"]:
        agent.browser.control_info["entry"] = {"text": label}
        await agent.dispatch("browser", {"operation": "click", "ref": "entry"})
    assert agent.browser.act.await_count == 3


async def test_tan_batch_preserves_gate_but_mixed_business_edits_invalidate(agent):
    agent.browser.control_info["tan"] = {"label": "Signing TAN", "name": "tan"}
    agent.browser.control_info["amount"] = {"label": "Total net"}
    agent.browser.act.return_value = {"url": "https://portal.test/sign"}
    await validate(agent)
    await agent.dispatch("browser", {"operation": "fill_fields", "fields": [{"ref": "tan", "value": "123456"}]})
    assert agent.validation is not None
    await agent.dispatch("browser", {"operation": "fill_fields", "fields": [
        {"ref": "tan", "value": "123456"}, {"ref": "amount", "value": "10"}]})
    assert agent.validation is None


def test_independent_total_catches_inconsistent_answer():
    with pytest.raises(ValueError, match="total disagrees"):
        check_answer({"decision": "bid", "positions": [{"position": "A", "quantity": 3, "unit_price": "1.01"}],
                      "total_net": "3.04"}, {})


async def test_receipt_reviewer_rejects_non_boolean_verdict():
    model = ModelClient(None, "https://model.test", "test")
    model.complete = AsyncMock(return_value={"choices": [{"message": {"content": '{"accepted":"false","reason":"draft"}'}}]})
    with pytest.raises(ValueError, match="Invalid independent"):
        await model.review("receipt", {"text": "draft"}, {})


async def test_reviewer_request_omits_empty_tool_configuration():
    async def handler(request):
        body = json.loads(request.content)
        assert not {"tools", "tool_choice", "parallel_tool_calls"} & body.keys()
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"accepted":false,"reason":"Only a draft"}'}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verdict = await ModelClient(client, "https://model.test", "test").review("receipt", {"text": "draft"}, {})
        assert verdict == {"accepted": False, "reason": "Only a draft"}


def test_trace_redacts_fill_values_and_tokens(tmp_path):
    trace = Trace(tmp_path, ["secret-token"])
    trace.event(arguments={"fields": [{"ref": "x", "value": "123456"}]}, url="https://proxy/secret-token")
    text = (tmp_path / "actions.jsonl").read_text()
    assert "123456" not in text and "secret-token" not in text


async def test_worker_is_confined_and_cannot_submit(agent):
    page = object()
    agent.browser.browsers = [object(), object()]
    agent.browser.controls = {}
    agent.browser.page_list = lambda: [{"page": 0, "browser": 0}, {"page": 1, "browser": 1}]
    agent.browser.page = lambda index: page
    agent.browser.browser_index = lambda _: 1
    worker = BrowserWorker(agent, 0, "Find the selected specification")
    with pytest.raises(ValueError, match="another browser"):
        await worker.dispatch("browser", {"operation": "observe", "page": 1})
    with pytest.raises(ValueError, match="gather evidence only"):
        await worker.dispatch("finish", {})


async def test_automatic_clef_visual_checks_reassess_same_text_and_are_advisory(agent):
    agent.clef = SimpleNamespace(decide=AsyncMock(return_value={"answers": {"page_state": {"choice": "form"}}}))
    agent.browser.act.return_value = {"image_url": "data:image/png;base64,test"}
    observation = {"page": 0, "browser": 0, "url": "https://portal.test", "text": "Review", "controls": []}
    await agent.visual_check(observation, "Inspect review")
    await agent.visual_check(dict(observation), "Inspect same review")
    assert agent.clef.decide.await_count == 2
    assert observation["visual_assessment"]["answers"]["page_state"]["choice"] == "form"
    assert agent.validation is None
    agent.clef.decide.side_effect = TimeoutError()
    observation["text"] = "Changed page"
    await agent.visual_check(observation, "Inspect changed state")
    assert observation["visual_assessment"]["unavailable"] == "TimeoutError"
