import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from atira_agent.browser import BrowserSession, origin
from atira_agent.config import Config
from atira_agent.contracts import RunContext
from atira_agent.dashboard import Dashboard
from atira_agent.multi_agent import (
    ROLE_ORDER,
    MultiAgentCoordinator,
    Specialist,
    assign_sites,
    benchmark_schedule,
)
from atira_agent.orchestrator import Orchestrator, compact_model_result
from atira_agent.popup_classifier import PopupClassifier
from atira_agent.telemetry import Redactor, Telemetry


class Site:
    def __init__(self, name):
        self.siteId = name
        self.url = f"https://{name}.example.test"


def test_runtime_site_assignment_uses_metadata_and_stays_one_to_one():
    assigned = assign_sites([Site("mailbox"), Site("erp"), Site("customer-spec"), Site("tender-portal")])
    assert assigned == {"tender": "tender-portal", "specifications": "customer-spec", "erp": "erp", "mail": "mailbox"}
    assert len(set(assigned.values())) == 4


def test_dependency_aware_benchmark_beats_sequential_baseline():
    result = benchmark_schedule()
    assert result["dependency_aware_parallel_seconds"] < result["sequential_seconds"]
    assert result["saved_seconds"] > 0


def test_research_focus_targets_only_a_known_specialist():
    # The runtime role names form a closed interface for CLI focus runs.
    assert set(("tender", "specifications", "erp", "mail")) == set(ROLE_ORDER)


def test_popup_classifier_only_runs_for_probable_blockers():
    class Observation:
        controls = []
        text = "Normal ERP material record"

    assert not PopupClassifier.needed(Observation())
    Observation.text = "Cookie consent overlay"
    assert PopupClassifier.needed(Observation())


async def test_clef_is_disabled_after_a_permanent_endpoint_error(telemetry):
    class Failure(Exception):
        status_code = 404

    class Completions:
        async def create(self, **_kwargs):
            raise Failure()

    class Chat:
        def __init__(self):
            self.completions = Completions()

    class Client:
        def __init__(self):
            self.chat = Chat()

        async def close(self):
            return None

    class Observation:
        id = "o1"
        controls = [{"inside_modal": True}]
        text = "Cookie notice"

    classifier = PopupClassifier(Config(False, (), "qwen", "qwen", "http://localhost", "local",
                                       clef_url="http://localhost", clef_key="local"), telemetry)
    classifier.client = Client()
    assert await classifier.classify("ZmFrZQ==", Observation()) is None
    assert classifier.client is None
    assert classifier.disabled_reason == "HTTP 404"


def test_verification_gate_is_classified_without_a_visual_model_call():
    class Observation:
        controls = []
        text = "Zum Entsperren ganz nach rechts ziehen — Ich bin kein Roboter"
        id = "o7"

    assert PopupClassifier.verification_gate(Observation())
    assert not PopupClassifier.needed(Observation())


async def test_multi_dashboard_serves_each_agent_state(tmp_path):
    root = Telemetry(tmp_path / "root", Redactor(), console=False)
    tender = Telemetry(tmp_path / "tender", root.redactor, console=False, agent="tender")
    dashboard = Dashboard([root, tender], port=0)
    try:
        port = await dashboard.start()
        tender.emit("stage_changed", stage="investigating", remaining=900)
        async with httpx.AsyncClient() as client:
            state = (await client.get(f"http://127.0.0.1:{port}/state")).json()
            assert state["agents"]["tender"]["stage"] == "investigating"
            assert (await client.get(f"http://127.0.0.1:{port}/artifact/tender/missing.png")).status_code == 404
    finally:
        await dashboard.close()
        root.close()
        tender.close()


def test_failure_fallback_reuses_a_supplied_browser_without_launching(telemetry):
    run = RunContext(challenge_id="rfq", brief="fixture", access=[
        {"siteId": "tender", "url": "https://tender.test", "credentials": {"username": "t-user"}},
        {"siteId": "mail", "url": "https://mail.test", "credentials": {"password": "m-pass"}},
    ], submission={"kind": "site", "url": "https://tender.test"}, answer_schema={})
    browser = BrowserSession(Config(False, (), "qwen", "qwen", "http://localhost", "local"), run, telemetry,
                             assigned_site="tender", allow_submission=True)
    assert origin("https://mail.test") not in browser.allowed
    browser.expand_to_run_access()
    assert origin("https://mail.test") in browser.allowed
    assert "mail:password" in browser.secret_values


def test_research_only_blocks_the_runtime_declared_submission_path(telemetry):
    run = RunContext(challenge_id="rfq", brief="fixture", access=[],
                     submission={"kind": "site", "url": "https://tender.test/bid"}, answer_schema={})
    controller = Orchestrator(run, Config(False, (), "qwen", "qwen", "http://localhost", "local"), None,
                              None, telemetry, None, research_only=True)
    controller.observation = type("Observation", (), {"url": "https://tender.test/list", "controls": [
        {"ref": "o1-f0-e1", "href": "https://tender.test/bid"}
    ]})()
    assert controller._targets_submission("navigate", {"url": "/bid"})
    assert controller._targets_submission("click", {"ref": "o1-f0-e1"})
    assert not controller._targets_submission("navigate", {"url": "/questions"})
    assert not controller._targets_submission("navigate", {"url": "https://tender.test"})


