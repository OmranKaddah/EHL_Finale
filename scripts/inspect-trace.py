from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from atira_agent.replay import read_events

parser = argparse.ArgumentParser(description="Summarize a redacted Atira JSONL trace")
parser.add_argument("trace", type=Path)
parser.add_argument("--tail", type=int, default=30)
args = parser.parse_args()
path = args.trace / "events.jsonl" if args.trace.is_dir() else args.trace
events = read_events(path)
print(json.dumps({"events": len(events), "counts": dict(Counter(x["event"] for x in events))}, indent=2))
selected = [x for x in events if x["event"] in {"model_decision", "tool_error", "model_error", "stage_changed",
    "deadline_warning", "run_failed", "submission_accepted", "scouting_acknowledged", "pricing_computed", "record_added"}]
for event in selected[-args.tail:]:
    print(f"{event['elapsed']:7.1f}s {event['event']:24s} {event.get('summary', event.get('error', event.get('reason', event.get('stage', ''))))}")
    if event["event"] == "pricing_computed":
        print(json.dumps(event["result"].get("unresolved", {}), ensure_ascii=False))
errors = [r for x in events if x.get("event") == "tool_result" and x.get("tool") == "record"
          for r in x.get("result", []) if isinstance(r, dict) and r.get("error")]
if errors:
    print("Recent record failures:")
    for row in errors[-5:]:
        print(json.dumps(row, ensure_ascii=False))
