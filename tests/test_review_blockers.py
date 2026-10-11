"""Regression tests for the parent review's blockers (controller, draft, mail, schema).

All values are invented. These prove local checks only, never an eligible submission.
"""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from rfq_agent.draft import DraftError, validate_draft, validate_schema
from rfq_agent.evidence import Evidence
from rfq_agent.submission import Phase, SubmissionController, SubmissionError

REF = "ZZ-TEST-001"
BRIEF = ("Synthetic brief for tender ZZ-TEST-001. Report a surcharge of 0 when none applies. "
         "Whole-order rebate applies above a threshold. Setup cost is pooled across lines of one family. "
         "The tender is open for bids.")
PORTAL = "https://portal.test/tenders/1"
SCHEMA = {
    "type": "object", "required": ["ref", "decision", "lines", "total"], "additionalProperties": False,
    "properties": {
        "ref": {"type": "string"}, "decision": {"enum": ["bid", "no_bid"]}, "total": {"type": "number"},
        "lines": {"type": "array", "items": {
            "type": "object", "required": ["line", "qty", "unit"],
            "properties": {"line": {"type": "string"}, "qty": {"type": "integer"},
                           "unit": {"type": "number"}, "surcharge": {"type": "number"}}}},
    },
}
EV = [
    Evidence("reference", "Tender ZZ-TEST-001 is open", "portal", PORTAL, "t", 1),
    Evidence("line A", "Line A quantity 4 pieces", "portal", PORTAL, "t", 2, kind="position", subject="A"),
    Evidence("price", "Base price 2,50 EUR per piece", "erp", "https://erp.test/a", "t", 3),
    Evidence("rebate", "Order value stays below the rebate threshold", "erp", "https://erp.test/b", "t", 4),
    Evidence("bidder", "Registered bidder: Example Works Ltd", "portal", PORTAL, "t", 5),
    Evidence("line B", "Line B quantity 2 pieces", "portal", PORTAL, "t", 6, kind="position", subject="B"),
    Evidence("family", "Line A is the only line of its family", "erp", "https://erp.test/c", "t", 7),
    Evidence("search A", "Catalogue search for line A: no active exact match", "erp", "https://erp.test/s", "t", 8,
             kind="catalogue_search", subject="A"),
    Evidence("search B", "Catalogue search for line B: no active exact match", "erp", "https://erp.test/s2", "t", 9,
             kind="catalogue_search", subject="B"),
]
CHECKLIST = [{"name": "rebate", "quote": "Whole-order rebate applies above a threshold"},
             {"name": "pooling", "quote": "Setup cost is pooled across lines of one family"}]


def good_draft():
    return {
        "reference": REF,
        "answer": {"ref": REF, "decision": "bid", "total": Decimal("10.00"),
                   "lines": [{"line": "A", "qty": 4, "unit": Decimal("2.50"), "surcharge": 0}]},
        "sources": {
            "ref": {"kind": "evidence", "evidence": [0]},
            "decision": {"kind": "interpretation", "evidence": [1, 2], "reason": "one line is resolved"},
            "lines.0.line": {"kind": "evidence", "evidence": [1]},
            "lines.0.qty": {"kind": "evidence", "evidence": [1]},
            "lines.0.unit": {"kind": "evidence", "evidence": [2]},
            "lines.0.surcharge": {"kind": "rule", "quote": "Report a surcharge of 0 when none applies"},
            "total": {"kind": "calculation", "expression": "qty * unit",
                      "inputs": {"qty": {"path": "lines.0.qty"}, "unit": {"path": "lines.0.unit"}}},
        },
        "identity": {"company": {"value": "Example Works Ltd", "evidence": 4}},
        "tender_positions": ["A", "B"],
        "priced": [{"id": "A", "path": "lines.0"}],
        "omitted": [{"position": "B", "reason": "price inputs unresolved"}],
        "closure": {"A": {"rebate": {"status": "not_applicable", "evidence": [3]},
                          "pooling": {"status": "not_applicable", "evidence": [6]}}},
    }


