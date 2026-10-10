import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hackathon_toolkit.rfq.evidence import EvidenceBook
from hackathon_toolkit.rfq.runtime import Agent, BrowserWorker, agent_loop, run_research


@pytest.fixture
def parent():
    pages = [SimpleNamespace(index=i) for i in range(4)]
    browser = SimpleNamespace(browsers=pages, page=lambda i: pages[i],
        browser_index=lambda p: p.index, controls={"own": (0, 0, None), "foreign": (1, 0, None)},
        control_info={}, act=AsyncMock(return_value={"ok": True}),
        page_list=lambda: [{"page": i, "browser": i} for i in range(4)])
    book = EvidenceBook()
    obs = book.observe("https://test.invalid", "REF-1 current specification")
    book.cite(obs, "REF-1 current specification", "Synthetic prerequisite")
    agent = Agent(browser, book, {"brief": "Research the bid", "access": [],
        "submission": {"url": "https://test.invalid"}, "answer_schema": {}})
    agent.remaining = 1100
    agent.model = object()
    return agent


def assignment(role, browser):
    return {"role": role, "browser": browser, "task": f"Research {role} on supplied site"}


async def test_parallel_producers_unlock_consumers(parent, monkeypatch):
    started = set()
    producers = asyncio.Event()

    async def loop(worker, model, **kwargs):
        started.add(worker.role)
        if len(started) == 4:
            producers.set()
        await producers.wait()  # All roles must start independent preparation before facts exist.
        if worker.role in {"tender", "specification"}:
            topic = "tender_reference" if worker.role == "tender" else "current_specification"
            await worker.dispatch("publish_fact", {"topic": topic, "text": "REF-1",
                                                    "evidence_ids": ["ev-1"]})
        else:
            topic = "tender_reference" if worker.role == "email" else "current_specification"
            assert "status" not in await worker.dispatch("await_fact", {"topic": topic, "seconds": 1})
            assert topic in worker.team.facts
        return "reported"

    monkeypatch.setattr("hackathon_toolkit.rfq.runtime.agent_loop", loop)
    async with asyncio.timeout(1):
        result = await run_research(parent, [assignment(r, i) for i, r in
            enumerate(["tender", "specification", "erp", "email"])])
    assert len(result["reports"]) == 4
    assert set(result["specialists"].values()) == {"reported"}


async def test_missing_prerequisite_allows_setup_then_reports_missing_fact(parent, monkeypatch):
    seen = []

    async def loop(worker, model, **kwargs):
        seen.append(worker.role)
        if worker.role == "erp":
            result = await worker.dispatch("await_fact", {"topic": "current_specification", "seconds": 1})
            assert result["status"] == "missing_dependency"
        return "reported"

    monkeypatch.setattr("hackathon_toolkit.rfq.runtime.agent_loop", loop)
    async with asyncio.timeout(1):
        result = await run_research(parent, [assignment("specification", 0), assignment("erp", 1)])
    assert seen == ["specification", "erp"]
    assert result["specialists"]["erp"] == "reported"


