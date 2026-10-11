"""Synthetic contract tests for the draft and the signing transaction.

Every value here is invented. Passing these tests proves local state handling
only; it is never evidence of an accepted or eligible challenge submission.
Fixtures were adapted after the parent review (observed inventory, checklist,
mail timestamps, receipt blocks); the blocker regressions are in test_review_blockers.
"""
import asyncio
import io
import unittest
from decimal import Decimal

from rfq_agent import draft as draft_module
from rfq_agent.deadline import DeadlineExceeded, RunClock
from rfq_agent.draft import DraftError, parse_numbers, validate_draft, validate_schema
from rfq_agent.redact import Redactor, RedactingStream, Secret
from rfq_agent.submission import Phase, SubmissionController, SubmissionError
from tests.test_review_blockers import BRIEF, CHECKLIST, EV as EVIDENCE, PORTAL, SCHEMA, Flow, good_draft as make_draft, omit_a_draft

RECEIPT = "Bid received for ZZ-TEST-001. Receipt R-77."


def check(candidate, capabilities=None):
    return validate_draft(candidate, SCHEMA, BRIEF, EVIDENCE, capabilities or {}, checklist=CHECKLIST)


class DraftTests(unittest.TestCase):
    def test_valid_partial_draft(self):
        valid = check(make_draft())
        self.assertEqual(valid.omitted, ("B",))
        self.assertEqual(valid.value("lines.0.unit"), Decimal("2.50"))
        self.assertEqual(valid.value("identity.company"), "Example Works Ltd")

    def test_runtime_schema_is_enforced(self):
        self.assertEqual(validate_schema({"ref": "x", "decision": "bid", "lines": [], "total": 1}, SCHEMA), [])
        self.assertTrue(validate_schema({"ref": 1, "decision": "maybe", "lines": [{}]}, SCHEMA))
        bad = make_draft(); bad["answer"]["extra"] = 1; bad["sources"]["extra"] = {"kind": "evidence", "evidence": [1]}
        with self.assertRaisesRegex(DraftError, "schema"):
            check(bad)

    def test_unsourced_zero_is_rejected(self):
        bad = make_draft(); del bad["sources"]["lines.0.surcharge"]
        with self.assertRaisesRegex(DraftError, "lines.0.surcharge"):
            check(bad)
        bad = make_draft(); bad["sources"]["lines.0.surcharge"] = {"kind": "rule", "quote": "surcharges default to zero"}
        with self.assertRaisesRegex(DraftError, "brief"):
            check(bad)

    def test_number_must_appear_in_cited_quote(self):
        bad = make_draft(); bad["answer"]["lines"][0]["unit"] = Decimal("2.40")
        with self.assertRaisesRegex(DraftError, "lines.0.unit"):
            check(bad)
        bad = make_draft(); bad["sources"]["lines.0.unit"] = {"kind": "interpretation", "evidence": [2], "reason": "guess"}
        with self.assertRaisesRegex(DraftError, "lines.0.unit"):
            check(bad)

    def test_decimal_total_consistency(self):
        bad = make_draft(); bad["answer"]["total"] = Decimal("10.01")
        with self.assertRaisesRegex(DraftError, "total"):
            check(bad)
        self.assertEqual(draft_module.evaluate("a * b + c", {"a": Decimal("0.1"), "b": Decimal("3"), "c": Decimal("0.2")}), Decimal("0.5"))
        with self.assertRaises(DraftError):
            draft_module.evaluate("__import__('os')", {})

    def test_locale_numbers(self):
        self.assertIn(Decimal("1234.56"), parse_numbers("Sum 1.234,56 EUR"))
        self.assertIn(Decimal("1234.56"), parse_numbers("Sum 1,234.56"))
        self.assertIn(Decimal("2.5"), parse_numbers("2,50"))

    def test_dependency_closure_required_for_priced_position(self):
        bad = make_draft(); bad["closure"]["A"] = {}
        with self.assertRaisesRegex(DraftError, "rebate"):
            check(bad)
        bad = make_draft(); bad["closure"]["A"]["rebate"] = {"status": "unknown"}
        with self.assertRaisesRegex(DraftError, "rebate"):
            check(bad)

    def test_every_position_is_priced_or_explicitly_omitted(self):
        bad = make_draft(); bad["omitted"] = []
        with self.assertRaisesRegex(DraftError, "B"):
            check(bad)

    def test_reference_is_exact_and_not_normalized(self):
        bad = make_draft(); bad["reference"] = "zz-test-001"
        with self.assertRaisesRegex(DraftError, "reference"):
            check(bad)
        bad = make_draft(); bad["answer"]["ref"] = "ZZ-TEST-0001"
        with self.assertRaisesRegex(DraftError, "reference"):
            check(bad)

    def test_identity_needs_runtime_evidence(self):
        bad = make_draft(); bad["identity"]["company"] = {"value": "Placeholder GmbH", "evidence": 4}
        with self.assertRaisesRegex(DraftError, "identity.company"):
            check(bad)

    def test_all_omitted_needs_observed_capability(self):
        with self.assertRaisesRegex(DraftError, "all_positions_omitted"):
            check(omit_a_draft())
        with self.assertRaisesRegex(DraftError, "all_positions_omitted"):
            check(omit_a_draft(), {"all_positions_omitted": {"supported": False, "quote": "x"}})
        valid = check(omit_a_draft(), {"all_positions_omitted": {"supported": True, "quote": "x"}})
        self.assertEqual(valid.omitted, ("A", "B"))

    def test_no_bid_cannot_come_from_unresolved_work(self):
        bad = omit_a_draft(); bad["answer"]["decision"] = "no_bid"; bad["no_bid"] = True
        with self.assertRaisesRegex(DraftError, "no_bid"):
            check(bad)