def omit_a_draft():
    candidate = good_draft()
    candidate["answer"]["lines"] = []
    candidate["answer"]["total"] = Decimal("0")
    candidate["sources"] = {key: value for key, value in candidate["sources"].items() if not key.startswith("lines")}
    candidate["sources"]["total"] = {"kind": "empty_total"}
    candidate["priced"], candidate["closure"] = [], {}
    candidate["omitted"] = [{"position": "A", "reason": "dropped"}, {"position": "B", "reason": "unresolved"}]
    return candidate


def check(candidate, capabilities=None, checklist=CHECKLIST, evidence=EV):
    return validate_draft(candidate, SCHEMA, BRIEF, evidence, capabilities or {}, checklist=checklist)


class NumericProvenanceTests(unittest.TestCase):
    def test_unrelated_brief_quote_cannot_back_a_number(self):
        bad = good_draft()
        bad["answer"]["lines"][0]["unit"] = Decimal("999")
        bad["answer"]["total"] = Decimal("3996")
        bad["sources"]["lines.0.unit"] = {"kind": "rule", "quote": "The tender is open for bids"}
        with self.assertRaisesRegex(DraftError, "lines.0.unit"):
            check(bad)

    def test_literal_only_calculation_is_refused(self):
        bad = good_draft()
        bad["sources"]["lines.0.unit"] = {"kind": "calculation", "expression": "2.5", "inputs": {}}
        with self.assertRaisesRegex(DraftError, "lines.0.unit"):
            check(bad)
        bad = good_draft()
        bad["sources"]["total"] = {"kind": "calculation", "expression": "qty * 2.5", "inputs": {"qty": {"path": "lines.0.qty"}}}
        with self.assertRaisesRegex(DraftError, "total"):
            check(bad)

    def test_circular_calculation_is_refused(self):
        bad = good_draft()
        bad["sources"]["lines.0.unit"] = {"kind": "calculation", "expression": "total / qty",
                                          "inputs": {"total": {"path": "total"}, "qty": {"path": "lines.0.qty"}}}
        with self.assertRaisesRegex(DraftError, "circular"):
            check(bad)

    def test_ordinary_price_arithmetic_still_validates(self):
        ok = good_draft()
        ok["sources"]["total"] = {"kind": "calculation", "expression": "qty * unit * (1 - pct / 100)",
                                  "inputs": {"qty": {"path": "lines.0.qty"}, "unit": {"path": "lines.0.unit"},
                                             "pct": {"value": "0", "quote": "Report a surcharge of 0 when none applies"}}}
        self.assertEqual(check(ok).priced, (("A", "lines.0"),))


class InventoryAndChecklistTests(unittest.TestCase):
    def test_observed_position_cannot_be_dropped_by_the_draft(self):
        bad = good_draft()
        bad["omitted"] = []
        bad["tender_positions"] = ["A"]
        with self.assertRaisesRegex(DraftError, r"\bB\b"):
            check(bad)

    def test_inventory_must_have_been_observed(self):
        with self.assertRaisesRegex(DraftError, "inventory"):
            check(good_draft(), evidence=[item if item.kind != "position" else Evidence(item.claim, item.quote, item.site_id, item.url, item.title, item.step) for item in EV])

    def test_established_checklist_cannot_be_emptied_by_the_draft(self):
        bad = good_draft()
        bad["cross_position_rules"] = []
        bad["closure"] = {}
        with self.assertRaisesRegex(DraftError, "pooling"):
            check(bad)
        with self.assertRaisesRegex(DraftError, "checklist"):
            check(good_draft(), checklist=None)

    def test_no_bid_needs_catalogue_search_evidence_for_every_position(self):
        bad = omit_a_draft()
        bad["answer"]["decision"] = "no_bid"
        bad["omitted"] = []
        bad["no_bid"] = True
        bad["no_bid_basis"] = {"evidence": [0], "quote": "The tender is open for bids"}
        with self.assertRaisesRegex(DraftError, "no_bid"):
            check(bad)
        bad["no_bid_basis"] = {"searches": {"A": [7]}}
        with self.assertRaisesRegex(DraftError, "no_bid"):
            check(bad)
        bad["no_bid_basis"] = {"searches": {"A": [7], "B": [8]}}
        self.assertTrue(check(bad).no_bid)

    def test_genuine_partial_omission_still_validates(self):
        self.assertEqual(check(good_draft()).omitted, ("B",))


