from __future__ import annotations

import asyncio
import json
import random
import time

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from .contracts import AgentAction
from .tool_specs import model_tools


def normalize_record_item(item: dict) -> dict:
    """Accept a flat named-tool record while retaining the canonical envelope.

    Tool-call models occasionally place typed record fields beside ``kind`` in
    a batch rather than under ``data``.  This is a transport variation, not a
    business inference: it is normalized before the normal schema and evidence
    checks run.  A record without actual typed fields still fails clearly.
    """
    if "data" in item or "kind" not in item:
        return item
    data = {key: value for key, value in item.items() if key not in {"kind", "citations", "summary"}}
    if not data:
        return item
    return {**{key: value for key, value in item.items() if key in {"kind", "citations", "summary"}}, "data": data}


def parse_action(payload: str) -> AgentAction:
    """Normalize harmless transport variations; the executor still validates business inputs."""
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Action must be an object")
    action = data.get("action")
    args = data.get("args", {})
    if isinstance(args, str):
        args = json.loads(args)
    if not isinstance(args, dict):
        raise ValueError("Action args must be an object")
    args = dict(args)
    for key, value in data.items():
        if key in {"action", "summary", "args"}:
            continue
        if key in args and args[key] != value:
            raise ValueError(f"Conflicting action argument: {key}")
        args[key] = value
    def container(parent, key, expected):
        if key not in parent:
            return
        value = parent[key]
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, expected):
            raise ValueError(f"{key} must be a JSON {expected.__name__}")
        parent[key] = value

    def record(item, *, require_data=False):
        if not isinstance(item, dict):
            raise ValueError("Each record must be an object")
        if require_data and "data" not in item:
            raise ValueError("record requires data for every record item")
        container(item, "data", dict)
        container(item, "citations", list)
        for citation in item.get("citations", []):
            if not isinstance(citation, dict):
                raise ValueError("Each citation must be an object")
            container(citation, "scope", dict)

    if action == "record":
        container(args, "records", list)
        if "records" in args:
            if "data" in args:
                raise ValueError("record must use either data or records, not both")
            if not args["records"]:
                raise ValueError("record requires a nonempty records list")
            args["records"] = [normalize_record_item(item) if isinstance(item, dict) else item
                               for item in args["records"]]
            for item in args["records"]:
                record(item, require_data=True)
        else:
            args = normalize_record_item(args)
            record(args, require_data=True)
    if action == "cite":
        container(args, "citations", list)
        for citation in args.get("citations", []):
            if not isinstance(citation, dict):
                raise ValueError("Each citation must be an object")
            container(citation, "scope", dict)
    if action == "fill_answer":
        container(args, "fields", list)
    if action in {"inspect_controls", "read_links"}:
        container(args, "refs", list)
    return AgentAction.model_validate({"action": action, "summary": data.get("summary") or f"Execute {action}", "args": args})


def parse_tool_call(name: str, payload: str) -> AgentAction:
    if name == "act":
        return parse_action(payload)
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Tool arguments must be an object")
    if "action" in data and data["action"] != name:
        raise ValueError("Tool name and nested action conflict")
    return parse_action(json.dumps({**data, "action": name}))


class QwenClient:
    def __init__(self, config, telemetry):
        self.config, self.telemetry = config, telemetry
        self.client = AsyncOpenAI(base_url=config.model_url, api_key=config.model_key, max_retries=0, timeout=120)
        self.input_tokens = self.output_tokens = 0

    async def decide(self, messages, deadline):
        for attempt in range(3):
            started = time.monotonic()
            try:
                timeout = deadline.timeout(120, investigation=not deadline.submission_due)
                self.telemetry.emit("model_started", model=self.config.model, attempt=attempt + 1, remaining=deadline.remaining)
                async with asyncio.timeout(timeout):
                    reply = await self.client.chat.completions.create(
                        model=self.config.model, messages=messages, tools=model_tools(),
                        tool_choice="required",
                        # Each turn must return one small, validated tool call.
                        # A large completion allowance needlessly increases
                        # latency while specialists are traversing paginated UI.
                        parallel_tool_calls=False, temperature=0.1, max_tokens=1200,
                    )
                usage = reply.usage
                if usage:
                    self.input_tokens += usage.prompt_tokens
                    self.output_tokens += usage.completion_tokens
                self.telemetry.emit("model_usage", seconds=round(time.monotonic() - started, 3),
                                    input_tokens=self.input_tokens, output_tokens=self.output_tokens,
                                    call_usage=usage.model_dump() if usage else None)
                message = reply.choices[0].message
                if message.tool_calls:
                    if len(message.tool_calls) != 1:
                        raise ValueError("Return exactly one tool call")
                    payload = message.tool_calls[0].function.arguments
                    return parse_tool_call(message.tool_calls[0].function.name, payload)
                else:
                    payload = (message.content or "").strip().removeprefix("```json").removesuffix("```").strip()
                return parse_action(payload)
            except (APIConnectionError, APITimeoutError, APIStatusError, TimeoutError) as exc:
                status = getattr(exc, "status_code", None)
                self.telemetry.emit("model_error", error=type(exc).__name__, status=status, attempt=attempt + 1)
                if status is not None and status not in {408, 429} and status < 500:
                    raise RuntimeError(f"Model request rejected: HTTP {status}") from None
                if attempt == 2 or deadline.remaining < 10:
                    raise
                await asyncio.sleep(min(2 ** attempt + random.random(), max(0, deadline.remaining - 1)))

    async def smoke(self):
        response = await self.client.chat.completions.create(model=self.config.model, timeout=360,
            messages=[{"role": "user", "content": "Reply with exactly READY."}], max_tokens=300)
        if not response.choices[0].message.content:
            raise RuntimeError("Model smoke returned no visible answer")
        return {"model": self.config.model, "reply": response.choices[0].message.content,
                "usage": response.usage.model_dump() if response.usage else None}

    async def assign_specialists(self, brief: str, sites: list[dict], fallback: dict[str, str]) -> dict[str, str]:
        """Use Qwen to assign opaque runtime sites to the four fixed responsibilities.

        The result is validated against the runtime inventory and falls back to a
        deterministic mapping if the small dispatch call is unavailable.
        """
        prompt = {"task": "Assign the four supplied websites to tender, specifications, erp and mail specialists.",
                  "brief": self.telemetry.redactor.text(brief), "sites": sites,
                  "return": {"tender": "siteId", "specifications": "siteId", "erp": "siteId", "mail": "siteId"}}
        try:
            reply = await self.client.chat.completions.create(
                model=self.config.model, messages=[{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
                response_format={"type": "json_object"}, temperature=0, max_tokens=300,
            )
            value = json.loads((reply.choices[0].message.content or "{}"))
            valid = {site["id"] for site in sites}
            if set(value) != set(fallback) or set(value.values()) != valid:
                raise ValueError("invalid assignment")
            self.telemetry.emit("specialist_dispatch", assignments=value, method="qwen")
            return value
        except Exception as exc:
            self.telemetry.emit("specialist_dispatch", assignments=fallback, method="validated_fallback",
                                error=type(exc).__name__)
            return fallback

    async def close(self):
        await self.client.close()