async def test_cancellation_joins_every_worker(parent, monkeypatch):
    started = set()
    stopped = set()
    ready = asyncio.Event()

    async def loop(worker, model, **kwargs):
        started.add(worker.role)
        if len(started) == 2:
            ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.add(worker.role)

    monkeypatch.setattr("hackathon_toolkit.rfq.runtime.agent_loop", loop)
    task = asyncio.create_task(run_research(parent, [assignment("tender", 0), assignment("specification", 1)]))
    await asyncio.wait_for(ready.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped == started == {"tender", "specification"}
    assert set(parent.team.status.values()) == {"cancelled"}


async def test_conflicting_browser_assignments_fail_before_start(parent):
    with pytest.raises(ValueError, match="exclusive browser"):
        await run_research(parent, [assignment("tender", 0), assignment("email", 0)])
    assert not parent.team.status


async def test_failed_specialist_does_not_cancel_independent_research(parent, monkeypatch):
    async def loop(worker, model, **kwargs):
        if worker.role == "tender":
            raise RuntimeError("Synthetic navigation failure")
        await asyncio.sleep(0)
        return "reported"

    monkeypatch.setattr("hackathon_toolkit.rfq.runtime.agent_loop", loop)
    result = await run_research(parent, [assignment("tender", 0), assignment("specification", 1)])
    assert result["specialists"] == {"tender": "RuntimeError", "specification": "reported"}
    assert len(parent.notes) == 2


async def test_messages_and_versioned_citations(parent):
    spec = BrowserWorker(parent, 0, "Resolve revision", "specification")
    erp = BrowserWorker(parent, 1, "Match material", "erp")
    await spec.dispatch("send_message", {"recipient": "erp", "text": "Check revised dimensions"})
    assert erp.team.inbox("erp")[0]["from"] == "specification"
    with pytest.raises(ValueError, match="Unknown"):
        await spec.dispatch("publish_fact", {"topic": "current_specification", "text": "x", "evidence_ids": ["fake"]})
    for expected in [1, 2]:
        fact = await spec.dispatch("publish_fact", {"topic": "current_specification", "text": "updated", "evidence_ids": ["ev-1"]})
        assert fact["version"] == expected
    assert (await erp.dispatch("await_fact", {"topic": "current_specification"}))["version"] == 2
    with pytest.raises(ValueError, match="Only specification"):
        await erp.dispatch("publish_fact", {"topic": "current_specification", "text": "x", "evidence_ids": ["ev-1"]})


async def test_specialist_prompt_and_capabilities(parent):
    prompts = []
    for role in ["erp", "email"]:
        worker = BrowserWorker(parent, 0, "Assigned task", role)

        async def complete(messages, tools):
            prompts.append(messages[0]["content"])
            names = {t["function"]["name"] for t in tools}
            assert {"send_message", "publish_fact", "request_human"} <= names
            assert not {"calculate", "finish", "research", "validate_submission"} & names
            return {"choices": [{"message": {"role": "assistant", "tool_calls": [{
                "id": "1", "function": {"name": "report", "arguments": json.dumps({"text": "Done"})}}]}}]}

        assert await agent_loop(worker, SimpleNamespace(complete=complete), seconds=2) == "reported"
    assert prompts[0] != prompts[1]
    assert "You are the ERP specialist" in prompts[0]
    assert "You are the email specialist" in prompts[1]
    assert "You are the coordinator" not in prompts[0]


async def test_worker_cannot_use_foreign_fields_screenshots_or_handoff(parent):
    worker = BrowserWorker(parent, 0, "Research", "erp")
    for name, args in [
        ("browser", {"operation": "fill_fields", "fields": [{"ref": "own", "value": "a"}, {"ref": "foreign", "value": "b"}]}),
        ("decide", {"include_screenshot": True, "page": 1}),
        ("request_human", {"page": 1, "reason": "test"}),
    ]:
        with pytest.raises(ValueError, match="another browser"):
            await worker.dispatch(name, args)
    parent.browser.act.assert_not_awaited()


async def test_visual_distraction_recovers_and_only_confirmed_captcha_holds_browser(parent):
    parent.clef = SimpleNamespace(decide=AsyncMock())
    parent.browser.act.return_value = {"image_url": "data:image/png;base64,test"}
    obs = {"page": 0, "text": "Same underlying page", "url": "https://test.invalid", "controls": []}
    for state in ["optional_distraction", "optional_distraction", "optional_distraction"]:
        parent.clef.decide.return_value = {"decisions": {"page_state": {"decision": state}}}
        await parent.visual_check(obs, "Find material")
    assert obs["recovery"]["attempts"] == 3
    assert "stop repeating" in obs["recovery"]["next"]
    parent.clef.decide.return_value = {"decisions": {"page_state": {"decision": "human_verification"}}}
    await parent.visual_check(obs, "Find material")
    assert not parent.waiting_for_human
    assert not parent.team.handoffs
    await parent.dispatch("request_human", {"page": 0, "reason": "Navigator confirms a verification test"})
    assert parent.waiting_for_human
    for args in [{"operation": "click", "ref": "own"}, {"operation": "navigate", "url": "https://test.invalid"},
                 {"operation": "new_tab", "browser": 0}]:
        with pytest.raises(ValueError, match="awaits human"):
            await parent.dispatch("browser", args)
    await parent.dispatch("browser", {"operation": "click", "ref": "foreign"})
    parent.apply_assessment(obs, "other", "Inspect uncertainty")
    assert 0 in parent.team.handoffs
    parent.apply_assessment(obs, "results", "Re-observe after human completion")
    assert not parent.team.handoffs
    assert obs["recovery"]["resume_task"] == "Find material"
    assert parent.clef.decide.await_count == 4


async def test_human_handoff_ends_worker_loop_and_preserves_task(parent):
    worker = BrowserWorker(parent, 0, "Search catalogue for REF-1", "erp")
    model = SimpleNamespace(complete=AsyncMock(return_value={"choices": [{"message": {
        "role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "request_human",
        "arguments": json.dumps({"page": 0, "reason": "Human verification"})}}]}}]}))
    assert await agent_loop(worker, model, seconds=2) == "awaiting_human"
    assert parent.team.handoffs[0]["resume_task"] == worker.task
    assert not parent.done