class SchemaTests(unittest.TestCase):
    def test_not_and_unique_items_are_enforced(self):
        self.assertTrue(validate_schema({"a": 1}, {"type": "object", "not": {"required": ["a"]}}))
        self.assertTrue(validate_schema([1, 1], {"type": "array", "uniqueItems": True}))

    def test_ref_siblings_and_missing_refs(self):
        schema = {"$defs": {"n": {"type": "number"}}, "type": "object",
                  "properties": {"x": {"$ref": "#/$defs/n", "minimum": 5}}}
        self.assertTrue(validate_schema({"x": 1}, schema))
        self.assertEqual(validate_schema({"x": Decimal("5.5")}, schema), [])
        self.assertTrue(validate_schema({"x": 1}, {"type": "object", "properties": {"x": {"$ref": "#/$defs/missing"}}}))

    def test_remote_refs_are_never_fetched(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network fetch attempted")):
            self.assertTrue(validate_schema({"x": 1}, {"properties": {"x": {"$ref": "https://schemas.test/remote.json"}}}))

    def test_decimal_values_and_float_bounds(self):
        schema = {"type": "object", "properties": {"p": {"type": "number", "minimum": 0.5, "multipleOf": 0.01}, "q": {"type": "integer"}}}
        self.assertEqual(validate_schema({"p": Decimal("2.50"), "q": 4}, schema), [])
        self.assertTrue(validate_schema({"p": Decimal("0.25"), "q": Decimal("1.5")}, schema))


class Flow:
    """A controller with synthetic monotonic and wall clocks."""

    PAGE = ("Summary ZZ-TEST-001 Company Example Works Ltd Line A quantity 4 Line A unit 2,50 "
            "Line A surcharge 0,00 Line B: not offered Total 10,00")

    def __init__(self, draft=None):
        self.mono = 100.0
        self.wall = datetime(2026, 1, 5, 12, 0, 0, tzinfo=timezone.utc)
        self.c = SubmissionController(PORTAL, clock=lambda: self.mono, wall=lambda: self.wall)
        self.c.checklist = CHECKLIST
        self.c.identify(REF, BRIEF, EV)
        self.c.confirm_on_portal(PORTAL, "Tender ZZ-TEST-001 configurator")
        self.c.note_observed("Tender ZZ-TEST-001 Line A: steel bracket Line B: steel washer")
        self.c.accept_draft(draft or good_draft(), SCHEMA, BRIEF, EV)

    def tick(self, seconds=1.0):
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)
        return self.mono

    def fill(self):
        self.c.note_filled("identity.company", descriptor="ctl-company", shown="Example Works Ltd")
        self.c.note_filled("lines.0.unit", descriptor="ctl-unit-A", shown="2,50")
        self.c.note_omission("B", descriptor="ctl-omit-B", state="true")
        return self

    def review(self, **changes):
        arguments = dict(
            readbacks={"identity.company": "Example Works Ltd", "lines.0.unit": "2,50"},
            omission_quotes={"B": "Line B: not offered"}, page_text=self.PAGE,
            static={"lines.0.qty": "Line A quantity 4", "lines.0.surcharge": "Line A surcharge 0,00", "total": "Total 10,00"},
            descriptors={"identity.company": "ctl-company", "lines.0.unit": "ctl-unit-A"})
        arguments.update(changes)
        self.c.review(arguments.pop("readbacks"), arguments.pop("omission_quotes"), arguments.pop("page_text"), **arguments)
        return self

    def mail(self, value="482913", stamp=None, extra=""):
        stamp = stamp or (self.wall + timedelta(seconds=20)).strftime("%Y-%m-%d %H:%M:%S UTC")
        return f"Signing code for ZZ-TEST-001: {value} Sent {stamp}{extra}", stamp

    def tan(self, value="482913", **changes):
        self.c.request_tan("tender")
        self.tick(30)
        message, stamp = self.mail(value)
        arguments = dict(message=message, sent_at=stamp)
        arguments.update(changes)
        self.c.accept_tan(value, "Inbox " + arguments["message"], self.tick(), **arguments)
        return self

    def signed(self):
        self.fill().review().tan()
        self.c.begin_sign("tender", "Review page ZZ-TEST-001 enter code")
        self.tick()
        return self


