"""Decode local events and chunked Atira CLI log exports without executing their contents."""
from __future__ import annotations

import json
from pathlib import Path


def read_events(path: Path) -> list[dict]:
    raw = path.read_bytes()
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    text = raw.decode(encoding, errors="replace")
    events = []
    buffers: dict[str, str] = {}
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if "event" in row:
            events.append(row)
        elif isinstance(row.get("text"), str):
            stream = row.get("stream", "stdout")
            buffers[stream] = buffers.get(stream, "") + row["text"]
            while "\n" in buffers[stream]:
                complete, buffers[stream] = buffers[stream].split("\n", 1)
                try:
                    event = json.loads(complete)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and "event" in event:
                    events.append(event)
            # A corrupt/unfinished output line must not consume unbounded memory.
            if len(buffers[stream]) > 2_000_000:
                buffers[stream] = ""
    return events
