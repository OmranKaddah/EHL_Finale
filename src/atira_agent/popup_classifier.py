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
        self.disabled_reason = None

    @staticmethod
    def verification_gate(observation) -> bool:
        """Recognize an unresolved verification challenge, not stale page copy.

        Mail clients can keep a locked empty preview alongside an already
        unlocked list. Its static robot text must not redirect the model away
        from a usable inbox or archive.
        """
        text = observation.text.casefold()
        terms = ("captcha", "i am not a robot", "i'm not a robot", "ich bin kein roboter",
                 "robot challenge", "verification challenge",
                 "zum entsperren", "ganz nach rechts", "empfangsnummer",
                 "betriebsbedingungen", "systemmitteilung", "geschützter bereich",
                 "ich bin kein", "kein roboter")
        if not any(term in text for term in terms):
            return False
        sliders = [item for item in observation.controls if item.get("type") == "range"]
        if sliders:
            # An inbox/search list can be unlocked while the deliberately
            # empty reading pane still renders its own dormant challenge.  A
            # checked maxed-out slider proves the active list is usable;
            # never redirect the agent back into the empty pane.
            checkboxes = [item for item in observation.controls if item.get("type") == "checkbox"]
            if any(str(item.get("value")) == "100" for item in sliders) and any(
                    item.get("checked") is True for item in checkboxes):
                return False
            for slider in sliders:
                try:
                    if float(str(slider.get("value", "0"))) < 100:
                        return True
                except (TypeError, ValueError):
                    return True
            return False
        # The page can announce the challenge before it renders controls.
        return True

    @staticmethod
    def needed(observation) -> bool:
        text = observation.text.lower()
        if PopupClassifier.verification_gate(observation):
            return False
        modal = any(item.get("inside_modal") or item.get("blocked_by_modal") for item in observation.controls)
        words = ("cookie", "consent", "survey", "notice", "hinweis", "robot", "captcha", "verification", "overlay")
        return modal or any(word in text for word in words)

    async def classify(self, image_base64: str | None, observation) -> dict | None:
        if self.verification_gate(observation):
            result = {
                "kind": "verification_gate",
                "reason": ("Observed verification gate: drag unlock slider fully right, "
                           "check robot checkbox, copy Empfangsnummer into protected input, "
                           "accept Betriebsbedingungen, then Weiter"),
                "safe_next_step": "solve_observed_verification_gate",
            }
            self.telemetry.emit("popup_classified", observation=observation.id, classification=result)
            return result
        if not self.client or not image_base64 or not self.needed(observation):
            return None
        prompt = (
            "Classify this sanitized browser screenshot for a sales-RFQ agent. Return JSON only: "
            '{"kind":"blocking_popup|normal_page|uncertain","reason":"short visible-only description",'
            '"safe_next_step":"inspect_observed_popup_control|continue_normal_observation"}. '
            "Do not identify values, infer hidden controls, or propose coordinates."
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
            # Do not log response bodies, endpoint URLs, headers, or request
            # payloads: those can contain credentials or image-derived data.
            self.telemetry.emit("popup_classification_unavailable", error=type(exc).__name__,
                                status=getattr(exc, "status_code", None))
            # A permanent endpoint mismatch cannot become useful on a later
            # screenshot. Keep Clef advisory and stop spending calls while the
            # DOM-based modal controls remain available to Qwen.
            if getattr(exc, "status_code", None) in {401, 403, 404, 422}:
                self.disabled_reason = f"HTTP {getattr(exc, 'status_code')}"
                await self.client.close()
                self.client = None
                self.telemetry.emit("popup_classifier_disabled", reason=self.disabled_reason)
            return None

    async def close(self):
        if self.client:
            await self.client.close()