class ReceiptSemanticsTests(unittest.TestCase):
    def test_rejection_page_with_a_ticket_id_is_not_a_receipt(self):
        flow = Flow().signed()
        text = "Error: submission rejected for ZZ-TEST-001. Ticket E-9913"
        with self.assertRaises(SubmissionError):
            flow.c.verify_receipt(PORTAL, text, flow.tick(), "submission rejected for ZZ-TEST-001. Ticket E-9913", "E-9913")
        self.assertEqual(flow.c.phase, Phase.SIGN)

    def test_saved_draft_confirmation_is_not_a_receipt(self):
        flow = Flow().signed()
        text = "Draft D-204 saved for ZZ-TEST-001"
        with self.assertRaises(SubmissionError):
            flow.c.verify_receipt(PORTAL, text, flow.tick(), text, "D-204")

    def test_receipt_must_tie_acceptance_identifier_and_reference_together(self):
        flow = Flow().signed()
        text = "Bid received. Tender ZZ-TEST-001. Session S-1234 expires soon."
        with self.assertRaises(SubmissionError):
            flow.c.verify_receipt(PORTAL, text, flow.tick(), "Bid received", "S-1234")

    def test_success_text_is_not_a_validation_failure(self):
        flow = Flow().signed()
        text = "Bid received for ZZ-TEST-001. Receipt R-77."
        with self.assertRaises(SubmissionError):
            flow.c.validation_failure(PORTAL, text, flow.tick(), "Bid received for ZZ-TEST-001. Receipt R-77.")
        self.assertEqual(flow.c.phase, Phase.SIGN)

    def test_positive_receipts_and_explicit_failures_are_recognized(self):
        for text, receipt_id in (("Bid received for ZZ-TEST-001. Receipt R-77.", "R-77"),
                                 ("Ihr Angebot zu ZZ-TEST-001 wurde erfolgreich übermittelt. Belegnummer B-5521", "B-5521")):
            flow = Flow().signed()
            flow.c.verify_receipt(PORTAL, text, flow.tick(), text, receipt_id)
            self.assertEqual(flow.c.phase, Phase.ACCEPTED)
        flow = Flow().signed()
        flow.c.validation_failure(PORTAL, "Error: signing code rejected", flow.tick(), "Error: signing code rejected")
        self.assertEqual(flow.c.phase, Phase.FILL)