async def test_schema_without_a_kind_fails_with_a_recoverable_action_error(telemetry):
    run = RunContext(challenge_id="rfq", brief="fixture", access=[],
                     submission={"kind": "site", "url": "https://tender.test"}, answer_schema={})
    controller = Orchestrator(run, Config(False, (), "qwen", "qwen", "http://localhost", "local"), None,
                              None, telemetry, None)
    with pytest.raises(ValueError, match="schema requires kind"):
        await controller.execute(type("Action", (), {"action": "schema", "args": {}})())


async def test_research_workers_release_the_submission_reserve(telemetry):
    class ReserveDeadline:
        remaining = 180
        submission_due = True

    run = RunContext(challenge_id="rfq", brief="fixture", access=[],
                     submission={"kind": "site", "url": "https://tender.test"}, answer_schema={})
    controller = Orchestrator(run, Config(False, (), "qwen", "qwen", "http://localhost", "local"), None,
                              None, telemetry, ReserveDeadline(), research_only=True)
    controller.stop_at_submission_reserve = True

    assert await controller.run_loop(max_steps=10)
    trace = (telemetry.trace_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "submission reserve reached" in trace


async def test_persistent_blank_tab_recovers_to_its_runtime_site(telemetry):
    class Page:
        def __init__(self):
            self.url = "about:blank"
            self.calls = []

        def is_closed(self):
            return False

        async def goto(self, url, **kwargs):
            self.calls.append((url, kwargs))
            self.url = url

    run = RunContext(challenge_id="rfq", brief="fixture", access=[
        {"siteId": "mail", "url": "https://mail.example.test"},
    ], submission={"kind": "site", "url": "https://mail.example.test"}, answer_schema={})
    browser = BrowserSession(Config(False, (), "qwen", "qwen", "http://localhost", "local"), run, telemetry,
                             assigned_site="mail")
    page = Page()
    browser.pages = [page]
    browser.blank_page_since = time.monotonic() - 41

    await browser._recover_persistent_blank_page()

    assert page.calls == [("https://mail.example.test", {"wait_until": "domcontentloaded", "timeout": 15000})]
    trace = (telemetry.trace_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "persistent_about_blank" in trace


def test_research_prompt_is_scoped_to_the_assigned_site_and_compacts_large_results(telemetry):
    class Deadline:
        remaining = 500
        reserve = 180
        submission_due = False

    run = RunContext(challenge_id="rfq", brief="fixture", access=[
        {"siteId": "tender", "url": "https://tender.example.test", "credentials": {"password": "t"}},
        {"siteId": "mail", "url": "https://mail.example.test", "credentials": {"password": "m"}},
    ], submission={"kind": "site", "url": "https://tender.example.test/submit"},
       answer_schema={"secretly_large": "schema"})
    browser = SimpleNamespace(assigned_site="mail", scope_expanded=False, last_image=None)
    controller = Orchestrator(run, Config(False, (), "qwen", "qwen", "http://localhost", "local"), browser,
                              None, telemetry, Deadline(), research_only=True)
    controller.history.append({"result": compact_model_result("x" * 5000)})

    message = controller.messages()[1]["content"][0]["text"]
    context = json.loads(message)

    assert context["sites"] == [{"id": "mail", "url": "https://mail.example.test", "credential_handles": ["mail:password"]}]
    assert context["submission_target"] is None
    assert context["answer_schema"] == {}
    assert context["recent_actions_and_results"][0]["result"]["truncated"]


async def test_second_specialist_failure_starts_recovery_before_slow_workers_finish(telemetry):
    class Deadline:
        remaining = 500
        submission_due = False

    class Browser:
        def __init__(self):
            self.expanded = False

        def expand_to_run_access(self):
            self.expanded = True

    class Controller:
        def __init__(self, result, delay):
            self.result, self.delay = result, delay
            self.stop_at_submission_reserve = False
            self.role_instruction = "normal"
            self.calls = []

        async def run_loop(self, max_steps):
            self.calls.append(max_steps)
            if max_steps == 48:
                assert not erp_done.is_set()
                recovery_started.set()
                return True
            await asyncio.sleep(self.delay)
            if self.result and self.delay == 0.2:
                erp_done.set()
            return self.result

    run = RunContext(challenge_id="rfq", brief="fixture", access=[
        {"siteId": role, "url": f"https://{role}.example.test"} for role in ROLE_ORDER
    ], submission={"kind": "site", "url": "https://tender.example.test"}, answer_schema={})
    coordinator = MultiAgentCoordinator(run, Config(False, (), "qwen", "qwen", "http://localhost", "local"),
                                        Deadline(), telemetry, telemetry.trace_dir)
    recovery_started, erp_done = asyncio.Event(), asyncio.Event()
    for role, result, delay in (("tender", False, 0.01), ("specifications", False, 0.02),
                                ("erp", True, 0.2), ("mail", True, 0.2)):
        browser = Browser()
        coordinator.specialists[role] = Specialist(role, role, browser, None, None, telemetry,
                                                    Controller(result, delay))

    failures = await coordinator.investigate_roles(steps=8, stop_at_submission_reserve=True)

    assert failures == ["tender", "specifications"]
    assert recovery_started.is_set()
    assert coordinator.specialists["tender"].browser.expanded
