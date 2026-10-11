"""Regression tests for the parent review's blockers on local Chromium pages.

All pages and values are invented; nothing here is evidence of an eligible submission.
"""
import asyncio
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from rfq_agent import model, planner
from rfq_agent.deadline import RunClock
from rfq_agent.documents import InvestigationSession
from rfq_agent.evidence import EvidenceLedger
from rfq_agent.redact import Redactor
from rfq_agent.submission import Phase, SubmissionController
from rfq_agent.submit_agent import SubmissionAgent
from tests.test_review_blockers import BRIEF, CHECKLIST, EV, SCHEMA, Flow, good_draft, omit_a_draft

ROOT = "https://portal.test"
TASK = {"brief": BRIEF, "answer_schema": SCHEMA, "submission": {"kind": "site", "url": ROOT},
        "access": [{"siteId": "portal", "url": ROOT}, {"siteId": "mail", "url": "https://mail.test"}]}
ROW_A = ('<tr><td>Line A: steel bracket, quantity 4</td><td><label>Unit price <input id="pa"></label></td>'
         '<td><label>Surcharge <input id="sa"></label></td>')
PAGES = {
    "/tenders/1": """<h1>Tender ZZ-TEST-001</h1><a id="entry" href="/form">Angebot abgeben</a>
<form onsubmit="return false"><label>Company <input id="co" required></label><table>""" + ROW_A + """
<td><label><input type="checkbox" id="oa"> Do not offer line A</label></td></tr>
<tr><td>Line B: steel washer</td><td><label>Unit price <input id="pb"></label></td><td></td>
<td><label><input type="checkbox" id="ob"> Do not offer line B</label></td></tr></table>
<label>Delivery terms <select id="terms"><option value="">Choose</option><option value="std">Standard</option></select></label>
<label>Find receipt <input type="search" id="q" name="q"></label>
<label>Internal note <input id="note"></label>
<button type="button" id="rev" onclick="summary.innerText='Line A quantity 4 Total 10,00'">Show summary</button>
<div id="summary"></div>
<button type="button" id="tanreq" onclick="window.requests=(window.requests||0)+1">Request signing code</button>
<label>Signing code <input id="tan"></label>
<button type="button" id="send" onclick="window.sends=(window.sends||0)+1">Absenden</button>
<button type="submit" id="sign" onclick="window.signs=(window.signs||0)+1">Sign and submit bid</button></form>""",
    "/form": "<h1>Bid form ZZ-TEST-001</h1><p>form opened</p>",
    "/login": '<p>Tender ZZ-TEST-001</p><form action="/form"><input name="user"><button type="submit" id="si">Sign in</button></form>',
    "/gate": """<h1>ZZ-TEST-001</h1><div role="dialog" aria-label="Human verification"><p>Human verification: type the code K7Q2</p>
<label>Verification code <input id="vc"></label></div>""",
    "/w1": '<h1>ZZ-TEST-001 step 1</h1><label>Company <input id="co"></label><a id="n1" href="/w2">Next</a>',
    "/w2": '<h1>ZZ-TEST-001 step 2</h1><table>' + ROW_A + """</tr><tr><td>Line B: steel washer</td>
<td><label><input type="checkbox" id="ob"> Do not offer line B</label></td></tr></table><a id="n2" href="/w3">Next</a>""",
    "/w3": """<h1>Summary ZZ-TEST-001</h1><p>Company Example Works Ltd</p><p>Line A quantity 4 unit 2,50 surcharge 0,00</p>
<p>Line B: not offered</p><p>Total 10,00</p><button type="button" id="tanreq">Request signing code</button>""",
}


class AgentBlockerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context()

        async def serve(route):
            path = "/" + route.request.url.split("/", 3)[3].split("?")[0]
            await route.fulfill(body=PAGES.get(path, "<p>not found</p>"), content_type="text/html")

        await self.context.route(ROOT + "/**", serve)
        self.page = await self.context.new_page()
        await self.page.goto(ROOT + "/tenders/1")
        self.sites = planner.normalize_sites(TASK["access"])
        self.redactor = Redactor()
        self.controller = SubmissionController(ROOT, redactor=self.redactor)
        self.controller.checklist = CHECKLIST
        self.controller.identify("ZZ-TEST-001", BRIEF, EV)
        self.controller.confirm_on_portal(ROOT + "/tenders/1", "Tender ZZ-TEST-001")
        self.controller.accept_draft(good_draft(), SCHEMA, BRIEF, EV)
        self.session = InvestigationSession(self.page, self.sites)
        self.agent = SubmissionAgent(TASK, self.session, self.controller, EvidenceLedger(), RunClock({}), self.redactor)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def target(self, element):
        observation = await self.agent.observe()
        return next(t["id"] for t in observation["targets"] if t["element_id"] == element)

    async def act(self, kind, element=None, **fields):
        observation = await self.agent.observe()
        action = {"action": kind, **fields}
        if element:
            action["target"] = next(t["id"] for t in observation["targets"] if t["element_id"] == element)
        return await self.agent.handle(action, observation)

    async def allowed(self, kind, element=None, **fields):
        try:
            return await self.act(kind, element, **fields)
        except ValueError as exc:
            self.fail(f"{kind} on {element} should be allowed but was blocked: {exc}")

    def force_reviewed(self):
        c = self.controller
        c.note_filled("identity.company", descriptor="d-co", shown="Example Works Ltd")
        c.note_filled("lines.0.unit", descriptor="d-pa", shown="2.50")
        c.note_omission("B", descriptor="d-ob", state="true")
        c.review({"identity.company": "Example Works Ltd", "lines.0.unit": "2.50"}, {"B": "Line B: not offered"}, Flow.PAGE,
                 static={"lines.0.qty": "Line A quantity 4", "lines.0.surcharge": "Line A surcharge 0,00", "total": "Total 10,00"})

    async def force_tan(self, value="482913"):
        self.force_reviewed()
        self.controller.request_tan("tender")
        await asyncio.sleep(0.02)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        message = f"Signing code for ZZ-TEST-001: {value} Sent {stamp}"
        self.controller.accept_tan(value, message, self.controller.now(), message=message, sent_at=stamp)

    async def test_sign_in_is_not_a_final_control(self):
        await self.page.goto(ROOT + "/login")
        investigator = InvestigationSession(self.page, self.sites)
        observation = await investigator.observe("portal")
        target = next(t["id"] for t in observation["targets"] if t["element_id"] == "si")
        try:
            await investigator.apply({"action": "click", "target": target}, "portal")
        except ValueError as exc:
            self.fail(f"Sign in was treated as a final signing control: {exc}")
        self.assertTrue(self.page.url.startswith(ROOT + "/form"))

    async def test_entry_control_opens_the_form_only_before_anything_is_entered(self):
        with self.assertRaises(ValueError):
            await self.act("click", "entry")
        await self.allowed("open_form", "entry")
        self.assertTrue(self.page.url.endswith("/form"))
        await self.page.goto(ROOT + "/tenders/1")
        await self.allowed("enter_value", "co", path="identity.company")
        with self.assertRaisesRegex(ValueError, "open_form"):
            await self.act("open_form", "entry")
        self.assertTrue(self.page.url.endswith("/tenders/1"))

    async def test_no_form_mutation_while_signing_is_unresolved(self):
        await self.force_tan()
        self.controller.begin_sign("tender", "pre-sign page")
        for kind, element, fields in (("click", "send", {}), ("click", "rev", {}), ("click", "oa", {}),
                                      ("select_option", "terms", {"value": "std"}), ("fill", "note", {"value": "x"})):
            with self.assertRaises(ValueError, msg=f"{kind} {element}"):
                await self.act(kind, element, **fields)
        self.assertIsNone(await self.page.evaluate("window.sends"))
        self.assertEqual(await self.page.locator("#terms").input_value(), "")
        await self.allowed("fill", "q", value="R-77")
        self.assertEqual(await self.page.locator("#q").input_value(), "R-77")
        self.assertEqual(self.controller.phase, Phase.SIGN)

    async def test_changes_after_review_void_review_and_code(self):
        await self.force_tan()
        await self.allowed("select_option", "terms", value="std")
        self.assertEqual(self.controller.phase, Phase.FILL)
        self.assertIsNone(self.controller.review_hash)
        with self.assertRaises(ValueError):
            self.controller.tan_for_entry("tender")

    async def test_free_fill_is_limited_to_search_and_access_gates(self):
        for element in ("note", "pb"):
            with self.assertRaisesRegex(ValueError, "enter_value"):
                await self.act("fill", element, value="1.00")
        await self.allowed("fill", "q", value="receipt")
        await self.page.goto(ROOT + "/gate")
        with self.assertRaises(ValueError):
            await self.act("fill", "vc", value="ZZZZ")
        await self.allowed("fill", "vc", value="K7Q2")
        self.assertEqual(await self.page.locator("#vc").input_value(), "K7Q2")

    async def test_multi_page_wizard_collects_readbacks_and_reviews_a_static_summary(self):
        await self.page.goto(ROOT + "/w1")
        await self.allowed("enter_value", "co", path="identity.company")
        await self.allowed("collect_readback", fields=[{"path": "identity.company", "target": await self.target("co")}])
        await self.allowed("click", "n1")
        await self.allowed("enter_value", "pa", path="lines.0.unit", decimal_comma=True)
        await self.allowed("enter_value", "sa", path="lines.0.surcharge")
        await self.allowed("omit_position", "ob", position="B")
        await self.allowed("collect_readback", fields=[{"path": "lines.0.unit", "target": await self.target("pa")},
                                                       {"path": "lines.0.surcharge", "target": await self.target("sa")}])
        await self.allowed("click", "n2")
        with self.assertRaisesRegex(ValueError, "total"):
            await self.act("review", fields=[{"path": "lines.0.qty", "quote": "Line A quantity 4 unit 2,50 surcharge 0,00"}],
                           omissions=[{"position": "B", "quote": "Line B: not offered"}])
        await self.allowed("review", fields=[{"path": "lines.0.qty", "quote": "Line A quantity 4 unit 2,50 surcharge 0,00"},
                                             {"path": "total", "quote": "Total 10,00"}],
                           omissions=[{"position": "B", "quote": "Line B: not offered"}])
        self.assertEqual(self.controller.phase, Phase.REVIEW)
        self.assertTrue(self.controller.review_hash)

    async def test_values_are_bound_to_the_row_and_control_they_belong_to(self):
        with self.assertRaisesRegex(ValueError, "position A"):
            await self.act("enter_value", "pb", path="lines.0.unit")
        self.assertEqual(await self.page.locator("#pb").input_value(), "")
        await self.allowed("enter_value", "pa", path="lines.0.unit")
        await self.allowed("enter_value", "sa", path="lines.0.surcharge")
        await self.allowed("omit_position", "ob", position="B")
        await self.allowed("click", "rev")

        async def review():
            return await self.act("review", fields=[
                {"path": "identity.company", "target": await self.target("co")},
                {"path": "lines.0.unit", "target": await self.target("pa")},
                {"path": "lines.0.surcharge", "target": await self.target("sa")},
                {"path": "lines.0.qty", "quote": "Line A quantity 4 Total 10,00"}, {"path": "total", "quote": "Line A quantity 4 Total 10,00"}],
                omissions=[], code_field=await self.target("tan"))

        with self.assertRaisesRegex(ValueError, "Company"):
            await review()
        await self.allowed("enter_value", "co", path="identity.company")
        await self.page.locator("#pb").fill("7")
        with self.assertRaisesRegex(ValueError, "not bound"):
            await review()
        await self.page.locator("#pb").fill("")
        await self.page.locator("#ob").uncheck()
        with self.assertRaisesRegex(ValueError, "omitted state"):
            await review()
        await self.page.locator("#ob").check()
        try:
            await review()
        except ValueError as exc:
            self.fail(f"complete review was blocked: {exc}")
        self.assertEqual(self.controller.phase, Phase.REVIEW)

    async def test_revised_draft_must_clear_superseded_live_values(self):
        await self.allowed("enter_value", "co", path="identity.company")
        await self.allowed("enter_value", "pa", path="lines.0.unit")
        await self.allowed("enter_value", "sa", path="lines.0.surcharge")
        await self.allowed("omit_position", "ob", position="B")
        await self.allowed("revise_draft", reason="line A can no longer be priced")
        self.controller.capabilities["all_positions_omitted"] = {"supported": True, "quote": "x"}
        self.controller.accept_draft(omit_a_draft(), SCHEMA, BRIEF, EV)
        await self.allowed("enter_value", "co", path="identity.company")
        await self.allowed("omit_position", "oa", position="A")
        await self.page.evaluate("document.getElementById('summary').innerText = 'Total 0,00'")

        async def review():
            return await self.act("review", fields=[{"path": "identity.company", "target": await self.target("co")},
                                                    {"path": "total", "quote": "Total 0,00"}],
                                  omissions=[], code_field=await self.target("tan"))

        with self.assertRaisesRegex(ValueError, "superseded"):
            await review()
        await self.allowed("clear_field", "pa")
        await self.allowed("clear_field", "sa")
        self.assertEqual(await self.page.locator("#pa").input_value(), "")
        with self.assertRaisesRegex(ValueError, "superseded|draft"):
            await self.act("clear_field", "co")
        try:
            await review()
        except ValueError as exc:
            self.fail(f"review after clearing was blocked: {exc}")
        self.assertEqual(self.controller.phase, Phase.REVIEW)

    async def test_failed_request_click_does_not_open_the_code_path(self):
        self.force_reviewed()

        async def failing(action, site_id):
            raise TimeoutError("synthetic click timeout")

        with patch.object(self.session, "apply", failing):
            with self.assertRaises(TimeoutError):
                await self.act("request_tan", "tanreq")
        self.assertEqual(self.controller.phase, Phase.REVIEW)

    async def test_no_screenshot_reaches_the_model_while_a_code_is_on_screen(self):
        await self.force_tan("482913")
        await self.page.evaluate("document.body.insertAdjacentHTML('beforeend', '<p>Human verification pending</p>')")
        shot = AsyncMock(return_value="data:image/jpeg;base64,AAAA")
        give_up = json.dumps({"action": "give_up", "reason": "test"})
        with patch.object(planner, "_visual_challenge_screenshot", shot), \
                patch.object(model, "complete_with_retry", AsyncMock(return_value=give_up)) as call:
            await self.agent.run(max_steps=1)
            self.assertIsInstance(call.call_args.args[0][1]["content"], list)
            await self.page.locator("#tan").fill("482913")
            await self.agent.run(max_steps=1)
            content = call.call_args.args[0][1]["content"]
            self.assertIsInstance(content, str)
            self.assertNotIn("482913", content)
            await self.page.locator("#tan").fill("")
            await self.page.evaluate("document.body.insertAdjacentHTML('beforeend', '<p>You typed 482913</p>')")
            await self.agent.run(max_steps=1)
            self.assertIsInstance(call.call_args.args[0][1]["content"], str)


if __name__ == "__main__":
    unittest.main()
