from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


class Redactor:
    """One redaction boundary for every durable output, including exception messages."""

    def __init__(self, secrets=()):
        self.secrets: set[str] = set()
        for value in secrets:
            self.add(value)

    def add(self, value: str) -> None:
        if value and len(value) >= 3 and value != "local":
            self.secrets.add(value)
            self.secrets.add(quote(value, safe=""))

    def text(self, value: str) -> str:
        for secret in sorted(self.secrets, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)(/llm/(?:run|team)/)[^/\s]+", r"\1[REDACTED]", value)
        value = re.sub(r"(?i)((?:password|passwort|authorization|api[_ -]?key|cookie|token)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", value)
        value = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
        value = re.sub(r"(?i)(\bTAN\b\s*(?:lautet|ist|:|=)?\s*)[0-9][0-9 -]{3,12}", r"\1[REDACTED]", value)
        return value

    def clean(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): v if k == "secret" and isinstance(v, str) and re.fullmatch(r"[\w-]+:(?:username|password)", v)
                    else "[REDACTED]" if re.search(
                r"(?i)^(password|passwort|credentials|authorization|cookie|cookies|(?:x[-_])?api[-_]key|token|tan|secret|model_key|(?:request_|response_)?headers)$", str(k)
            ) else self.clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            return self.text(value)
        return value


class Telemetry:
    def __init__(self, trace_dir: Path, redactor: Redactor, run_id: str | None = None, console=True):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.trace_dir = trace_dir
        trace_dir.mkdir(parents=True, exist_ok=True)
        self.redactor = redactor
        self.console = console
        self.structured_stdout = True
        self.debug = False
        self.started = time.monotonic()
        self.action_id = 0
        self.tab = 0
        self.site = ""
        self.events = deque(maxlen=2000)
        self.queues: set[asyncio.Queue] = set()
        self.state: dict[str, Any] = {"run_id": self.run_id, "stage": "starting", "submission": "draft"}
        self.file = (trace_dir / "events.jsonl").open("a", encoding="utf-8", buffering=1)

    def emit(self, event_kind: str, **data) -> dict:
        event = self.redactor.clean({
            "timestamp": datetime.now(timezone.utc).isoformat(), "run_id": self.run_id,
            "action_id": self.action_id, "tab": self.tab, "site": self.site,
            "elapsed": round(time.monotonic() - self.started, 3), "event": event_kind, **data,
        })
        line = json.dumps(event, ensure_ascii=False, default=str)
        self.file.write(line + "\n")
        if self.console:
            if self.structured_stdout:
                print(line, flush=True)
            elif self.debug or event_kind in {"run_started", "stage_changed", "model_decision", "tool_error",
                    "model_error", "deadline_warning", "run_failed", "submission_state", "dashboard_started",
                    "pricing_computed", "scouting_acknowledged", "submission_accepted"}:
                detail = event.get("summary", event.get("error", event.get("reason", event.get("stage",
                                   event.get("submission", event.get("url", ""))))))
                print(f"[{event['elapsed']:7.1f}s] {event_kind}: {str(detail)[:500]}", flush=True)
        self.events.append(event)
        self.state.update(event)
        if event_kind == "stage_changed":
            self.state["stage"] = data["stage"]
        if event_kind == "observation":
            self.state["page_url"] = event.get("url", "")
        if event_kind == "screenshot":
            self.state["screenshot"] = event["path"]
        if event_kind == "pricing_computed":
            self.state["pricing_result"] = event["result"]
        if event_kind == "evidence_added":
            self.state["latest_evidence"] = event["evidence"]
        for queue in tuple(self.queues):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)
        return event

    def artifact(self, name: str, value: Any) -> None:
        path = (self.trace_dir / name).resolve()
        if not path.is_relative_to(self.trace_dir.resolve()):
            raise ValueError("Artifact outside trace directory")
        path.write_text(json.dumps(self.redactor.clean(value), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def close(self):
        self.file.close()


def safe_error(exc: Exception, redactor: Redactor) -> str:
    return redactor.text(f"{type(exc).__name__}: {exc}")[:1800]


def configure_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
