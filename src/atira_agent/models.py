from __future__ import annotations

import asyncio
import json
import random
import time

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from .contracts import AgentAction
from .tool_specs import model_tools


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

    def record(item):
        if not isinstance(item, dict):
            raise ValueError("Each record must be an object")
        container(item, "data", dict)
        container(item, "citations", list)
        for citation in item.get("citations", []):
            if not isinstance(citation, dict):
                raise ValueError("Each citation must be an object")
            container(citation, "scope", dict)

    if action in {"record", "cite"}:
        record(args)
        container(args, "records", list)
        for item in args.get("records", []):
            record(item)
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
                        parallel_tool_calls=False, temperature=0.1, max_tokens=6000,
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

    async def close(self):
        await self.client.close()