class Stage(Flow):
    """A controller advanced to a named point with synthetic observations."""

    pre_sign_text = "Review page ZZ-TEST-001 enter code"

    @property
    def controller(self):
        return self.c

    def filled(self):
        return self.fill()

    def reviewed(self):
        return self.fill().review()

    def tan_ready(self, value="482913"):
        return self.fill().review().tan(value)


class SubmissionStateTests(unittest.TestCase):
    def test_happy_path_reaches_accepted_only_through_every_phase(self):
        stage = Stage().signed()
        receipt = stage.controller.verify_receipt(PORTAL, RECEIPT, stage.tick(), RECEIPT, "R-77")
        self.assertEqual(stage.controller.phase, Phase.ACCEPTED)
        self.assertEqual(receipt["receipt_id"], "R-77")
        self.assertEqual([p.name for p in stage.controller.history], [
            "BOOT", "IDENTIFY", "PREPARE", "VALIDATE", "FILL", "REVIEW", "REQUEST_TAN", "READ_TAN", "SIGN",
            "VERIFY_RECEIPT", "ACCEPTED"])

    def test_wrong_reference_cannot_be_identified(self):
        controller = SubmissionController(PORTAL)
        with self.assertRaisesRegex(SubmissionError, "reference"):
            controller.identify("ZZ-TEST-999", BRIEF, EVIDENCE)
        controller.identify("ZZ-TEST-001", BRIEF, EVIDENCE)
        with self.assertRaisesRegex(SubmissionError, "portal"):
            controller.confirm_on_portal("https://elsewhere.test/x", "ZZ-TEST-001")
        with self.assertRaisesRegex(SubmissionError, "reference"):
            controller.confirm_on_portal(PORTAL, "Tender ZZ-TEST-002")

    def test_values_come_only_from_the_validated_draft(self):
        stage = Stage()
        with self.assertRaises(SubmissionError):
            stage.controller.value_for("lines.9.unit")
        with self.assertRaisesRegex(SubmissionError, "omitted"):
            stage.controller.note_omission("A")

    def test_review_must_match_draft_and_explicit_omissions(self):
        stage = Stage().filled()
        with self.assertRaisesRegex(SubmissionError, "lines.0.unit"):
            stage.review(readbacks={"identity.company": "Example Works Ltd", "lines.0.unit": "2,40"})
        with self.assertRaisesRegex(SubmissionError, "identity.company"):
            stage.review(readbacks={"lines.0.unit": "2.50"})
        with self.assertRaisesRegex(SubmissionError, "B"):
            stage.review(omission_quotes={})
        with self.assertRaisesRegex(SubmissionError, "visible"):
            stage.review(page_text="nothing here")
        with self.assertRaisesRegex(SubmissionError, "REVIEW"):
            stage.controller.request_tan("tender")
        self.assertEqual(stage.controller.phase, Phase.FILL)

    def test_omission_must_be_acted_on_in_the_ui_before_review(self):
        stage = Stage()
        stage.c.note_filled("identity.company", descriptor="ctl-company")
        stage.c.note_filled("lines.0.unit", descriptor="ctl-unit-A")
        with self.assertRaisesRegex(SubmissionError, "omission"):
            stage.review()

    def test_fill_after_review_invalidates_review(self):
        stage = Stage().reviewed()
        stage.controller.note_filled("lines.0.unit")
        self.assertEqual(stage.controller.phase, Phase.FILL)

    def test_only_the_tender_owner_requests_and_signs(self):
        stage = Stage().reviewed()
        with self.assertRaisesRegex(SubmissionError, "owner"):
            stage.controller.request_tan("mail")
        stage = Stage().tan_ready()
        with self.assertRaisesRegex(SubmissionError, "owner"):
            stage.controller.begin_sign("mail", "")

    def test_tan_must_match_tender_and_follow_the_request(self):
        stage = Stage().reviewed()
        c = stage.controller
        message, stamp = stage.mail()
        with self.assertRaisesRegex(SubmissionError, "REQUEST_TAN"):
            c.accept_tan("482913", message, stage.tick(), message=message, sent_at=stamp)
        before = stage.tick()
        c.request_tan("tender"); stage.tick()
        message, stamp = stage.mail()
        with self.assertRaisesRegex(SubmissionError, "before"):
            c.accept_tan("482913", message, before, message=message, sent_at=stamp)
        other = message.replace("ZZ-TEST-001", "ZZ-TEST-002")
        with self.assertRaisesRegex(SubmissionError, "reference"):
            c.accept_tan("482913", other, stage.tick(), message=other, sent_at=stamp)
        with self.assertRaisesRegex(SubmissionError, "one time"):
            c.accept_tan("222222", message, stage.tick(), message=message, sent_at=stamp)
        self.assertEqual(c.phase, Phase.REQUEST_TAN)

    def test_old_tan_is_refused_after_a_new_request(self):
        stage = Stage().tan_ready("482913")
        c = stage.controller
        c.request_tan("tender"); stage.tick()
        with self.assertRaisesRegex(SubmissionError, "SIGN|READ_TAN|TAN"):
            c.begin_sign("tender", "")
        message, stamp = stage.mail("482913")
        with self.assertRaisesRegex(SubmissionError, "earlier"):
            c.accept_tan("482913", message, stage.tick(), message=message, sent_at=stamp)
        message, stamp = stage.mail("700001")
        c.accept_tan("700001", message, stage.tick(), message=message, sent_at=stamp)
        self.assertEqual(c.tan_for_entry("tender").reveal(), "700001")

    def test_tan_never_appears_in_repr_or_snapshot(self):
        stage = Stage().tan_ready("482913")
        self.assertNotIn("482913", repr(stage.controller.tan_for_entry("tender")))
        self.assertNotIn("482913", repr(stage.controller.snapshot()))

    def test_draft_save_or_stale_receipt_is_not_acceptance(self):
        stage = Stage().reviewed()
        with self.assertRaisesRegex(SubmissionError, "SIGN"):
            stage.controller.verify_receipt(PORTAL, RECEIPT, stage.tick(), RECEIPT, "R-77")
        stage = Stage().signed()
        c = stage.controller
        with self.assertRaisesRegex(SubmissionError, "before"):
            c.verify_receipt(PORTAL, RECEIPT, 50.0, RECEIPT, "R-77")
        with self.assertRaisesRegex(SubmissionError, "already visible"):
            c.verify_receipt(PORTAL, stage.pre_sign_text, stage.tick(), stage.pre_sign_text, "R-77")
        with self.assertRaisesRegex(SubmissionError, "origin"):
            c.verify_receipt("https://mail.test/x", RECEIPT, stage.tick(), RECEIPT, "R-77")
        wrong = RECEIPT.replace("ZZ-TEST-001", "ZZ-TEST-002")
        with self.assertRaisesRegex(SubmissionError, "reference"):
            c.verify_receipt(PORTAL, wrong, stage.tick(), wrong, "R-77")
        with self.assertRaisesRegex(SubmissionError, "identifier"):
            c.verify_receipt(PORTAL, "Bid received for ZZ-TEST-001", stage.tick(), "Bid received for ZZ-TEST-001", "R-77")
        self.assertEqual(c.phase, Phase.SIGN)

    def test_uncertain_signing_is_not_repeated_before_observation(self):
        stage = Stage().signed()
        c = stage.controller
        with self.assertRaisesRegex(SubmissionError, "receipt or an explicit validation failure"):
            c.begin_sign("tender", "")
        with self.assertRaisesRegex(SubmissionError, "receipt or an explicit validation failure"):
            c.request_tan("tender")
        with self.assertRaisesRegex(SubmissionError, "already visible"):
            c.validation_failure(PORTAL, stage.pre_sign_text, stage.tick(), "enter code")
        c.validation_failure(PORTAL, "Error: signing code rejected", stage.tick(), "signing code rejected")
        self.assertEqual(c.phase, Phase.FILL)
        with self.assertRaises(SubmissionError):
            c.tan_for_entry("tender")
        self.assertEqual(c.sign_attempts, 1)

    def test_draft_revision_resets_review_and_tan(self):
        stage = Stage().tan_ready()
        stage.controller.reopen_draft("tender")
        self.assertEqual(stage.controller.phase, Phase.PREPARE)
        with self.assertRaises(SubmissionError):
            stage.controller.tan_for_entry("tender")

    def test_accepted_is_terminal(self):
        stage = Stage().signed()
        stage.controller.verify_receipt(PORTAL, RECEIPT, stage.tick(), RECEIPT, "R-77")
        with self.assertRaises(SubmissionError):
            stage.controller.reopen_draft("tender")