async def test_false_clef_verification_does_not_end_worker_conversation(parent):
    worker = BrowserWorker(parent, 0, "Find tender reference", "tender")
    worker.clef = SimpleNamespace(decide=AsyncMock(return_value={"answers": {
        "page_state": {"choice": "human_verification"}, "recovery_control": {"choice": "own"}}}))

    async def act(operation, **args):
        if operation == "screenshot":
            return {"image_url": "data:image/png;base64,test"}
        return {"page": 0, "text": "Optional feedback", "active_dialog": "Optional feedback",
                "controls": [{"ref": "own", "text": "Continue"}]}

    worker.browser.act.side_effect = act
    responses = [
        {"name": "browser", "arguments": json.dumps({"operation": "observe", "page": 0})},
        {"name": "report", "arguments": json.dumps({"text": "Ordinary notice; no human verification"})},
    ]
    model = SimpleNamespace(complete=AsyncMock(side_effect=[{"choices": [{"message": {
        "role": "assistant", "tool_calls": [{"id": str(i), "function": response}]}}]}
        for i, response in enumerate(responses)]))
    assert await agent_loop(worker, model, seconds=2) == "reported"
    assert model.complete.await_count == 2
    assert not worker.team.handoffs
    assert any(isinstance(m.get("content"), list) for m in model.complete.call_args.args[0])
    candidates = worker.clef.decide.call_args.kwargs["questions"]["recovery_control"]["criteria"]
    assert set(candidates) == {"none", "own"}


async def test_navigator_can_correct_stale_human_hold_with_fresh_evidence(parent):
    parent.browser.observed_pages = {}
    obs = parent.book.observe("https://test.invalid", "Optional feedback. Continue without responding.")
    parent.browser.observed_pages[obs] = 0
    await parent.dispatch("request_human", {"page": 0, "reason": "Mistaken earlier assessment"})
    review = {"observation_id": obs, "quote": "Optional feedback", "reason": "No challenge is present",
              "disposition": "optional_distraction"}
    await parent.dispatch("review_obstruction", review)
    assert not parent.waiting_for_human and not parent.team.handoffs
    await parent.dispatch("browser", {"operation": "click", "ref": "own"})
    newer = parent.book.observe("https://test.invalid", "Changed page")
    parent.browser.observed_pages[newer] = 0
    with pytest.raises(ValueError, match="Re-observe"):
        await parent.dispatch("review_obstruction", review)


