"""The free hosted models in short: one call each. Docs: $API/start#models and $API/docs/run-contract.md#llm-calls

Qwen (Qwen3.8-Flash-Next): an OpenAI-compatible chat model with tool calls, images and a 256k context. Every run gets
QWEN_BASE_URL and QWEN_API_KEY; on your machine `atira scout --env` points them at `atira models proxy`, which you
keep running in another terminal.

Clef (Cloudflare Clef): a decision model. POST $CLEF_BASE_URL/v1/decide with a `state`, up to 4 `images` and your
`questions`: "choice" picks one of your options, "noul" gives the probability of yes, "score" rates on your scale.
CLEF_BASE_URL and CLEF_API_KEY are set only where the platform hosts Clef. A run waits only for the models listed in
agent.json "models" to warm up: list ["qwen", "clef"] if your agent relies on Clef.

Any other provider works with your own key, through the run's metering proxy: see the docs above.
"""
import os

import httpx  # comes with the OpenAI SDK
from openai import AsyncOpenAI

QWEN_MODEL = "qwen3.8-flash-next"


def qwen() -> AsyncOpenAI:
    """A client for the hosted Qwen; a cold model takes a while to answer its first call, hence the long timeout."""
    return AsyncOpenAI(base_url=os.environ["QWEN_BASE_URL"], api_key=os.environ["QWEN_API_KEY"], timeout=360)


async def ask_qwen(prompt: str) -> str:
    """One chat call: the reply's text."""
    reply = await qwen().chat.completions.create(model=QWEN_MODEL, messages=[{"role": "user", "content": prompt}])
    return reply.choices[0].message.content or ""


async def ask_clef(state, question: str) -> float:
    """One decision: how likely Clef finds the answer to a yes/no question about `state` (text or JSON) is yes."""
    body = {"state": state, "questions": {"q": {"type": "noul", "instructions": question}}}
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(os.environ["CLEF_BASE_URL"].rstrip("/") + "/v1/decide", json=body,
                                     headers={"Authorization": f"Bearer {os.environ['CLEF_API_KEY']}"})
    response.raise_for_status()
    return response.json()["answers"]["q"]["noul"]


# With the team's own OpenAI key (a team secret; calls go through the run's metering proxy, OPENAI_BASE_URL) each role
# gets the best available model for its job; without it, or if a model is refused, the hosted Qwen.
ROLES = {
    # the newest fast and cheap OpenAI model: steps Qwen times out on, planning and calculation
    "navigate": (["gpt-5.4-mini", "gpt-5-mini"], {"reasoning_effort": "low"}),
    "reason": (["gpt-5.4-mini", "gpt-5-mini"], {"reasoning_effort": "medium"}),
}
_picked: dict = {}
_ids = None


async def pick(role: str):
    """(client, model, extra request params) for a role; probed once per run, never longer than 25 s."""
    import asyncio
    if role in _picked:
        return _picked[role]
    task = asyncio.ensure_future(_pick(role))
    done, _ = await asyncio.wait({task}, timeout=25)
    if not done:
        task.cancel()
        print(f"model for {role}: OpenAI not answering, using {QWEN_MODEL}", flush=True)
        _picked[role] = (qwen(), QWEN_MODEL, {})
    return _picked[role]


async def _pick(role: str):
    global _ids
    if role in _picked:
        return _picked[role]
    choice = (qwen(), QWEN_MODEL, {})
    key, base = os.environ.get("OPENAI_API_KEY"), os.environ.get("OPENAI_BASE_URL")
    if key and base and key != os.environ.get("CHALLENGE_RUN_TOKEN"):
        try:
            client = AsyncOpenAI(base_url=base, api_key=key, timeout=180)
            if _ids is None:
                _ids = {m.id async for m in client.models.list()}
                print("OpenAI models available: " + ", ".join(sorted(_ids)), flush=True)
            names, extra = ROLES[role]
            for name in names:
                if name not in _ids:
                    continue
                params = extra if name.startswith(("gpt-5", "o")) else {}
                if name.startswith("o") and params.get("reasoning_effort") == "minimal":
                    params = {"reasoning_effort": "low"}
                try:
                    await client.chat.completions.create(model=name, messages=[{"role": "user", "content": "ok"}],
                                                         max_completion_tokens=64, **params)
                    choice = (client, name, params)
                    break
                except Exception as e:
                    print(f"{role}: {name} refused: {type(e).__name__} {str(e)[:150]}", flush=True)
        except Exception as e:
            print(f"OpenAI unavailable: {type(e).__name__} {str(e)[:200]}", flush=True)
    print(f"model for {role}: {choice[1]}", flush=True)
    _picked[role] = choice
    return choice


async def strong():
    return await pick("reason")
