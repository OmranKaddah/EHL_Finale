"""Clef-assisted visual popup classification with no authority to act."""
from __future__ import annotations

import asyncio
import json

from openai import AsyncOpenAI


class PopupClassifier:
    """Classify sanitized screenshots only when browser evidence suggests a blocker.

    This is deliberately advisory.  It neither sees credentials/TAN screenshots
    nor produces browser actions; Qwen still chooses every observed control.
    """
    def __init__(self, config, telemetry):
        self.telemetry = telemetry
        self.model = config.clef_model
        self.client = (AsyncOpenAI(base_url=config.clef_url, api_key=config.clef_key, max_retries=0, timeout=15)
                       if config.clef_url and config.clef_key else None)

    @staticmethod
    def needed(observation) -> bool:
        text = observation.text.lower()
        modal = any(item.get("inside_modal") or item.get("blocked_by_modal") for item in observation.controls)
        words = ("cookie", "consent", "survey", "notice", "hinweis", "robot", "captcha", "verification", "overlay")
        return modal or any(word in text for word in words)

    async def classify(self, image_base64: str | None, observation) -> dict | None:
        if not self.client or not image_base64 or not self.needed(observation):
            return None
        prompt = (
            "Classify this sanitized browser screenshot for a sales-RFQ agent. Return JSON only: "
            '{"kind":"blocking_popup|normal_page|uncertain","reason":"short visible-only description",'
            '"safe_next_step":"inspect_observed_popup_control|continue_normal_observation"}. '
            "Do not identify values, solve CAPTCHAs, infer hidden controls, or propose coordinates."
        )
        try:
            async with asyncio.timeout(15):
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_base64}},
                    ]}], max_tokens=180, temperature=0,
                )
            text = (response.choices[0].message.content or "").strip().removeprefix("```json").removesuffix("```").strip()
            result = json.loads(text)
            if result.get("kind") not in {"blocking_popup", "normal_page", "uncertain"}:
                raise ValueError("unexpected classification")
            result = {key: str(result.get(key, ""))[:280] for key in ("kind", "reason", "safe_next_step")}
            self.telemetry.emit("popup_classified", observation=observation.id, classification=result)
            return result
        except Exception as exc:
            self.telemetry.emit("popup_classification_unavailable", error=type(exc).__name__)
            return None

    async def close(self):
        if self.client:
            await self.client.close()
