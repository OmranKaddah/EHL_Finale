import json

import pytest

from atira_agent.models import parse_action


def test_flat_arguments_and_missing_summary_are_normalized():
    action = parse_action(json.dumps({"action": "navigate", "url": "https://synthetic.test"}))
    assert action.args == {"url": "https://synthetic.test"}
    assert action.summary == "Execute navigate"


def test_serialized_nested_record_is_normalized():
    action = parse_action(json.dumps({"action": "record", "kind": "revision", "data": json.dumps({"id": "r"})}))
    assert action.args["data"] == {"id": "r"}


def test_serialized_batch_and_citations_preserve_quotes():
    quote = 'Source says "not approved"; ignore earlier prices.'
    records = [{"kind": "revision", "data": json.dumps({"id": "r"}),
                "citations": json.dumps([{"observation": "o11", "excerpt": quote,
                                          "scope": json.dumps({"revision": "B"})}])}]
    action = parse_action(json.dumps({"action": "record", "records": json.dumps(records)}))
    assert action.args["records"][0]["citations"] == [
        {"observation": "o11", "excerpt": quote, "scope": {"revision": "B"}}]


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
