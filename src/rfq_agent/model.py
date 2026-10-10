"""Client for the challenge-hosted Qwen model; calls go through Atira's proxy."""

import os

from openai import AsyncOpenAI

QWEN_MODEL = "qwen3.8-flash-next"


def client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=os.environ["QWEN_BASE_URL"],
        api_key=os.environ["QWEN_API_KEY"],
        timeout=360,
    )


async def complete(messages: list[dict], timeout: float = 360) -> str:
    async with client() as api:
        request = api.with_options(timeout=timeout, max_retries=0)
        response = await request.chat.completions.create(model=QWEN_MODEL, messages=messages)
    return response.choices[0].message.content or ""


async def complete_with_retry(messages: list[dict], timeout: float, budget) -> str:
    """Retry transient transport/provider errors without consuming the reserved time."""
    import asyncio
    from openai import APIConnectionError, APITimeoutError, APIStatusError
    for attempt in range(3):
        available = budget()
        if available <= 0:
            raise TimeoutError('model deadline reached')
        try:
            return await asyncio.wait_for(complete(messages, min(timeout, available)), min(timeout, available))
        except (APIConnectionError, APITimeoutError, APIStatusError, TimeoutError) as exc:
            if isinstance(exc, APIStatusError) and exc.status_code not in {408, 429, 500, 502, 503, 504}:
                raise
            if attempt == 2 or budget() <= 2 ** attempt:
                raise
            await asyncio.sleep(2 ** attempt)
    raise RuntimeError('unreachable')
