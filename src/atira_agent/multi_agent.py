"""Dependency-aware four-browser RFQ coordination.

The coordinator is deliberately browserless.  Specialists only publish cited
records to a shared ledger; deterministic pricing and the binding submission
remain centrally owned.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from .browser import BrowserSession
from .evidence import EvidenceLedger
from .models import QwenClient
from .orchestrator import Orchestrator
from .popup_classifier import PopupClassifier
from .pricing import calculate
from .submit import Submission
from .telemetry import Telemetry, safe_error

ROLE_ORDER = ("tender", "specifications", "erp", "mail")
ROLE_HINTS = {
    "tender": ("tender", "award", "bid", "vergabe", "rfq"),
    "specifications": ("spec", "customer", "document", "drawing", "requirement"),
    "erp": ("erp", "sap", "material", "inventory", "catalog"),
    "mail": ("mail", "inbox", "email", "postfach", "archive"),
}
ROLE_INSTRUCTIONS = {
    "tender": "Own only the assigned tender portal. Resolve the tender reference, positions, current Q&A, amendments, keys and deadline. After identifying the tender, finish the model-selected Q&A pages: expand relevant answers, reveal each issued date, follow pagination, and record withdrawals/amendments before spending turns on optional documents. Publish cited tender, position and Q&A records. Do not calculate or submit during investigation.",
    "specifications": "Own only the assigned specification/customer portal. Resolve the current revision, complete requirements, engineering attributes, certification and governing units. Publish cited revision and requirement records. Wait for tender/Q&A facts when scope is ambiguous.",
    "erp": "Own only the assigned ERP portal. First learn safe search/navigation, then use published requirements to select exact active materials and publish cited material, search and price records. Never infer a missing match from an incomplete search.",
    "mail": "Own only the assigned mailbox. First learn inbox/archive access. Once the tender reference is published, find authorized dated messages and publish cited approval, FX, index, packaging, pool, bonus, commercial, technical and commitment records. TANs remain secret.",
}


def assign_sites(access) -> dict[str, str]:
    """Map runtime-provided sites to specialist roles without scenario-specific URLs.

    Runtime IDs and hosts are only hints.  If an unseen deployment gives opaque
    identifiers, assignment remains deterministic and every specialist still
    decides its own navigation from live observations.
    """
    available = list(access)
    result: dict[str, str] = {}
    for role in ROLE_ORDER:
        best = None
        best_score = 0
        for site in available:
            text = f"{site.siteId} {site.url}".lower()
            score = sum(bool(re.search(re.escape(hint), text)) for hint in ROLE_HINTS[role])
            if score > best_score:
                best, best_score = site, score
        if best is None:
            best = available[0]
        result[role] = best.siteId
        available.remove(best)
    return result


def benchmark_schedule() -> dict:
    """Deterministic scheduler benchmark; no live model/browser calls.

    It compares equal unit work with the dependency graph used at runtime.  The
    result is a planning check, not a claim about hosted-model latency.
    """
    durations = {"tender": 90, "specifications": 110, "erp": 100, "mail": 95, "pricing": 25, "submit": 70}
    sequential = sum(durations.values())
    discovery_done = max(durations["tender"], durations["specifications"], 30)
    # ERP and mail have safe reconnaissance before their tender/spec dependency,
    # then complete focused work after the inputs arrive.
    parallel = max(discovery_done + durations["erp"], durations["tender"] + durations["mail"]) + durations["pricing"] + durations["submit"]
    return {"sequential_seconds": sequential, "dependency_aware_parallel_seconds": parallel,
            "saved_seconds": max(0, sequential - parallel), "assumptions": durations}


@dataclass
class Specialist:
    role: str
    site_id: str
    browser: BrowserSession
    model: QwenClient
    classifier: PopupClassifier
    telemetry: Telemetry
    controller: Orchestrator


class MultiAgentCoordinator:
    def __init__(self, run, config, deadline, root_telemetry, trace_dir: Path, token=None):
        self.run, self.config, self.deadline, self.root_telemetry, self.trace_dir, self.token = run, config, deadline, root_telemetry, trace_dir, token
        self.assignments = assign_sites(run.access)
        self.ledger = EvidenceLedger(root_telemetry)
        self.specialists: dict[str, Specialist] = {}
        self.submission = None
        self.pricing = None
        self.sequential_fallback = False

    @property
    def telemetries(self):
        return [self.root_telemetry, *(item.telemetry for item in self.specialists.values())]

    async def start(self):
        if self.config.sandbox and len(self.config.cdp_urls) != 4:
            raise RuntimeError("The multi-agent runtime requires exactly four supplied CDP browsers")
        if len(self.run.access) < 4:
            raise RuntimeError("The RFQ runtime must provide four website access records")
        dispatcher = QwenClient(self.config, self.root_telemetry)
        try:
            self.assignments = await dispatcher.assign_specialists(
                self.run.brief, [{"id": site.siteId, "url": site.url} for site in self.run.access], self.assignments)
        finally:
            await dispatcher.close()
        for index, role in enumerate(ROLE_ORDER):
            site_id = self.assignments[role]
            telemetry = Telemetry(self.trace_dir / role, self.root_telemetry.redactor, run_id=self.run.run_id,
                                  console=self.root_telemetry.console, agent=role)
            telemetry.structured_stdout = self.root_telemetry.structured_stdout
            telemetry.debug = self.root_telemetry.debug
            browser = BrowserSession(self.config, self.run, telemetry, headful=True, browser_index=index,
                                     agent_id=role, assigned_site=site_id, allow_submission=role == "tender")
            await browser.start()
            model = QwenClient(self.config, telemetry)
            classifier = PopupClassifier(self.config, telemetry)
            controller = Orchestrator(self.run, self.config, browser, model, telemetry, self.deadline, self.token,
                                      ledger=self.ledger, agent_name=role, role_instruction=ROLE_INSTRUCTIONS[role],
                                      research_only=True)
            controller.popup_classifier = classifier
            self.specialists[role] = Specialist(role, site_id, browser, model, classifier, telemetry, controller)
            telemetry.emit("agent_started", role=role, assigned_site=site_id, browser_index=index,
                           remaining=self.deadline.remaining)
        tender = self.specialists["tender"]
        self.submission = Submission(self.run, tender.browser, tender.telemetry)

    async def investigate(self, steps=72):
        return await self.investigate_roles(steps=steps)

    async def investigate_roles(self, *, steps=72, roles: tuple[str, ...] | None = None):
        """Run all specialists or a bounded evidence-only focus subset."""
        selected = tuple(roles or tuple(self.specialists))
        unknown = set(selected) - set(self.specialists)
        if unknown:
            raise ValueError(f"Unknown specialist roles: {sorted(unknown)}")
        async def run_one(item: Specialist):
            try:
                return await item.controller.run_loop(max_steps=steps)
            except Exception as exc:
                item.telemetry.emit("agent_failed", error=safe_error(exc, item.telemetry.redactor), role=item.role)
                return False
        items = [self.specialists[role] for role in selected]
        results = await asyncio.gather(*(run_one(item) for item in items), return_exceptions=False)
        failures = [role for role, ok in zip(selected, results) if not ok]
        self.root_telemetry.emit("agents_phase_complete", completed=[role for role in selected if role not in failures],
                                 failed=failures, focus=selected, remaining=self.deadline.remaining)
        if roles is not None:
            return failures
        if len(failures) >= 2 and not self.deadline.submission_due:
            # Reliability wins over keeping four logical agents alive. Reuse the
            # tender browser (one of the supplied four) for bounded sequential
            # recovery; do not create a new browser or retry failed workers.
            tender = self.specialists["tender"]
            tender.browser.expand_to_run_access()
            tender.controller.role_instruction = (
                "Multiple specialists failed. Perform a bounded sequential recovery across the runtime-provided sites, "
                "using shared evidence to fill only the highest-impact missing facts. Do not submit."
            )
            self.sequential_fallback = True
            await tender.controller.run_loop(max_steps=48)
            self.root_telemetry.emit("sequential_fallback_complete", failed_agents=failures,
                                     remaining=self.deadline.remaining)
        return failures

    def set_research_focus(self, role: str | None):
        if role is None:
            return
        if role not in self.specialists:
            raise ValueError(f"Unknown specialist role: {role}")
        if role == "tender":
            self.specialists[role].controller.role_instruction += (
                " This is a focused evidence-only rehearsal: after login, go directly to the observed Q&A/clarification "
                "view and traverse its relevant pages. Reveal date/content details, record the current page's relevant Q&A "
                "facts, then choose observed pagination controls. Use the exact citation_candidates returned by the relevant inspection results, including "
                "both answer and date observations when they differ. Never emit an empty record action. "
                "Do not inspect tender documents unless an observed Q&A entry explicitly requires it."
            )
        self.root_telemetry.emit("research_focus", role=role)

    async def retrieve_tan(self, submission):
        """Let the mail specialist retrieve the current TAN after the portal asks for it."""
        item = self.specialists["mail"]
        item.controller.research_only = False
        item.controller.submission = submission
        item.controller.role_instruction = (
            "The tender portal has requested a TAN. Find the newest matching signing message for the prepared tender, "
            "capture it using the secret TAN tool, then stop. Do not submit anything."
        )
        try:
            await item.controller.run_loop(max_steps=24)
            if item.browser.latest_tan:
                submission.browser.latest_tan = item.browser.latest_tan
                submission.browser.tan_captured_at = item.browser.tan_captured_at
                self.root_telemetry.emit("tan_handoff", from_agent="mail", to_agent="tender")
        finally:
            item.controller.research_only = True

    async def calculate_and_submit(self, steps=120):
        self.pricing = calculate(self.ledger, allow_partial=self.deadline.submission_due)
        if not self.pricing.answer and not self.deadline.submission_due:
            # A failed specialist must not kill the whole bid.  Give only the
            # missing evidence owners one bounded second pass, then recalculate.
            unresolved = " ".join(" ".join(values) for values in self.pricing.unresolved.values()).lower()
            roles = [role for role, words in {
                "tender": ("position", "quantity", "revision", "qa"),
                "specifications": ("requirement", "technical", "stroke"),
                "erp": ("material", "price", "stock", "search"),
                "mail": ("mail", "discount", "fx", "pool", "bonus", "packaging", "commitment"),
            }.items() if any(word in unresolved for word in words)]
            for role in roles[:2]:
                item = self.specialists[role]
                item.controller.role_instruction = ROLE_INSTRUCTIONS[role] + " The coordinator still has unresolved evidence; make one focused recovery pass using the shared ledger."
                await item.controller.run_loop(max_steps=20)
            self.pricing = calculate(self.ledger, allow_partial=self.deadline.submission_due)
        self.root_telemetry.emit("pricing_computed", result=self.pricing.model_dump(mode="json"), remaining=self.deadline.remaining)
        tender = self.specialists["tender"]
        tender.controller.research_only = False
        tender.controller.submission = self.submission
        tender.controller.pricing = self.pricing
        tender.controller.role_instruction = (
            "You own final submission. Use only the shared cited evidence and deterministic pricing already prepared. "
            "Map the current portal form, submit verified complete or explicitly partial lines, request the TAN only when ready, "
            "then inspect the portal receipt. Do not redo discretionary research."
        )
        tender.controller.tan_callback = self.retrieve_tan
        return await tender.controller.run_loop(max_steps=steps)

    async def close(self):
        for item in self.specialists.values():
            for resource in (item.browser, item.model, item.classifier):
                try:
                    await asyncio.wait_for(resource.close(), timeout=2)
                except Exception:
                    pass
            item.telemetry.close()
