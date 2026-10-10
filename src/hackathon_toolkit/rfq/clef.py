"""Cloudflare Clef decision model client for the Atira RFQ challenge."""
from __future__ import annotations

import asyncio
from typing import Any


class ClefClient:
    """Hosted Cloudflare Clef decision model client through the configured Atira proxy.

    Clef is a multimodal non-autoregressive decision model designed for rapid,
    low-latency, low-cost decisions (choice selection, boolean verification via noul,
    and rubric scoring) over state and up to four screenshots.
    """

    def __init__(self, client, base_url: str, api_key: str):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    @property
    def decide_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/decide"
        return f"{self.base_url}/v1/decide"

    async def decide(
        self,
        state: dict[str, Any] | str,
        questions: dict[str, Any],
        images: list[str] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Send a decision query to Clef /v1/decide endpoint."""
        import httpx

        state_payload = state if isinstance(state, dict) else {"text": str(state)}
        for question in questions.values():
            if question.get("type") == "choice":
                criteria = question.get("criteria")
                if not isinstance(criteria, dict) or not criteria or any(not isinstance(v, str) for v in criteria.values()):
                    raise ValueError("Clef choice needs criteria mapping option IDs to string descriptions")
            elif question.get("type") == "noul" and "criteria" in question:
                raise ValueError("Clef noul takes instructions, not choice criteria")
        payload: dict[str, Any] = {
            "state": state_payload,
            "questions": questions,
        }
        if images:
            # Clef accepts up to 4 images/screenshots
            payload["images"] = list(images)[:4]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(3):
            try:
                response = await self.client.post(
                    self.decide_url,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {
                    408, 429, 500, 502, 503, 504
                }
                if not retryable or attempt == 2:
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 400:
                        raise ValueError("Clef rejected question format: " + exc.response.text[:600]) from exc
                    raise
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("Clef request failed after retries")

    async def choose(
        self,
        state: dict[str, Any] | str,
        instructions: str,
        criteria: dict[str, str],
        question_id: str = "choice",
        images: list[str] | None = None,
    ) -> dict[str, Any]:
        """Helper for 'choice' questions: pick one option from criteria."""
        questions = {
            question_id: {
                "type": "choice",
                "instructions": instructions,
                "criteria": criteria,
            }
        }
        return await self.decide(state, questions, images=images)

    async def ask_noul(
        self,
        state: dict[str, Any] | str,
        instructions: str,
        question_id: str = "yes_no",
        images: list[str] | None = None,
    ) -> dict[str, Any]:
        """Helper for 'noul' questions: evaluate probability of yes (0 to 1)."""
        questions = {
            question_id: {
                "type": "noul",
                "instructions": instructions,
            }
        }
        return await self.decide(state, questions, images=images)

    async def score(
        self,
        state: dict[str, Any] | str,
        instructions: str,
        criteria: dict[str, str] | None = None,
        question_id: str = "score",
        images: list[str] | None = None,
    ) -> dict[str, Any]:
        """Helper for 'score' questions: rate on a rubric scale."""
        q: dict[str, Any] = {
            "type": "score",
            "instructions": instructions,
        }
        if criteria:
            q["criteria"] = criteria
        questions = {question_id: q}
        return await self.decide(state, questions, images=images)
