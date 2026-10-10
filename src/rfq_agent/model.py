"""Configurable model transport; scored calls use Atira's provider proxy."""

import os
import asyncio
import time

from openai import AsyncOpenAI
from dotenv import load_dotenv, dotenv_values

QWEN_MODEL = "qwen3.8-flash-next"


def configuration():
    # Team secrets and platform endpoints take precedence. Never load a bundled
    # development key or endpoint in the timed sandbox.
    if not os.environ.get("CHALLENGE_RUN_TOKEN"):
        load_dotenv(".env", override=False)
        if not os.environ.get("OPENAI_API_KEY"):
            local_key = dotenv_values(".env").get("OPENAI_API_KEY")
            if local_key:
                os.environ["OPENAI_API_KEY"] = local_key
    provider = os.environ.get("RFQ_MODEL_PROVIDER", "openai").lower()
    if provider == "qwen":
        if os.environ.get("CHALLENGE_RUN_TOKEN"):
            proxy = os.environ.get("LLM_PROXY_URL")
            if not proxy:
                raise RuntimeError("Sandbox Qwen calls require LLM_PROXY_URL")
            return provider, QWEN_MODEL, proxy.rstrip("/") + "/qwen/v1", os.environ["CHALLENGE_RUN_TOKEN"]
        return provider, QWEN_MODEL, os.environ["QWEN_BASE_URL"], os.environ["QWEN_API_KEY"]
    if provider != "openai":
        raise ValueError("RFQ_MODEL_PROVIDER must be openai or qwen")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    if os.environ.get("CHALLENGE_RUN_TOKEN"):
        proxy = os.environ.get("LLM_PROXY_URL")
        if not proxy:
            raise RuntimeError("Scored OpenAI calls require LLM_PROXY_URL")
        base = proxy.rstrip("/") + "/openai/v1"
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing; use .env locally or a team secret in runs")
    return provider, os.environ.get("OPENAI_MODEL", "gpt-5-nano"), base, key


def client() -> AsyncOpenAI:
    _, _, base, key = configuration()
    return AsyncOpenAI(
        base_url=base,
        api_key=key,
        timeout=360,
    )


async def complete(messages: list[dict], timeout: float = 360, response_schema=None) -> str:
    provider, model_name, _, _ = configuration()
    options = {}
    if provider == "openai":
        options['response_format'] = ({'type': 'json_schema', 'json_schema': {'name': 'browser_decision', 'strict': True, 'schema': response_schema}}
                                      if response_schema else {'type': 'json_object'})
    if provider == "openai" and model_name.startswith("gpt-5"):
        options["reasoning_effort"] = os.environ.get("OPENAI_REASONING_EFFORT", "low")
    async with client() as api:
        request = api.with_options(timeout=timeout, max_retries=0)
        response = await request.chat.completions.create(model=model_name, messages=messages, **options)
    return response.choices[0].message.content or ""


async def complete_with_retry(messages: list[dict], timeout: float, budget, phase="model", response_schema=None) -> str:
    """Retry transient transport/provider errors without consuming the reserved time."""
    from openai import APIConnectionError, APITimeoutError, APIStatusError
    for attempt in range(3):
        available = budget()
        if available <= 0:
            raise TimeoutError(f"{phase}: reserved workflow deadline reached")
        limit = min(timeout, available)
        started = time.monotonic()
        async def heartbeat():
            while True:
                await asyncio.sleep(60)
                print(f"[{phase}] waiting for model ({time.monotonic() - started:.0f}s elapsed)", flush=True)
        ticker = asyncio.create_task(heartbeat())
        try:
            request = complete(messages, limit, response_schema=response_schema) if response_schema else complete(messages, limit)
            result = await asyncio.wait_for(request, limit)
            return result
        except (APIConnectionError, APITimeoutError, APIStatusError, TimeoutError) as exc:
            if isinstance(exc, APIStatusError) and exc.status_code not in {408, 429, 500, 502, 503, 504}:
                raise
            status = f" HTTP {exc.status_code}" if isinstance(exc, APIStatusError) else ""
            print(f"[{phase}] model attempt failed: {type(exc).__name__}{status}; elapsed={time.monotonic() - started:.1f}s", flush=True)
            if attempt == 2 or budget() <= 2 ** attempt:
                raise
            await asyncio.sleep(2 ** attempt)
        finally:
            ticker.cancel()
            try:
                await ticker
            except asyncio.CancelledError:
                pass
    raise RuntimeError('unreachable')