class ClockTests(unittest.IsolatedAsyncioTestCase):
    def clock(self, task, elapsed=0.0):
        self.mono = 1000.0
        clock = RunClock(task, monotonic=lambda: self.mono, wall=lambda: 5000.0)
        self.mono += elapsed
        return clock

    def test_research_cutoff_and_signing_reserve(self):
        clock = self.clock({})
        self.assertAlmostEqual(clock.research_left(), 12 * 60, delta=1)
        self.assertGreaterEqual(clock.left() - clock.research_left(), 6 * 60)
        self.mono += 13 * 60
        self.assertEqual(clock.research_left(), 0)
        self.assertGreater(clock.left(), 6 * 60)

    def test_live_expiry_shortens_budget_and_keeps_reserve(self):
        clock = self.clock({"expires_at": (5000.0 + 9 * 60) * 1000})
        self.assertLess(clock.left(), 9 * 60)
        self.assertLessEqual(clock.research_left(), 3 * 60)
        self.assertGreaterEqual(clock.left() - clock.research_left(), 6 * 60 - 1)

    def test_started_at_counts_elapsed_time(self):
        clock = self.clock({"started_at": (5000.0 - 11 * 60) * 1000})
        self.assertLessEqual(clock.research_left(), 60)
        self.assertLessEqual(clock.left(), 9 * 60)

    async def test_pending_call_is_cancelled_at_deadline(self):
        clock = RunClock({}, run_limit=0.2, research_limit=0.05, signing_reserve=0.1, exit_margin=0)
        cancelled = asyncio.Event()

        async def hang():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        loop = asyncio.get_running_loop()
        started = loop.time()
        with self.assertRaises(DeadlineExceeded):
            await clock.bounded(hang(), research=True)
        self.assertLess(loop.time() - started, 1)
        self.assertTrue(cancelled.is_set())
        with self.assertRaises(DeadlineExceeded):
            await clock.bounded(hang(), research=True)


class RedactionTests(unittest.TestCase):
    def test_stream_redacts_registered_secrets(self):
        redactor = Redactor()
        redactor.add("run-token-abcdef"); redactor.add(Secret("482913")); redactor.add("")
        stream = io.StringIO()
        wrapped = RedactingStream(stream, redactor)
        print("token run-token-abcdef code 482913 ok", file=wrapped)
        self.assertEqual(stream.getvalue(), "token [redacted] code [redacted] ok\n")
        self.assertEqual(repr(Secret("482913")), "[secret]")

    def test_environment_secrets_are_collected(self):
        redactor = Redactor.from_runtime(
            {"CHALLENGE_RUN_TOKEN": "tok-12345", "QWEN_API_KEY": "key-98765", "PATH": "/usr/bin"},
            [{"_credentials": {"username": "synthetic-user", "password": "synthetic-pass"}}])
        self.assertEqual(redactor.scrub("tok-12345 key-98765 synthetic-pass /usr/bin"), "[redacted] [redacted] [redacted] /usr/bin")


if __name__ == "__main__":
    unittest.main()
