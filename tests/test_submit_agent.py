"""Synthetic portal/mail pages driven through the model-directed submission agent.

All pages and values are invented. A green run here shows the local transaction
logic only and must never be reported as an accepted or eligible submission.
"""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from rfq_agent import model, planner
from rfq_agent.deadline import RunClock
from rfq_agent.documents import InvestigationSession
from rfq_agent.evidence import EvidenceLedger
from rfq_agent.redact import Redactor
from rfq_agent.submission import Phase, SubmissionController
from rfq_agent.submit_agent import SubmissionAgent, read_tan
from datetime import datetime, timedelta, timezone

from tests.test_review_blockers import BRIEF, CHECKLIST, EV as EVIDENCE, SCHEMA, good_draft as make_draft

PORTAL_URL = "https://portal.test/tenders/1"
PORTAL_HTML = """<h1>Tender ZZ-TEST-001</h1>
<label>Company <input id="co"></label>
<table><tr><td>Line A: steel bracket, quantity 4</td><td><label>Unit price <input id="pa"></label></td>
<td><label>Surcharge <input id="sa"></label></td></tr>
<tr><td>Line B: steel washer</td><td><label><input type="checkbox" id="ob"> Do not offer line B</label></td></tr></table>
<button type="button" id="rev" onclick="summary.innerText = 'Line A quantity 4 Total 10,00'">Show summary</button>
<div id="summary"></div>
<button type="button" id="tanreq" onclick="window.requests=(window.requests||0)+1">Request signing code</button>
<label>Signing code <input id="tan"></label>
<button type="submit" id="sign" onclick="window.signs=(window.signs||0)+1;
  if (tan.value === '482913') { document.body.innerHTML = '<p>Bid received for ZZ-TEST-001. Receipt R-77.</p>'; }
  else { err.innerText = 'Error: signing code rejected'; }">Sign and submit bid</button>
<p id="err"></p>"""
RECEIPT = "Bid received for ZZ-TEST-001. Receipt R-77."
SUMMARY = "Line A quantity 4 Total 10,00"


def stamp(offset=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).strftime("%Y-%m-%d %H:%M:%S UTC")


TASK = {"brief": BRIEF, "answer_schema": SCHEMA, "submission": {"kind": "site", "url": "https://portal.test"},
        "access": [{"siteId": "portal", "url": "https://portal.test"}, {"siteId": "mail", "url": "https://mail.test"}]}


class SubmitAgentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context()
        await self.context.route("https://portal.test/**", lambda route: route.fulfill(body=PORTAL_HTML, content_type="text/html"))
        self.fresh_mail = f"Signing code for ZZ-TEST-001: 482913 Sent {stamp()}"
        self.mail_list = f"Signing code for ZZ-TEST-002: 111111 Sent {stamp(-900)} | {self.fresh_mail}"
        await self.context.route("https://mail.test/**", lambda route: route.fulfill(
            body=f"<p>{self.mail_list}</p>", content_type="text/html"))
        self.page = await self.context.new_page()
        await self.page.goto(PORTAL_URL)
        self.sites = planner.normalize_sites(TASK["access"])
        self.redactor = Redactor()
        self.controller = SubmissionController("https://portal.test", redactor=self.redactor)
        self.controller.checklist = CHECKLIST
        self.controller.identify("ZZ-TEST-001", BRIEF, EVIDENCE)
        self.controller.confirm_on_portal(PORTAL_URL, "Tender ZZ-TEST-001")
        self.controller.accept_draft(make_draft(), SCHEMA, BRIEF, EVIDENCE)
        self.mail_value = "482913"

        async def fake_mail():
            sent = stamp()
            message = f"Signing code for ZZ-TEST-001: {self.mail_value} Sent {sent}"
            self.controller.accept_tan(self.mail_value, message, self.controller.now(), message=message, sent_at=sent)
            return "TAN captured"

        self.session = InvestigationSession(self.page, self.sites)
        self.agent = SubmissionAgent(TASK, self.session, self.controller, EvidenceLedger(), RunClock({}),
                                     self.redactor, read_tan=fake_mail)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def act(self, kind, element=None, **fields):
        observation = await self.agent.observe()
        action = {"action": kind, **fields}
        if element:
            action["target"] = next(t["id"] for t in observation["targets"] if t["element_id"] == element)
        return await self.agent.handle(action, observation)

    async def target(self, element):
        observation = await self.agent.observe()
        return next(t["id"] for t in observation["targets"] if t["element_id"] == element)

    async def enter_all(self, comma=False):
        await self.act("enter_value", "co", path="identity.company")
        await self.act("enter_value", "pa", path="lines.0.unit", decimal_comma=comma)
        await self.act("enter_value", "sa", path="lines.0.surcharge")
        await self.act("omit_position", "ob", position="B")
        await self.act("click", "rev")

    async def review(self):
        fields = [{"path": "identity.company", "target": await self.target("co")},
                  {"path": "lines.0.unit", "target": await self.target("pa")},
                  {"path": "lines.0.surcharge", "target": await self.target("sa")},
                  {"path": "lines.0.qty", "quote": SUMMARY}, {"path": "total", "quote": SUMMARY}]
        return await self.act("review", fields=fields, omissions=[])

    async def fill_and_review(self):
        await self.enter_all(comma=True)
        await self.review()

    async def test_investigation_session_keeps_the_signing_guard(self):
        with self.assertRaisesRegex(ValueError, "MVP safety"):
            await InvestigationSession(self.page, self.sites).apply(
                {"action": "click", "target": await self.target("sign")}, "portal")
        self.assertIsNone(await self.page.evaluate("window.signs"))

    async def test_final_controls_are_gated_by_submission_state(self):
        with self.assertRaisesRegex(ValueError, "sign or request_tan action"):
            await self.act("click", "sign")
        with self.assertRaisesRegex(ValueError, "READ_TAN"):
            await self.act("sign", "sign")
        with self.assertRaisesRegex(ValueError, "REVIEW"):
            await self.act("request_tan", "tanreq")
        with self.assertRaisesRegex(ValueError, "enter_value"):
            await self.act("fill", "pa", value="1.00")
        self.assertIsNone(await self.page.evaluate("window.signs"))
        self.assertIsNone(await self.page.evaluate("window.requests"))

    async def test_synthetic_transaction_reaches_accepted_with_one_signature(self):
        await self.fill_and_review()
        self.assertEqual(await self.page.locator("#pa").input_value(), "2,50")
        self.assertEqual(self.controller.phase, Phase.REVIEW)
        await self.act("request_tan", "tanreq")
        self.assertEqual(self.controller.phase, Phase.READ_TAN)
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            await self.act("enter_tan", "tan")
            observation = await self.agent.observe()
            prompt = self.agent.prompt(observation, "")
            await self.act("sign", "sign")
        self.assertNotIn("482913", log.getvalue() + prompt)
        await self.act("confirm_receipt", excerpt=RECEIPT, receipt_id="R-77")
        self.assertEqual(self.controller.phase, Phase.ACCEPTED)
        self.assertEqual(await self.page.evaluate("window.signs"), 1)

    async def test_review_reads_live_controls_not_model_claims(self):
        await self.enter_all()
        await self.page.locator("#pa").fill("9.99")
        with self.assertRaisesRegex(ValueError, "lines.0.unit"):
            await self.review()

    async def test_stale_control_requires_new_observation(self):
        observation = await self.agent.observe()
        target = next(t["id"] for t in observation["targets"] if t["element_id"] == "pa")
        await self.page.evaluate("document.getElementById('pa').remove()")
        with self.assertRaisesRegex(ValueError, "stale"):
            await self.agent.handle({"action": "enter_value", "target": target, "path": "lines.0.unit"}, observation)
        self.assertNotIn("lines.0.unit", self.controller.filled)

    async def test_signing_timeout_observes_receipt_and_never_resigns(self):
        await self.fill_and_review()
        await self.act("request_tan", "tanreq")
        await self.act("enter_tan", "tan")
        real_apply = self.session.apply

        async def click_then_time_out(action, site_id):
            await real_apply(action, site_id)
            raise TimeoutError("synthetic click timeout")

        with patch.object(self.session, "apply", click_then_time_out):
            result = await self.act("sign", "sign")
        self.assertIn("unknown", result)
        self.assertEqual(self.controller.phase, Phase.SIGN)
        observation = await self.agent.observe()
        with self.assertRaisesRegex(ValueError, "receipt or an explicit validation failure"):
            await self.agent.handle({"action": "sign", "target": "rfq-1"}, observation)
        await self.act("confirm_receipt", excerpt=RECEIPT, receipt_id="R-77")
        self.assertEqual(await self.page.evaluate("window.signs"), 1)
        self.assertEqual(self.controller.sign_attempts, 1)

    async def test_explicit_validation_failure_reopens_without_acceptance(self):
        self.mail_value = "000000"
        await self.fill_and_review()
        await self.act("request_tan", "tanreq")
        await self.act("enter_tan", "tan")
        await self.act("sign", "sign")
        with self.assertRaisesRegex(ValueError, "visible"):
            await self.act("confirm_receipt", excerpt=RECEIPT, receipt_id="R-77")
        await self.act("report_validation_failure", quote="Error: signing code rejected")
        self.assertEqual(self.controller.phase, Phase.FILL)
        self.assertIsNone(self.controller.receipt)

    async def test_mail_owner_reports_only_the_matching_new_tan(self):
        await self.fill_and_review()
        self.controller.request_tan("tender")
        mail_page = await self.context.new_page()
        sent = self.fresh_mail.split("Sent ")[1]
        replies = [{"action": "open_site", "site_id": "mail"},
                   {"action": "report_tan", "value": "999999", "message": self.fresh_mail, "sent_at": sent},
                   {"action": "report_tan", "value": "482913", "message": self.mail_list, "sent_at": sent},
                   {"action": "report_tan", "value": "482913"},
                   {"action": "report_tan", "value": "482913", "message": self.fresh_mail, "sent_at": sent}]
        with patch.object(model, "complete_with_retry", side_effect=[json.dumps(r) for r in replies]) as call:
            result = await read_tan(TASK, [InvestigationSession(mail_page, self.sites)], self.controller, RunClock({}), self.redactor)
        self.assertEqual(call.await_count, 5)
        self.assertEqual(self.controller.phase, Phase.READ_TAN)
        self.assertEqual(self.controller.tan_for_entry("tender").reveal(), "482913")
        self.assertNotIn("482913", result)
        self.assertIn("ZZ-TEST-001", call.call_args_list[0].args[0][1]["content"])

    async def test_scripted_model_loop_runs_the_whole_transaction(self):
        replies = [
            {"action": "enter_value", "target": "rfq-1", "path": "identity.company"},
            {"action": "enter_value", "target": "rfq-2", "path": "lines.0.unit"},
            {"action": "enter_value", "target": "rfq-3", "path": "lines.0.surcharge"},
            {"action": "omit_position", "target": "rfq-4", "position": "B"},
            {"action": "click", "target": "rfq-5"},
            {"action": "review", "fields": [{"path": "identity.company", "target": "rfq-1"}, {"path": "lines.0.unit", "target": "rfq-2"},
                                            {"path": "lines.0.surcharge", "target": "rfq-3"},
                                            {"path": "lines.0.qty", "quote": SUMMARY}, {"path": "total", "quote": SUMMARY}],
             "omissions": [], "code_field": "rfq-7"},
            {"action": "request_tan", "target": "rfq-6"},
            {"action": "enter_tan", "target": "rfq-7"},
            {"action": "sign", "target": "rfq-8"},
            {"action": "confirm_receipt", "excerpt": RECEIPT, "receipt_id": "R-77"},
        ]
        with patch.object(model, "complete_with_retry", side_effect=[json.dumps(r) for r in replies]), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            result = await self.agent.run(max_steps=12)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["receipt"]["receipt_id"], "R-77")
        self.assertNotIn("482913", log.getvalue())
        self.assertEqual(await self.page.evaluate("window.signs"), 1)


if __name__ == "__main__":
    unittest.main()
