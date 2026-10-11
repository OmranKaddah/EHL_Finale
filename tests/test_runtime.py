from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from atira_agent.browser import BrowserSession
from atira_agent.config import Config
from atira_agent.contracts import RunContext
from atira_agent.runtime import Deadline, load_run
from atira_agent.telemetry import Redactor


def run_data():
    return dict(challenge_id="rfq", brief="Synthetic task", access=[dict(siteId="site", url="http://127.0.0.1:9000",
        credentials={"username": "synthetic-user", "password": "synthetic-password"})],
        submission={"kind": "site", "siteId": "site", "url": "http://127.0.0.1:9000"}, answer_schema={})


def env():
    return {"QWEN_BASE_URL": "http://127.0.0.1:8765/qwen/v1", "QWEN_API_KEY": "local"}


def test_local_config():
    config = Config.from_env(env())
    assert not config.sandbox and not config.cdp_urls and config.provider == "qwen"


@pytest.mark.parametrize("update", [
    {"CHALLENGE_RUN_TOKEN": "fake-token"}, {"CDP_URLS": "bad-json"}, {"CDP_URLS": '"string"'},
    {"CDP_URLS": '["http://external.test:9222"]'}, {"ATIRA_MODEL_PROVIDER": "openai"},
    {"QWEN_BASE_URL": "https://outside.test/v1"}, {"ATIRA_SUBMISSION_RESERVE": "1200"},
])
def test_invalid_configuration_fails(update):
    with pytest.raises(ValueError):
        Config.from_env(env() | update)


def test_paid_key_alone_does_not_activate():
    assert Config.from_env(env() | {"OPENAI_API_KEY": "fake", "OPENAI_BASE_URL": "https://api.openai.com/v1"}).provider == "qwen"


def test_hybrid_provider_routes_only_to_configured_atira_proxy_models():
    hybrid = env() | {
        "ATIRA_MODEL_PROVIDER": "hybrid", "ATIRA_ALLOW_PAID": "1",
        "OPENAI_BASE_URL": "http://127.0.0.1:8765/openai/v1", "OPENAI_API_KEY": "openai-local",
        "ATIRA_OPENAI_MODEL": "approved-openai-model",
    }
    config = Config.from_env(hybrid)
    assert config.for_role("erp").provider == "qwen"
    assert config.for_role("tender").provider == "openai"
    assert config.for_role("submission").model == "approved-openai-model"


def test_hybrid_rejects_an_unproxied_openai_endpoint():
    hybrid = env() | {
        "ATIRA_MODEL_PROVIDER": "hybrid", "ATIRA_ALLOW_PAID": "1",
        "OPENAI_BASE_URL": "https://api.openai.com/v1", "OPENAI_API_KEY": "key",
        "ATIRA_OPENAI_MODEL": "approved-openai-model",
    }
    with pytest.raises(ValueError, match="localhost"):
        Config.from_env(hybrid)


async def test_run_loader_uses_header_agent_and_retries():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(503 if len(requests) == 1 else 200, json=run_data())
    with patch("atira_agent.runtime.asyncio.sleep", new=AsyncMock()):
        result = await load_run({"CHALLENGE_RUN_TOKEN": "synthetic-token", "CHALLENGE_API_URL": "https://platform.test"},
                                httpx.MockTransport(handler))
    assert result.challenge_id == "rfq"
    assert len(requests) == 2
    assert requests[0].headers["x-api-key"] == "synthetic-token"
    assert "ehl-atira" in requests[0].headers["user-agent"]


async def test_scouting_expiry_is_not_execution_budget():
    data = run_data() | {"expires_at": 1}
    result = await load_run({"CHALLENGE_SCOUTING": json.dumps(data)})
    assert result.expires_at == 1
    deadline = Deadline(1200, 180, None)
    assert deadline.remaining > 1199


