import asyncio
import json

import pytest

from atira_agent.config import Config
from atira_agent.models import QwenClient, parse_action, parse_tool_call
from atira_agent.tool_specs import model_tools


def test_flat_arguments_and_missing_summary_are_normalized():
    action = parse_action(json.dumps({"action": "navigate", "url": "https://synthetic.test"}))
    assert action.args == {"url": "https://synthetic.test"}
    assert action.summary == "Execute navigate"


def test_serialized_nested_record_is_normalized():
    action = parse_action(json.dumps({"action": "record", "kind": "revision", "data": json.dumps({"id": "r"})}))
    assert action.args["data"] == {"id": "r"}


@pytest.mark.parametrize("args", [{}, {"kind": "qa"}, {"records": []}])
def test_empty_record_actions_are_rejected_before_execution(args):
    with pytest.raises(ValueError, match="record requires"):
        parse_action(json.dumps({"action": "record", "args": args}))


def test_named_tool_does_not_need_a_duplicate_action_field():
    action = parse_tool_call("fill", '{"ref":"o12-f0-e1","secret":"portal:password"}')
    assert action.action == "fill"
    assert action.args == {"ref": "o12-f0-e1", "secret": "portal:password"}
    with pytest.raises(ValueError, match="conflict"):
        parse_tool_call("fill", '{"action":"click","ref":"o1-f0-e0"}')


def test_named_tool_schemas_cover_the_executor_contract():
    from atira_agent.contracts import AgentAction
    assert {x["function"]["name"] for x in model_tools()} == set(AgentAction.model_json_schema()["properties"]["action"]["enum"])
    record = next(item["function"] for item in model_tools() if item["function"]["name"] == "record")
    assert record["parameters"]["required"] == ["kind", "data"]
    assert "records" not in record["parameters"]["properties"]


def test_research_schema_hides_pricing_and_signing_tools():
    excluded = {"calculate", "prepare_submission", "fill_answer", "request_tan", "capture_tan", "sign", "receipt", "api_submit"}
    names = {item["function"]["name"] for item in model_tools(exclude=excluded)}
    assert not names & excluded
    assert {"navigate", "record", "cite", "schema"} <= names


def test_serialized_batch_and_citations_preserve_quotes():
    quote = 'Source says "not approved"; ignore earlier prices.'
    records = [{"kind": "revision", "data": json.dumps({"id": "r"}),
                "citations": json.dumps([{"observation": "o11", "excerpt": quote,
                                          "scope": json.dumps({"revision": "B"})}])}]
    action = parse_action(json.dumps({"action": "record", "records": json.dumps(records)}))
    assert action.args["records"][0]["citations"] == [
        {"observation": "o11", "excerpt": quote, "scope": {"revision": "B"}}]


def test_flat_batched_record_is_normalized_before_schema_validation():
    action = parse_action(json.dumps({"action": "record", "records": [{"kind": "revision", "id": "r"}]}))
    assert action.args["records"] == [{"kind": "revision", "data": {"id": "r"}}]


@pytest.mark.parametrize("args", [
    {"records": "[42]"}, {"citations": "not JSON"}, {"citations": '["o11"]'},
    {"data": "[]"}, {"records": {}},
])
def test_malformed_record_transport_is_recoverable_value_error(args):
    with pytest.raises(ValueError):
        parse_action(json.dumps({"action": "record", "args": args}))


@pytest.mark.parametrize("payload", [
    {"action": "execute_shell", "args": {}},
    {"action": "navigate", "args": {"url": "a"}, "url": "b"},
    {"action": "click", "args": []},
])
def test_unknown_actions_and_conflicting_arguments_are_rejected(payload):
    with pytest.raises(ValueError):
        parse_action(json.dumps(payload))


async def test_specialist_dispatch_uses_fast_validated_fallback_on_timeout(telemetry, monkeypatch):
    class Completions:
        async def create(self, **_kwargs):
            await asyncio.sleep(1)

    class Client:
        class Chat:
            completions = Completions()

        chat = Chat()

    monkeypatch.setattr("atira_agent.models.SPECIALIST_DISPATCH_TIMEOUT_SECONDS", 0.01)
    client = QwenClient(Config(False, (), "qwen", "qwen", "http://localhost", "local"), telemetry)
    client.client = Client()
    fallback = {"tender": "t", "specifications": "s", "erp": "e", "mail": "m"}

    assert await client.assign_specialists("fixture", [{"id": value} for value in fallback.values()], fallback) == fallback