class TanMailTests(unittest.TestCase):
    def requested(self):
        flow = Flow().fill().review()
        flow.c.request_tan("tender")
        flow.tick(30)
        return flow

    def test_old_mail_opened_after_the_request_is_refused(self):
        flow = self.requested()
        message = "Signing code for ZZ-TEST-001: 482913 Sent 2026-01-05 11:40:00 UTC"
        with self.assertRaisesRegex(SubmissionError, "request"):
            flow.c.accept_tan("482913", message, flow.tick(), message=message, sent_at="2026-01-05 11:40:00 UTC")
        self.assertEqual(flow.c.phase, Phase.REQUEST_TAN)

    def test_mail_list_with_several_codes_is_ambiguous(self):
        flow = self.requested()
        message = ("ZZ-TEST-002 signing code 111111 12:00 "
                   "ZZ-TEST-001 signing code 482913 Sent 2026-01-05 12:00:20 UTC")
        with self.assertRaisesRegex(SubmissionError, "one"):
            flow.c.accept_tan("482913", message, flow.tick(), message=message, sent_at="2026-01-05 12:00:20 UTC")

    def test_code_of_an_earlier_request_is_stale(self):
        flow = Flow().fill().review().tan("482913")
        first, stamp = flow.mail("482913", stamp="2026-01-05 12:00:20 UTC")
        flow.tick(240)
        flow.c.request_tan("tender")
        flow.tick(20)
        with self.assertRaises(SubmissionError):
            flow.c.accept_tan("482913", first, flow.tick(), message=first, sent_at=stamp)
        other, stamp = flow.mail("700001", stamp="2026-01-05 12:00:20 UTC")
        with self.assertRaisesRegex(SubmissionError, "request"):
            flow.c.accept_tan("700001", other, flow.tick(), message=other, sent_at=stamp)

    def test_fresh_single_matching_mail_is_accepted_and_validity_is_enforced(self):
        flow = Flow().fill().review()
        message, stamp = None, None
        flow.c.request_tan("tender")
        flow.tick(30)
        message, stamp = flow.mail(extra=" This code is valid for 5 minutes.")
        with self.assertRaisesRegex(SubmissionError, "validity"):
            flow.c.accept_tan("482913", message, flow.tick(), message=message, sent_at=stamp)
        flow.c.accept_tan("482913", message, flow.tick(), message=message, sent_at=stamp, validity="valid for 5 minutes")
        self.assertEqual(flow.c.tan_for_entry("tender").reveal(), "482913")
        flow.tick(6 * 60)
        with self.assertRaisesRegex(SubmissionError, "expired"):
            flow.c.tan_for_entry("tender")
        with self.assertRaisesRegex(SubmissionError, "expired"):
            flow.c.begin_sign("tender", "")

    def test_local_time_with_stated_zone_and_relative_age(self):
        flow = self.requested()
        message = "Signaturcode für ZZ-TEST-001: 482913 Gesendet 05.01.2026 13:00 MEZ"
        flow.c.accept_tan("482913", message, flow.tick(), message=message, sent_at="05.01.2026 13:00 MEZ")
        flow = self.requested()
        message = "Signaturcode für ZZ-TEST-001: 482913 vor 1 Minute"
        with self.assertRaisesRegex(SubmissionError, "request"):
            flow.c.accept_tan("482913", message, flow.tick(), message=message, sent_at="vor 1 Minute")
        message = "Signaturcode für ZZ-TEST-001: 482913 vor 10 Sekunden"
        flow.c.accept_tan("482913", message, flow.tick(), message=message, sent_at="vor 10 Sekunden")
        self.assertEqual(flow.c.phase, Phase.READ_TAN)

    def test_unzoned_timestamp_must_still_fall_in_the_request_window(self):
        flow = self.requested()
        message = "Signaturcode für ZZ-TEST-001: 482913 Gesendet 05.01.2026 12:40"
        with self.assertRaisesRegex(SubmissionError, "request"):
            flow.c.accept_tan("482913", message, flow.tick(), message=message, sent_at="05.01.2026 12:40")
        message = "Signaturcode für ZZ-TEST-001: 482913 Gesendet 05.01.2026 13:00"
        flow.c.accept_tan("482913", message, flow.tick(), message=message, sent_at="05.01.2026 13:00")
        self.assertEqual(flow.c.phase, Phase.READ_TAN)

    def test_message_must_be_given_and_visible(self):
        flow = self.requested()
        with self.assertRaises(SubmissionError):
            flow.c.accept_tan("482913", "Signing code for ZZ-TEST-001: 482913", flow.tick())


