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
