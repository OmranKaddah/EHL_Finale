from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import deque

from .contracts import RECORD_TYPES, Observation, SubmissionState
from .evidence import EvidenceLedger
from .pricing import calculate
from .prompts import SYSTEM
from .submit import Submission
from .telemetry import safe_error


def action_signature(action, observation):
    """Detect unchanged retries without conflating identically labelled rows or pagination."""
    args = dict(action.args)
    if "ref" in args:
        control = next((x for x in observation.controls if x["ref"] == args["ref"]), {})
        args["ref"] = (re.sub(r"^(?:.*-)?o\d+-", "", args["ref"]), control.get("label"), control.get("context"))
    state = (observation.url, hashlib.sha256(observation.text.encode()).hexdigest())
    return action.action, json.dumps(args, sort_keys=True, default=str), state


class Orchestrator:
    def __init__(self, run, config, browser, model, telemetry, deadline, token=None, *, ledger=None,
                 submission=None, agent_name="orchestrator", role_instruction="", research_only=False):
        self.run, self.config, self.browser, self.model = run, config, browser, model
        self.telemetry, self.deadline, self.token = telemetry, deadline, token
        self.ledger = ledger or EvidenceLedger(telemetry)
        self.submission = submission or Submission(run, browser, telemetry)
        self.agent_name, self.role_instruction, self.research_only = agent_name, role_instruction, research_only
        self.history = deque(maxlen=16)
        self.pricing = None
        self.observation = None
        self.stage = "investigating"
        self.last_action = None
        self.repeat_count = 0
        self._warned = False
        self.tan_callback = None
        self.popup_classifier = None
        self.popup_classification = None

    def messages(self):
        context = {
            "task": self.telemetry.redactor.text(self.run.brief),
            "sites": [{"id": s.siteId, "url": s.url,
                       "credential_handles": [f"{s.siteId}:{key}" for key in s.credentials]} for s in self.run.access],
            "submission_target": self.run.submission.model_dump(), "answer_schema": self.run.answer_schema,
            "remaining_seconds": round(self.deadline.remaining), "reserve_seconds": self.deadline.reserve,
            "submission_due": self.deadline.submission_due, "stage": self.stage,
            "submission_state": self.submission.state, "evidence_ledger": self.ledger.summary(),
            "calculation": self.pricing.model_dump(mode="json") if self.pricing else None,
            "recent_actions_and_results": list(self.history),
            "current_observation": self.observation.model_dump(mode="json") if self.observation else None,
            "agent": self.agent_name,
            "role_instruction": self.role_instruction,
            "research_only": self.research_only,
            "popup_classification": self.popup_classification,
        }
        content = [{"type": "text", "text": json.dumps(self.telemetry.redactor.clean(context), ensure_ascii=False, default=str)}]
        if self.browser.last_image:
            content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + self.browser.last_image}})
        return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]

    async def run_loop(self, max_steps=450):
        task_obs = Observation(id="task", action_id=0, tab=0, url="runtime:brief", title="Runtime task brief",
                               text=self.telemetry.redactor.text(self.run.brief))
        self.ledger.observe(task_obs)
        self.telemetry.emit("stage_changed", stage=self.stage, remaining=self.deadline.remaining)
        consecutive_errors = 0
        for step in range(1, max_steps + 1):
            if self.deadline.remaining <= 1:
                break
            if self.submission.state in {SubmissionState.ACCEPTED, SubmissionState.SCOUTING_ACKNOWLEDGED}:
                return True
            self.telemetry.action_id = step
            if self.deadline.submission_due and not self._warned:
                self._warned = True
                self.stage = "submitting"
                self.pricing = calculate(self.ledger, allow_partial=True)
                self.telemetry.emit("deadline_warning", remaining=self.deadline.remaining,
                                    message="Research reserve exhausted: prioritize verified partial signing")
                self.telemetry.emit("stage_changed", stage=self.stage, remaining=self.deadline.remaining)
            try:
                if self.observation is None:
                    self.observation = await asyncio.wait_for(self.browser.observe(), self.deadline.timeout(25))
                    self.ledger.observe(self.observation)
                    self.popup_classification = await self._classify_popup(self.observation)
                action = await self.model.decide(self.messages(), self.deadline)
                self.telemetry.emit("model_decision", **action.model_dump(), remaining=self.deadline.remaining)
                signature = action_signature(action, self.observation)
                self.repeat_count = self.repeat_count + 1 if signature == self.last_action else 0
                self.last_action = signature
                if self.repeat_count >= 3:
                    raise ValueError("Repeated action made no progress. Inspect current state and choose a different action.")
                self.telemetry.emit("tool_call", tool=action.action, arguments=action.args)
                result = await asyncio.wait_for(self.execute(action), self.deadline.timeout(35))
                self.telemetry.emit("tool_result", tool=action.action, result=result)
                self.history.append({"action": action.model_dump(), "result": result})
                consecutive_errors = 0
            except Exception as exc:
                error = safe_error(exc, self.telemetry.redactor)
                self.telemetry.emit("tool_error", error=error, remaining=self.deadline.remaining)
                self.history.append({"error": error, "instruction": "Correct malformed arguments or inspect the current page. Do not repeat a failed path blindly."})
                self.observation = None
                consecutive_errors += 1
                if consecutive_errors >= 8:
                    self.telemetry.emit("run_failed", reason="Eight consecutive model/tool failures")
                    return False
            finally:
                self.telemetry.artifact("evidence.json", self.ledger.summary())
        if self.research_only:
            self.telemetry.emit("agent_complete", agent=self.agent_name, reason="research step budget reached",
                                remaining=self.deadline.remaining)
            return True
        self.telemetry.emit("run_failed", reason="Deadline or step limit reached without verified signed receipt",
                            submission=self.submission.state.value, remaining=self.deadline.remaining)
        return False

    async def _classify_popup(self, observation):
        if not self.popup_classifier:
            return None
        return await self.popup_classifier.classify(self.browser.last_image, observation)

    async def execute(self, action):
        name, args = action.action, action.args
        if self.research_only and name in {"calculate", "prepare_submission", "fill_answer", "request_tan",
                                           "capture_tan", "sign", "receipt", "api_submit"}:
            raise ValueError("This specialist publishes evidence only; the central orchestrator owns pricing and signing")
        if name == "read_links":
            results = []
            try:
                async for observation, result in self.browser.read_links(args["refs"]):
                    self.ledger.observe(observation)
                    results.append(result)
            finally:
                self.observation = await self.browser.observe()
                self.ledger.observe(self.observation)
            return results
        if name == "inspect_controls":
            results = []
            try:
                async for observation, result in self.browser.inspect_controls(args["refs"]):
                    self.observation = observation
                    self.ledger.observe(observation)
                    results.append(result)
            except (ValueError, TimeoutError) as exc:
                results.append({"error": safe_error(exc, self.telemetry.redactor)})
            return results
        if name == "schema":
            kinds = args.get("kinds", [args.get("kind")])
            return {kind: RECORD_TYPES[kind].model_json_schema() for kind in kinds}
        if name == "cite":
            items = args.get("citations", [args])
            return [{"id": fact.id, "excerpt": fact.excerpt} for fact in [
                self.ledger.cite(item["observation"], item["excerpt"], item.get("scope")) for item in items]]
        if name == "record":
            items = args.get("records", [args])
            results = []
            for item in items:
                data = item.get("data")
                try:
                    data = dict(item["data"])
                    if item.get("citations"):
                        ids = [self.ledger.cite(c["observation"], c["excerpt"], c.get("scope")).id
                               for c in item["citations"]]
                        data["evidence"] = list(dict.fromkeys(data.get("evidence", []) + ids))
                    result = self.ledger.record(item["kind"], data)
                    results.append({"kind": item["kind"], "id": result.id, "evidence": result.evidence})
                except (ValueError, KeyError, TypeError) as exc:
                    error = safe_error(exc, self.telemetry.redactor)
                    if isinstance(data, dict):
                        self.ledger.reject(item.get("kind", "unknown"), data, error)
                    record_data = item.get("data")
                    results.append({"kind": item.get("kind"), "id": record_data.get("id") if isinstance(record_data, dict) else None,
                                    "error": error})
            self.telemetry.emit("evidence_status", counts={kind: len(values) for kind, values in self.ledger.records.items()},
                                unresolved=[{"kind": x["kind"], "id": x["data"].get("id"), "error": x["error"]}
                                            for x in self.ledger.rejected.values()])
            return results
        if name == "inspect_evidence":
            if "observation" in args:
                return self.ledger.observations[args["observation"]].model_dump(mode="json")
            return self.ledger.summary()
        if name in {"calculate", "prepare_submission"}:
            self.pricing = calculate(self.ledger, allow_partial=bool(args.get("partial", self.deadline.submission_due)))
            for row in self.pricing.audit:
                self.telemetry.emit("rule_applied", **row)
            self.telemetry.emit("pricing_computed", result=self.pricing.model_dump(mode="json"))
            self.telemetry.artifact("pricing.json", self.pricing.model_dump(mode="json"))
            return self.submission.prepare(self.pricing) if name == "prepare_submission" else self.pricing.model_dump(mode="json")
        if name == "stage":
            self.stage = args["stage"]
            self.telemetry.emit("stage_changed", stage=self.stage, summary=args.get("summary", ""), remaining=self.deadline.remaining)
            return {"stage": self.stage}
        if name == "receipt":
            return self.submission.accept_receipt(self.ledger.observations[args["observation"]], args)
        if name == "api_submit":
            return await self.submission.api_submit(self.token)
        if name == "document":
            self.observation = await self.browser.document(args)
            self.ledger.observe(self.observation)
            return self.observation.model_dump(mode="json")
        if name == "fill_answer":
            result = await self.submission.fill(args["fields"])
        elif name == "request_tan":
            result = await self.submission.request_tan(args)
            if self.tan_callback:
                await self.tan_callback(self.submission)
        elif name == "sign":
            result = await self.submission.sign(args)
        elif name == "capture_tan":
            if not self.submission.result:
                raise ValueError("No prepared tender for TAN matching")
            observation = self.ledger.observations[args["observation"]]
            if self.submission.result.answer["tender_reference"] not in observation.text:
                raise ValueError("Signing mail must visibly identify this exact tender")
            result = await self.browser.act(name, args)
            if self.browser is not self.submission.browser and self.browser.latest_tan:
                self.submission.browser.latest_tan = self.browser.latest_tan
                self.submission.browser.tan_captured_at = self.browser.tan_captured_at
        else:
            result = await self.browser.act(name, args)
        self.observation = await self.browser.observe(include_image=name == "screenshot")
        self.ledger.observe(self.observation)
        self.popup_classification = await self._classify_popup(self.observation)
        return result