class ReviewBindingTests(unittest.TestCase):
    def test_identifier_only_entry_cannot_pass_review(self):
        flow = Flow()
        flow.c.note_filled("lines.0.line", descriptor="ctl-line-A", shown="A")
        flow.c.note_omission("B", descriptor="ctl-omit-B", state="true")
        with self.assertRaisesRegex(SubmissionError, "lines.0.unit"):
            flow.c.review({"lines.0.line": "A"}, {"B": "Line B: not offered"}, Flow.PAGE)

    def test_ordinary_line_description_is_not_an_omission(self):
        flow = Flow().fill()
        with self.assertRaisesRegex(SubmissionError, "B"):
            flow.review(omission_quotes={"B": "Line B: steel washer"}, page_text=Flow.PAGE + " Line B: steel washer")
        self.assertEqual(flow.c.phase, Phase.FILL)

    def test_readback_from_another_control_is_a_path_swap(self):
        flow = Flow().fill()
        with self.assertRaisesRegex(SubmissionError, "lines.0.unit"):
            flow.review(descriptors={"identity.company": "ctl-company", "lines.0.unit": "ctl-company"})

    def test_static_summary_with_collected_pages_passes_and_binds_a_hash(self):
        flow = Flow().fill()
        flow.c.collect({"identity.company": "Example Works Ltd"}, "Page 1 Company", descriptors={"identity.company": "ctl-company"})
        flow.c.collect({"lines.0.unit": "2,50"}, "Page 2 prices", descriptors={"lines.0.unit": "ctl-unit-A"})
        static = {"lines.0.qty": "Line A quantity 4", "lines.0.surcharge": "Line A surcharge 0,00", "total": "Total 10,00",
                  "lines.0.unit": "Line A unit 2,50"}
        flow.review(readbacks={}, descriptors={}, static=static)
        self.assertEqual(flow.c.phase, Phase.REVIEW)
        first = flow.c.review_hash
        self.assertTrue(first)
        flow.c.invalidate_review("a field changed after review")
        self.assertEqual(flow.c.phase, Phase.FILL)
        self.assertIsNone(flow.c.review_hash)

    def test_static_quote_must_show_the_value_for_that_position(self):
        flow = Flow().fill()
        with self.assertRaisesRegex(SubmissionError, "total"):
            flow.review(static={"lines.0.qty": "Line A quantity 4", "lines.0.surcharge": "Line A surcharge 0,00", "total": "Line A quantity 4"})
        with self.assertRaisesRegex(SubmissionError, "lines.0.qty"):
            flow.review(static={"lines.0.qty": "Total 10,00 and 4 items", "lines.0.surcharge": "Line A surcharge 0,00", "total": "Total 10,00"},
                        page_text=Flow.PAGE + " Total 10,00 and 4 items")

    def test_unbound_values_and_empty_required_controls_block_review(self):
        flow = Flow().fill()
        with self.assertRaisesRegex(SubmissionError, "VAT"):
            flow.review(empty_required=["VAT number"])
        with self.assertRaisesRegex(SubmissionError, "Discount"):
            flow.review(unbound=["Discount"])

    def test_mutation_after_review_voids_review_and_tan(self):
        flow = Flow().fill().review().tan()
        flow.c.invalidate_review("a dropdown changed")
        self.assertEqual(flow.c.phase, Phase.FILL)
        with self.assertRaises(SubmissionError):
            flow.c.tan_for_entry("tender")
        with self.assertRaises(SubmissionError):
            flow.c.begin_sign("tender", "")

    def test_revised_draft_requires_clearing_superseded_live_values(self):
        flow = Flow().fill()
        flow.c.reopen_draft("tender")
        flow.c.capabilities["all_positions_omitted"] = {"supported": True, "quote": "x"}
        flow.c.accept_draft(omit_a_draft(), SCHEMA, BRIEF, EV)
        flow.c.note_omission("A", descriptor="ctl-omit-A", state="true")
        page = "Summary ZZ-TEST-001 Line A: not offered Line B: not offered Total 0,00"
        arguments = dict(readbacks={"identity.company": "Example Works Ltd"}, descriptors={"identity.company": "ctl-company"},
                         static={"total": "Total 0,00"}, page_text=page)
        quotes = {"A": "Line A: not offered", "B": "Line B: not offered"}
        flow.c.note_filled("identity.company", descriptor="ctl-company", shown="Example Works Ltd")
        with self.assertRaisesRegex(SubmissionError, "superseded"):
            flow.review(omission_quotes=quotes, **arguments)
        flow.c.note_cleared("ctl-unit-A")
        stale = dict(arguments, page_text=page + " Line A: not offered 2,50")
        with self.assertRaisesRegex(SubmissionError, "A"):
            flow.review(omission_quotes={"A": "Line A: not offered 2,50", "B": "Line B: not offered"}, **stale)
        flow.review(omission_quotes=quotes, **arguments)
        self.assertEqual(flow.c.phase, Phase.REVIEW)


if __name__ == "__main__":
    unittest.main()
