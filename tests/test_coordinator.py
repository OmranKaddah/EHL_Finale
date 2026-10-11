"""Coordinator, draft preparation and model transport with synthetic stand-ins."""
import asyncio
import copy
import json
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from rfq_agent import coordinator, model, planner
from rfq_agent.deadline import DeadlineExceeded, RunClock
from rfq_agent.evidence import EvidenceLedger
from rfq_agent.redact import Redactor
from rfq_agent.submission import Phase, SubmissionController
from tests.test_review_blockers import BRIEF, CHECKLIST, EV as EVIDENCE, SCHEMA, good_draft as make_draft
from tests.test_submit_agent import TASK


def as_json(value):
    return json.dumps(value, default=float)


async def ledger_with_evidence():
    ledger = EvidenceLedger()
    for item in EVIDENCE:
        await ledger.add(item)
    return ledger


class FakePage:
    """A provided page that cannot be read: plain attributes only, so no coroutine is left un-awaited."""

    url = "https://portal.test/unreadable"
    frames: list = []

    class context:
        pages: list = []

    async def evaluate(self, *args, **kwargs):
        raise RuntimeError("synthetic unreadable page")

    def locator(self, *args, **kwargs):
        raise RuntimeError("synthetic unreadable page")


class PrepareDraftTests(unittest.IsolatedAsyncioTestCase):
    async def test_validation_errors_are_fed_back_until_the_draft_is_source_backed(self):
        bad = make_draft(); del bad["sources"]["lines.0.surcharge"]
        controller = SubmissionController("https://portal.test")
        controller.checklist = CHECKLIST
        with patch.object(model, "complete_with_retry", side_effect=[as_json(bad), as_json(make_draft())]) as call:
            await coordinator.prepare_draft(TASK, await ledger_with_evidence(), controller, RunClock({}), "")
        self.assertEqual(controller.phase, Phase.FILL)
        self.assertEqual(controller.draft.value("lines.0.unit"), Decimal("2.50"))
        self.assertIn("lines.0.surcharge", call.call_args_list[1].args[0][1]["content"])

    async def test_unresolvable_draft_never_becomes_a_bid(self):
        bad = make_draft(); bad["answer"]["lines"][0]["unit"] = Decimal("7.77")
        controller = SubmissionController("https://portal.test")
        controller.checklist = CHECKLIST
        with patch.object(model, "complete_with_retry", return_value=as_json(bad)):
            feedback = await coordinator.prepare_draft(TASK, await ledger_with_evidence(), controller, RunClock({}), "")
        self.assertIsNone(controller.draft)
        self.assertIn("lines.0.unit", feedback)
        self.assertNotIn(controller.phase, {Phase.FILL, Phase.REVIEW})


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_research_is_cancelled_at_cutoff_and_no_draft_means_no_submission(self):
        cancelled = []

        async def hanging_planner(task, page, assignment, ledger, **kwargs):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.append(assignment["site_id"])
                raise

        clock = RunClock({}, run_limit=1.2, research_limit=0.2, signing_reserve=1.0, exit_margin=0)
        connect = AsyncMock(side_effect=lambda index: FakePage())
        assignments = [{"site_id": "portal", "objective": "x"}, {"site_id": "mail", "objective": "y"}]
        started = asyncio.get_running_loop().time()
        with patch.object(planner, "plan_assignments", AsyncMock(return_value=assignments)), \
                patch.object(planner, "run_planner", hanging_planner), \
                patch.object(model, "complete_with_retry", AsyncMock(return_value="{}")):
            result = await coordinator.run(TASK, connect, 2, clock, Redactor())
        self.assertLess(asyncio.get_running_loop().time() - started, 2.5)
        self.assertEqual(sorted(cancelled), ["mail", "portal"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["sign_attempts"], 0)
        self.assertEqual(coordinator.exit_code(result), 1)

    async def test_only_an_observed_receipt_exits_zero(self):
        self.assertEqual(coordinator.exit_code({"status": "accepted", "receipt": {"receipt_id": "R"}}), 0)
        self.assertEqual(coordinator.exit_code({"status": "accepted", "receipt": None}), 1)
        self.assertEqual(coordinator.exit_code({"status": "unverified_signature"}), 1)

    async def test_api_submission_kind_is_not_improvised(self):
        task = dict(TASK, submission={"kind": "api", "url": "https://api.test/answer"})
        connect = AsyncMock()
        result = await coordinator.run(task, connect, 2, RunClock({}), Redactor())
        connect.assert_not_awaited()
        self.assertEqual(result["status"], "blocked")


class ChecklistAndInventoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_checklist_is_established_from_exact_brief_quotes(self):
        wrong = {"rules": [{"name": "pooling", "quote": "Setup cost is shared"}]}
        with patch.object(model, "complete_with_retry", side_effect=[as_json(wrong), as_json({"rules": CHECKLIST})]) as call:
            self.assertEqual(await coordinator.derive_checklist(TASK, RunClock({})), CHECKLIST)
        self.assertEqual(call.await_count, 2)
        with patch.object(model, "complete_with_retry", return_value=as_json(wrong)):
            self.assertIsNone(await coordinator.derive_checklist(TASK, RunClock({})))
        with patch.object(model, "complete_with_retry", return_value=as_json({"rules": []})):
            self.assertEqual(await coordinator.derive_checklist(TASK, RunClock({})), [])

    async def test_investigator_records_inventory_positions_with_their_identifier(self):
        observation = {"url": "https://portal.test/t", "title": "t", "visible_text": "Line A quantity 4 pieces", "targets": []}
        session = AsyncMock(); session.page = FakePage(); session.observe.return_value = observation
        replies = [{"action": "record_evidence", "claim": "line", "quote": "quantity 4 pieces", "kind": "position", "subject": "A"},
                   {"action": "record_evidence", "claim": "line", "quote": "Line A quantity 4 pieces", "kind": "position", "subject": "A"},
                   {"action": "finish", "reason": "done"}]
        ledger = EvidenceLedger()
        with patch.object(planner, "InvestigationSession", return_value=session), \
                patch.object(model, "complete_with_retry", side_effect=[as_json(r) for r in replies]):
            await planner.run_planner(TASK, session.page, {"site_id": "portal"}, ledger, 3)
        self.assertEqual([(item.kind, item.subject) for item in await ledger.snapshot()], [("position", "A")])


class ModelTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_hung_model_call_is_cancelled_by_the_run_clock(self):
        cancelled = asyncio.Event()

        async def hang(messages, timeout=0):
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        clock = RunClock({}, run_limit=0.2, research_limit=0.1, signing_reserve=0.05, exit_margin=0)
        with patch.object(model, "complete", hang):
            with self.assertRaises((DeadlineExceeded, TimeoutError)):
                await clock.bounded(model.complete_with_retry([], 30, clock.left))
        self.assertTrue(cancelled.is_set())

    async def test_model_client_uses_only_the_run_proxy(self):
        with patch.dict("os.environ", {"QWEN_BASE_URL": "https://proxy.test/v1", "QWEN_API_KEY": "synthetic"}, clear=True):
            self.assertEqual(str(model.client().base_url).rstrip("/"), "https://proxy.test/v1")
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(KeyError):
                model.client()

    async def test_planner_honours_the_coordinator_budget(self):
        with patch.object(model, "complete_with_retry", AsyncMock()) as call:
            result = await planner.run_planner(TASK, FakePage(), {"site_id": "portal"}, EvidenceLedger(), budget=lambda: 0)
        call.assert_not_awaited()
        self.assertIn("budget", result["stop_reason"])


if __name__ == "__main__":
    unittest.main()