def test_deadlines():
    deadline = Deadline(1200, 180, int((time.time() + 90) * 1000))
    assert deadline.submission_due
    assert 89 < deadline.remaining <= 90
    with pytest.raises(TimeoutError):
        deadline.timeout(10, investigation=True)


async def test_sandbox_connects_without_launch(telemetry):
    config = Config(True, ("http://127.0.0.1:9222",), "qwen", "qwen", "http://proxy", "secret")
    context = MagicMock()
    context.pages = [MagicMock()]
    context.route = AsyncMock()
    context.unroute = AsyncMock()
    browser = MagicMock(contexts=[context])
    chromium = MagicMock(connect_over_cdp=AsyncMock(return_value=browser), launch=AsyncMock())
    playwright = MagicMock(chromium=chromium, stop=AsyncMock())
    with patch("atira_agent.browser.async_playwright") as factory:
        factory.return_value.start = AsyncMock(return_value=playwright)
        session = BrowserSession(config, RunContext.model_validate(run_data()), telemetry)
        await session.start()
        chromium.connect_over_cdp.assert_awaited_once()
        chromium.launch.assert_not_awaited()
        await session.close()


def test_redaction_covers_nested_values_and_token_urls():
    redactor = Redactor(["secret-value", "scout-password"])
    result = redactor.clean({"password": "other", "message": "Password: scout-password; TAN: 123456",
                             "url": "https://platform.test/llm/run/secret-value/qwen/v1", "nested": ["secret-value"]})
    text = json.dumps(result)
    assert "secret-value" not in text and "scout-password" not in text and "123456" not in text
    assert "other" not in text
    assert redactor.clean({"secret": "test-site:password"}) == {"secret": "test-site:password"}
    assert redactor.clean({"headers": {"X-Api-Key": "unseen"}}) == {"headers": "[REDACTED]"}
    assert "unseen" not in redactor.text("Bearer unseen.token.signature")


def test_citation_must_exist_and_record_needs_evidence(ledger):
    with pytest.raises(ValueError):
        ledger.cite("fixture", "fabricated fact")
    with pytest.raises(ValueError):
        ledger.record("revision", dict(id="bad", evidence=["invented"], revision="R", current=True, full=True))
    with pytest.raises(ValueError):
        ledger.record("revision", dict(id="bad", evidence=[], revision="R", current=True, full=True))


def test_control_reference_citation_retains_exact_quote_requirement(ledger):
    observation = ledger.observations["fixture"].model_copy(update={"id": "o5"})
    ledger.observe(observation)
    fact = ledger.cite("o5-f0-e12", "Synthetic records explicitly supplied for testing.")
    assert fact.observation_id == "o5"
    with pytest.raises(ValueError, match="exact visible excerpt"):
        ledger.cite("o5-f0-e12", "invented quote")


def test_telemetry_file_is_redacted(telemetry):
    telemetry.redactor.add("never-log-me")
    telemetry.emit("tool_call", arguments={"password": "never-log-me"}, message="never-log-me")
    assert "never-log-me" not in (telemetry.trace_dir / "events.jsonl").read_text()


def test_rejected_records_stay_outside_pricing_until_corrected(ledger):
    data = {"id": "q", "evidence": ["e1"], "quantity": 9}
    ledger.reject("qa", data, "issued_at missing")
    assert ledger.all("qa") == []
    assert ledger.summary()["rejected_records"][0]["data"] == data
    ledger.record("qa", data | {"issued_at": "2026-01-01T00:00:00Z"})
    assert ledger.summary()["rejected_records"] == []
    assert len(ledger.all("qa")) == 1


def test_model_context_bounds_old_evidence_but_keeps_the_full_record_set(ledger):
    for index in range(30):
        ledger.cite("fixture", "Synthetic records explicitly supplied for testing.", {"n": str(index)})
    context = ledger.model_context(max_evidence=5)
    assert len(context["evidence"]) == 5
    assert context["evidence"][0]["scope"] == {"n": "25"}
