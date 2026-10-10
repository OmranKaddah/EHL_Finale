from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import jsonschema
import simplejson

from .browser import origin
from .contracts import SubmissionState
from .runtime import USER_AGENT


def validate_answer(answer: dict, schema: dict):
    validator = jsonschema.validators.validator_for(schema)
    validator.check_schema(schema)
    validator(schema).validate(answer)
    payload = simplejson.dumps(answer, use_decimal=True, ensure_ascii=False).encode()
    if len(payload) > 65536:
        raise ValueError("Answer exceeds platform size limit")
    positions = answer["positions"]
    if len({x["position"] for x in positions}) != len(positions):
        raise ValueError("Duplicate positions")
    if answer["decision"] == "no_bid" and (positions or Decimal(str(answer["total_net"])) != 0):
        raise ValueError("no_bid requires no positions and a zero total")
    total = sum((Decimal(str(x["unit_price"])) * x["quantity"] for x in positions), Decimal(0))
    if total != Decimal(str(answer["total_net"])):
        raise ValueError("Total must equal quantities times final rounded unit prices")
    return payload


class Submission:
    def __init__(self, run, browser, telemetry):
        self.run, self.browser, self.telemetry = run, browser, telemetry
        self.state = SubmissionState.DRAFT
        self.result = None
        self.receipt = None
        self.signing_attempted_at = None
        self.signing_started_at = None

    def transition(self, state):
        self.state = state
        self.telemetry.emit("submission_state", submission=state.value)

    def prepare(self, result):
        if not result.answer:
            raise ValueError("No verified answer ready; resolve calculation issues")
        validate_answer(result.answer, self.run.answer_schema)
        self.result = result
        self.transition(SubmissionState.VALIDATED)
        self.telemetry.emit("submission_started", answer=result.answer, omitted=result.omitted)
        return {"answer": result.answer, "omitted": result.omitted,
                "instruction": "Map these values to current form controls. Explicitly omit listed positions; sign and verify receipt."}

    def answer_value(self, path):
        if self.result is None:
            raise ValueError("Prepare a verified answer first")
        value = self.result.answer
        for part in path.split("."):
            value = value[int(part)] if isinstance(value, list) else value[part]
        if isinstance(value, (dict, list)):
            raise ValueError("Answer path must select one field")
        return value

    async def fill(self, fields):
        if self.state not in {SubmissionState.VALIDATED, SubmissionState.TAN_REQUESTED}:
            raise ValueError("Answer not ready for entry")
        for field in fields:
            value = self.answer_value(field["path"])
            if isinstance(value, Decimal):
                value = format(value, "f")
            else:
                value = str(value)
            if field.get("format") == "de":
                value = value.replace(".", ",")
            await self.browser.act("fill", {"ref": field["ref"], "text": value})
        return {"filled": len(fields)}

    async def request_tan(self, args):
        if self.result is None:
            raise ValueError("Prepare a validated answer before requesting TAN")
        if self.state in {SubmissionState.ACCEPTED, SubmissionState.SCOUTING_ACKNOWLEDGED}:
            raise ValueError("Submission is already accepted")
        if self.state == SubmissionState.SIGNING_ATTEMPTED:
            observation = self.browser.last_observation
            if (not observation or origin(observation.url) != origin(self.run.submission.url)
                    or self.signing_started_at is None or observation.observed_at <= self.signing_started_at
                    or not re.search(r"(?i)(ungültig|abgelaufen|invalid|expired|validation failed|validierungsfehler)", observation.text)):
                raise ValueError("Inspect the portal for a receipt or explicit validation failure before requesting another TAN")
        self.browser.latest_tan = None
        self.browser.tan_captured_at = None
        self.browser.tan_requested_at = time.monotonic()
        self.browser.tan_request_observation = self.browser.observation_number
        await self.browser.act("click", {"ref": args["ref"]})
        self.transition(SubmissionState.TAN_REQUESTED)
        self.telemetry.emit("tan_requested")
        return {"requested": True, "instruction": "Read the newest matching signing mail; prior TANs are invalid."}

    async def sign(self, args):
        if self.state != SubmissionState.TAN_REQUESTED or not self.browser.latest_tan:
            raise ValueError("Signing requires a fresh requested and captured TAN")
        if time.monotonic() - self.browser.tan_captured_at > 240:
            raise ValueError("TAN may be expired; request a fresh TAN")
        if not args.get("reviewed") or not args.get("omissions_confirmed"):
            raise ValueError("Review the portal values and explicit omissions before final signing")
        self.signing_attempted_at = time.monotonic()
        self.signing_started_at = datetime.now(timezone.utc)
        self.transition(SubmissionState.SIGNING_ATTEMPTED)
        await self.browser.act("click", {"ref": args["ref"]})
        return {"attempted": True, "instruction": "Handle the confirmation dialog, then inspect the receipt. Do not repeat an uncertain signing action."}

    def accept_receipt(self, observation, args):
        if self.state != SubmissionState.SIGNING_ATTEMPTED:
            raise ValueError("No signing attempt to verify")
        if not self.result:
            raise ValueError("No prepared answer")
        if origin(observation.url) != origin(self.run.submission.url):
            raise ValueError("Receipt must be observed on the declared submission website")
        if self.signing_started_at is not None and observation.observed_at <= self.signing_started_at:
            raise ValueError("Receipt observation predates this signing attempt")
        excerpt = args["excerpt"]
        if excerpt not in observation.text:
            raise ValueError("Receipt excerpt must be present in the observed page")
        receipt_id = args.get("receipt_id", "")
        if not receipt_id or receipt_id not in observation.text:
            raise ValueError("Read the visible receipt/confirmation identifier")
        if not re.search(r"(?i)(eingegangen|eingereicht|übermittelt|abgegeben|erfolgreich|bestätigung|accepted|received|receipt|acknowledged)", excerpt):
            raise ValueError("Receipt does not state completed acceptance")
        if self.result.answer["tender_reference"] not in observation.text:
            raise ValueError("Receipt must identify the submitted tender")
        self.receipt = {"id": receipt_id, "excerpt": excerpt, "url": observation.url,
                        "observation": observation.id, "reference": self.result.answer["tender_reference"]}
        local = self.run.kind == "scouting"
        self.transition(SubmissionState.SCOUTING_ACKNOWLEDGED if local else SubmissionState.ACCEPTED)
        self.telemetry.emit("scouting_acknowledged" if local else "submission_accepted", receipt=self.receipt)
        self.telemetry.artifact("receipt.json", self.receipt)
        return self.receipt

    async def api_submit(self, token):
        if self.run.submission.kind != "api":
            raise ValueError("This run requires the website signing workflow")
        if self.result is None or not token:
            raise ValueError("A validated answer and a live run token are required")
        payload = validate_answer(self.result.answer, self.run.answer_schema)
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT, "x-api-key": token,
                                                        "Content-Type": "application/json"}) as client:
            response = await client.post(self.run.submission.url, content=payload)
        if response.status_code == 400:
            return {"validation_issues": response.json()}
        if response.status_code != 202:
            raise RuntimeError(f"Submission returned HTTP {response.status_code}")
        self.receipt = response.json()
        self.transition(SubmissionState.ACCEPTED)
        self.telemetry.emit("submission_accepted", receipt=self.receipt)
        self.telemetry.artifact("receipt.json", self.receipt)
        return self.receipt