async def test_binding_document_purpose_is_not_bid_signing(parent):
    parent.browser.control_info["own"] = {"text": "Verbindliche Unterlagen", "type": "radio"}
    worker = BrowserWorker(parent, 0, "Open document", "specification")
    await worker.dispatch("browser", {"operation": "click", "ref": "own"})
    parent.browser.act.assert_awaited_once()
    parent.browser.control_info["own"] = {"text": "Verbindlich abgeben", "type": "submit"}
    with pytest.raises(ValueError, match="validate_submission"):
        await worker.dispatch("browser", {"operation": "click", "ref": "own"})


async def test_progress_tracks_evidence_and_invalidates_derived_milestones(parent):
    progress = parent.team.progress
    assert progress.snapshot()["remaining_count"] == 10
    await parent.dispatch("publish_fact", {"topic": "tender_reference", "text": "REF-1", "evidence_ids": ["ev-1"]})
    assert progress.snapshot()["completed"] == 0  # The position inventory is still missing.
    await parent.dispatch("publish_fact", {"topic": "tender_positions", "text": "All positions", "evidence_ids": ["ev-1"]})
    assert progress.snapshot()["completed"] == 1
    progress.mark("calculation")
    progress.mark("review")
    await parent.dispatch("publish_fact", {"topic": "tender_positions", "text": "Corrected positions", "evidence_ids": ["ev-1"]})
    assert progress.snapshot()["completed"] == 1
    assert progress.snapshot()["milestones"]["review"]["status"] == "pending"


async def test_waiting_activity_is_visible_and_resumes_after_fact(parent):
    worker = BrowserWorker(parent, 0, "Search ERP", "erp")
    waiting = asyncio.create_task(worker.dispatch("await_fact", {"topic": "current_specification", "seconds": 1}))
    await asyncio.sleep(0)
    assert parent.team.progress.snapshot()["agents"]["erp"]["state"] == "waiting_for_dependency"
    await parent.dispatch("publish_fact", {"topic": "current_specification", "text": "Requirement", "evidence_ids": ["ev-1"]})
    await waiting
    assert parent.team.progress.snapshot()["agents"]["erp"]["state"] == "running"


async def test_record_progress_requires_observation_and_submission_validation(parent):
    obs = parent.book.observe("https://test.invalid", "A signing code has been requested")
    args = {"milestone": "tan_requested", "observation_id": obs, "quote": "A signing code has been requested"}
    with pytest.raises(ValueError, match="Validate the review"):
        await parent.dispatch("record_progress", args)
    parent.validation = {"verdict": {"accepted": True}}
    result = await parent.dispatch("record_progress", args)
    assert result["milestones"]["tan_requested"]["status"] == "completed"
    with pytest.raises(ValueError, match="exact observed quote"):
        await parent.dispatch("record_progress", {**args, "quote": "Receipt confirmed"})
    with pytest.raises(ValueError, match="runtime validation"):
        await parent.dispatch("record_progress", {**args, "milestone": "receipt"})


async def test_clef_does_not_recommend_dismissal_controls_on_normal_pages(parent):
    parent.clef = SimpleNamespace(decide=AsyncMock(return_value={"answers": {"page_state": {"choice": "form"}}}))
    parent.browser.act.return_value = {"image_url": "data:image/png;base64,test"}
    await parent.visual_check({"page": 0, "text": "Pricing form", "controls": [{"ref": "own", "text": "Save"}]}, "Read")
    assert "recovery_control" not in parent.clef.decide.call_args.kwargs["questions"]
    assert parent.team.progress.metrics["clef_calls"] == 1
    assert parent.team.progress.metrics["recovery_suggestions"] == 0


def test_progress_artifacts_include_pending_agents_and_escape_page_content(parent, tmp_path):
    from hackathon_toolkit.rfq.trace import Trace
    trace = Trace(tmp_path, [])
    trace.progress = parent.team.progress
    trace.progress.active("email", "waiting_for_dependency", topic="<script>test</script>")
    trace.update_progress()
    data = json.loads((tmp_path / "progress.json").read_text())
    assert data["remaining_count"] == 10
    html = (tmp_path / "browsers.html").read_text()
    assert "10 remaining" in html and "waiting_for_dependency" in html
    assert "<script>" not in html
