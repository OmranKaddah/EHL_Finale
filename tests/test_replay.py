import json

import pytest

from atira_agent.replay import read_events


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
def test_cli_chunks_and_interleaved_stderr_are_reassembled(tmp_path, encoding):
    event = {"event": "tool_error", "error": "synthetic layout changed", "elapsed": 1.25}
    line = json.dumps(event) + "\n"
    chunks = [
        {"stream": "stdout", "text": line[:20]},
        {"stream": "stderr", "text": "unstructured diagnostic\n"},
        {"stream": "stdout", "text": line[20:] + json.dumps({"event": "run_failed"}) + "\n"},
    ]
    path = tmp_path / "logs.jsonl"
    path.write_text("\n".join(map(json.dumps, chunks)), encoding=encoding)
    assert read_events(path) == [event, {"event": "run_failed"}]


def test_local_events_skip_incomplete_tail(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"event":"stage_changed"}\n{unfinished', encoding="utf-8")
    assert read_events(path) == [{"event": "stage_changed"}]
