import httpx
import pytest

from atira_agent.browser import BrowserSession, origin
from atira_agent.config import Config
from atira_agent.contracts import RunContext
from atira_agent.dashboard import Dashboard
from atira_agent.multi_agent import ROLE_ORDER, assign_sites, benchmark_schedule
from atira_agent.orchestrator import Orchestrator
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
