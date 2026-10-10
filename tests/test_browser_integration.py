"""Synthetic UI contracts with an observation-conditioned model double.

The double reads displayed records and current controls. Application code never knows fixture URLs,
selectors, values, layout variants, or the double's policy. Hosted-model quality is tested separately.
"""
from __future__ import annotations

import html
import json
import re
from decimal import Decimal

import httpx
import pytest
from aiohttp import web
from conftest import synthetic_records

from atira_agent.browser import BrowserSession
from atira_agent.config import Config
from atira_agent.contracts import AgentAction, RunContext, SubmissionState
from atira_agent.dashboard import Dashboard
from atira_agent.orchestrator import Orchestrator
from atira_agent.runtime import Deadline


class SyntheticSites:
    def __init__(self, variant):
        self.variant = variant
        self.runner = None
        self.base = ""
        self.tan_generation = 0
        self.answer = None
        self.hits = {}
        self.fail_once = variant == 2
        self.expire_once = variant == 2
        self.session_renewed = False
        self.archived_read = False

    async def start(self):
        app = web.Application()
        app.router.add_get("/{site}", self.home)
        app.router.add_get("/records/{site}", self.records)
        app.router.add_get("/offer/form", self.form)
        app.router.add_get("/sign/mail", self.mail)
        app.router.add_post("/sign/request", self.request_tan)
        app.router.add_post("/offer/accept", self.accept)
        app.router.add_post("/renew", self.renew)
        app.router.add_get("/archived/mail", self.archive)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        return self

    def page(self, content):
        return web.Response(text=f"<!doctype html><title>Synthetic company {self.variant}</title><body>{content}</body>", content_type="text/html")

    async def home(self, request):
        name = request.match_info["site"]
        self.hits[name] = self.hits.get(name, 0) + 1
        if self.fail_once and name == "erp":
            self.fail_once = False
            return self.page(f'<h1>Temporary error</h1><a href="/{name}">Retry selected page</a>')
        if self.expire_once and name == "erp":
            self.expire_once = False
            return self.page('''<h1>Synthetic session expired</h1><form action="/renew" method="post">
              <label>Login name<input name="user"></label><label>Password<input name="password" type="password"></label>
              <button>Renew session</button></form>''')
        if self.variant == 2 and name == "mail":
            return self.page('<h1>Inbox: no matching commercial messages</h1><a href="/archived/mail">Open archive</a>')
        if self.variant == 1:
            control = f'<a href="/records/{name}">Read {name} records</a>'
        else:
            control = f'''<button onclick="document.getElementById('viewer').src='/records/{name}'">Read {name} records</button><iframe id="viewer"></iframe>'''
        return self.page(f"<h1>{name}</h1>{control}<a href='/offer/form'>Configure offer</a>")

    async def renew(self, request):
        data = await request.post()
        if data.get("user") != "synthetic-user" or data.get("password") != "synthetic-password":
            return self.page("Synthetic credentials invalid")
        self.session_renewed = True
        raise web.HTTPSeeOther("/erp")

    async def archive(self, request):
        self.archived_read = True
        return self.page('''<h1>Archive</h1><button onclick="document.getElementById('viewer').src='/records/mail'">Read mail records</button><iframe id="viewer"></iframe>''')

    async def records(self, request):
        groups = {"tender": {"tender", "position"}, "spec": {"revision", "requirement"},
                  "erp": {"material", "search", "price"}, "mail": {"fx", "packaging", "pool", "bonus", "discount"}}
        selected = [{"kind": kind, "data": data} for kind, data in synthetic_records() if kind in groups[request.match_info["site"]]]
        for item in selected:
            item["data"].pop("evidence")
        return self.page("<h2>Selected records</h2><pre>DATA_BEGIN" + html.escape(json.dumps(selected)) + "DATA_END</pre>")

    async def form(self, request):
        labels = [(f"{pos} unit", f"{pos}_unit") for pos in ("A", "B")] + [("Net total", "total")]
        inputs = "".join(f'<label>{label}<input name="{name}"></label>' for label, name in labels)
        return self.page(f'''<h1>TEST-RFQ review</h1><form id="offer" method="post" action="/offer/accept">
        {inputs}<label>Signing code<input name="tan"></label>
        <button type="button" onclick="fetch('/sign/request',{{method:'POST'}}).then(()=>document.getElementById('state').textContent='Signing mail requested')">Request signing code</button>
        <p id="state"></p><a href="/sign/mail" target="_blank">View signing mailbox</a>
        <button type="submit" onclick="return confirm('Confirm binding offer submission?')">Send binding offer</button></form>''')

    async def request_tan(self, request):
        self.tan_generation += 1
        return web.json_response({"requested": True})

    async def mail(self, request):
        return self.page(f"<h1>TEST-RFQ signing message</h1><p>TAN: {654320 + self.tan_generation}</p>")

    async def accept(self, request):
        data = await request.post()
        if data.get("tan") != str(654320 + self.tan_generation):
            return self.page("<h1>TAN invalid</h1>")
        self.answer = dict(data)
        return self.page("<h1>TEST-RFQ</h1><p>Offer successfully received. Receipt SYN-RECEIPT-001</p>")

    async def close(self):
        await self.runner.cleanup()


class ObservingModel:
    def __init__(self):
        self.visited = set()
        self.pending = None
        self.cited = None
        self.form_tab = None
        self.tan_captured = False
        self.clicked_mail = False
        self.steps = []

    async def decide(self, messages, deadline):
        state = json.loads(messages[-1]["content"][0]["text"])
        obs = state["current_observation"]
        text, controls = obs["text"], obs["controls"]
        self.steps.append(obs["id"])
        def act(action, **args):
            return AgentAction(action=action, summary="Synthetic observation-conditioned decision", args=args)
        def ref(label):
            return next(x["ref"] for x in controls if x["label"].strip() == label)
        if "Synthetic session expired" in text:
            for label, secret in (("Login name", "erp:username"), ("Password", "erp:password")):
                if not next(x for x in controls if x["label"] == label)["filled"]:
                    return act("fill", ref=ref(label), secret=secret)
            return act("click", ref=ref("Renew session"))
        if any(x["label"] == "Open archive" for x in controls):
            return act("click", ref=ref("Open archive"))
        if obs["dialog"]:
            return act("dialog", accept=True)
        if "successfully received" in text:
            return act("receipt", observation=obs["id"], receipt_id="SYN-RECEIPT-001",
                       excerpt="Offer successfully received. Receipt SYN-RECEIPT-001")
        if self.pending:
            cite_result = state["recent_actions_and_results"][-1]["result"]
            evidence = cite_result[0]["id"]
            records = self.pending
            self.pending = None
            for record in records:
                record["data"]["evidence"] = [evidence]
            return act("record", records=records)
        if len(self.visited) < 4:
            match = re.search(r"DATA_BEGIN(.*?)DATA_END", text, re.S)
            if match and obs["url"] not in self.visited:
                self.visited.add(obs["url"])
                self.pending = json.loads(match.group(1))
                return act("cite", observation=obs["id"], excerpt=match.group(0))
            for c in controls:
                if c["label"].startswith("Read ") and "DATA_BEGIN" not in text:
                    return act("click", ref=c["ref"])
                if c["label"] == "Retry selected page":
                    return act("click", ref=c["ref"])
            next_site = state["sites"][len(self.visited)]
            return act("navigate", url=next_site["url"])
        if not state["calculation"]:
            return act("calculate")
        if state["submission_state"] == "draft":
            return act("prepare_submission")
        if "TEST-RFQ review" not in text and state["submission_state"] == "validated":
            return act("navigate", url=state["submission_target"]["url"])
        if state["submission_state"] == "validated":
            self.form_tab = obs["tab"]
            if not next(x for x in controls if x["label"] == "Net total").get("value"):
                return act("fill_answer", fields=[{"ref": ref("A unit"), "path": "positions.0.unit_price"},
                    {"ref": ref("B unit"), "path": "positions.1.unit_price"}, {"ref": ref("Net total"), "path": "total_net"}])
            return act("request_tan", ref=ref("Request signing code"))
        if "signing message" in text:
            if not self.tan_captured:
                self.tan_captured = True
                return act("capture_tan", observation=obs["id"])
            return act("tab", tab=self.form_tab)
        if self.tan_captured:
            code = next(x for x in controls if x["label"] == "Signing code")
            if not code.get("value"):
                return act("fill", ref=code["ref"], tan=True)
            return act("sign", ref=ref("Send binding offer"), reviewed=True, omissions_confirmed=True)
        if self.clicked_mail:
            other = next(x for x in obs["tabs"] if x["tab"] != self.form_tab)
            return act("tab", tab=other["tab"])
        self.clicked_mail = True
        return act("click", ref=ref("View signing mailbox"))


@pytest.mark.browser
@pytest.mark.parametrize("variant", [1, 2])
async def test_observed_extraction_calculation_and_signed_receipt(telemetry, variant):
    sites = await SyntheticSites(variant).start()
    run = RunContext(challenge_id="rfq", brief="Synthetic RFQ browser integration",
                     access=[{"siteId": name, "url": f"{sites.base}/{name}", "credentials":
                              {"username": "synthetic-user", "password": "synthetic-password"} if name == "erp" else {}}
                             for name in ("tender", "spec", "erp", "mail")],
                     submission={"kind": "site", "siteId": "tender", "url": sites.base + "/offer/form"}, answer_schema={})
    config = Config(False, (), "qwen", "qwen", "http://127.0.0.1", "local", 120, 20)
    browser = BrowserSession(config, run, telemetry, headful=False)
    model = ObservingModel()
    try:
        await browser.start()
        controller = Orchestrator(run, config, browser, model, telemetry, Deadline(120, 20))
        assert await controller.run_loop(max_steps=65), list(controller.history)[-3:]
        assert controller.submission.state == SubmissionState.SCOUTING_ACKNOWLEDGED
        assert Decimal(sites.answer["total"]) == Decimal("96.07")
        assert len(controller.ledger.facts) == 4
        assert set(sites.hits) == {"tender", "spec", "erp", "mail"}
        assert len(model.steps) > 20
        if variant == 2:
            assert sites.session_renewed and sites.archived_read
        trace = (telemetry.trace_dir / "events.jsonl").read_text(encoding="utf-8")
        assert str(654320 + sites.tan_generation) not in trace
    finally:
        await browser.close()
        await sites.close()


@pytest.mark.browser
async def test_stale_refs_and_secret_origin(telemetry):
    sites = await SyntheticSites(1).start()
    run = RunContext(challenge_id="rfq", brief="test", access=[{"siteId": "other", "url": "http://127.0.0.1:1",
        "credentials": {"password": "fake-secret"}}, {"siteId": "tender", "url": sites.base}],
        submission={"kind": "site", "url": sites.base}, answer_schema={})
    browser = BrowserSession(Config(False, (), "qwen", "qwen", "http://localhost", "local"), run, telemetry, headful=False)
    try:
        await browser.start()
        await browser.act("navigate", {"url": sites.base + "/offer/form"})
        obs = await browser.observe()
        old = next(x["ref"] for x in obs.controls if x["label"] == "A unit")
        with pytest.raises(ValueError, match="different website"):
            await browser.act("fill", {"ref": old, "secret": "other:password"})
        await browser.observe()
        with pytest.raises(ValueError, match="Stale"):
            await browser.act("fill", {"ref": old, "text": "99"})
        await browser.act("navigate", {"url": sites.base + "/erp"})
        observed = await browser.observe()
        selected = next(x["ref"] for x in observed.controls if x["label"] == "Read erp records")
        original_tab = browser.tab
        results = [row async for row in browser.read_links([selected])]
        assert "DATA_BEGIN" in results[0][0].text
        assert results[0][1]["selected_label"] == "Read erp records"
        assert browser.tab == original_tab
        assert browser.page.url == sites.base + "/erp"
    finally:
        await browser.close()
        await sites.close()


async def test_dashboard_updates_and_bounds(telemetry):
    dashboard = Dashboard(telemetry, port=0)
    try:
        port = await dashboard.start()
        telemetry.emit("stage_changed", stage="pricing", remaining=300)
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://127.0.0.1:{port}/state")
            assert response.json()["stage"] == "pricing"
            assert (await client.get(f"http://127.0.0.1:{port}/")).status_code == 200
            assert (await client.get(f"http://127.0.0.1:{port}/artifact/no.png")).status_code == 404
            async with client.stream("GET", f"http://127.0.0.1:{port}/events") as response:
                telemetry.emit("stage_changed", stage="submitting", remaining=180)
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        assert json.loads(line[6:])["stage"] == "submitting"
                        break
    finally:
        await dashboard.close()


@pytest.mark.browser
async def test_selected_tooltips_are_observed_before_the_next_hides_them(telemetry):
    run = RunContext(challenge_id="rfq", brief="Synthetic tooltip test", access=[],
                     submission={"kind": "site", "url": "http://localhost"}, answer_schema={})
    browser = BrowserSession(Config(False, (), "qwen", "qwen", "http://localhost", "local"),
                             run, telemetry, headful=False)
    try:
        await browser.start()
        await browser.page.set_content('''<table>
          <tr><td>Reply A</td><td><button onclick="document.getElementById('date').innerText='Date A: 2027-02-01'">Date</button></td></tr>
          <tr><td>Reply B</td><td><button onclick="document.getElementById('date').innerText='Date B: 2027-02-02'">Date</button></td></tr>
          </table><p id="date"></p>''')
        initial = await browser.observe()
        assert "Reply A" in initial.controls[0]["context"]
        assert "Reply B" in initial.controls[1]["context"]
        rows = [row async for row in browser.inspect_controls([x["ref"] for x in initial.controls])]
        assert "Date A: 2027-02-01" in rows[0][1]["revealed_text"]
        assert "Date B: 2027-02-02" in rows[1][1]["revealed_text"]
        assert "Date A" not in rows[1][0].text
        assert rows[0][0].id != rows[1][0].id
        with pytest.raises(ValueError, match="Stale"):
            await browser.act("click", {"ref": initial.controls[0]["ref"]})
        await browser.page.set_viewport_size({"width": 1500, "height": 950})
        current = await browser.observe(include_image=True)
        assert browser.last_image_size == (1500, 950)
        await browser.act("pixel_click", {"observation": current.id, "x": 1400, "y": 900})
        fresh = await browser.observe()
        with pytest.raises(ValueError, match="current screenshot"):
            await browser.act("pixel_click", {"observation": fresh.id, "x": 1, "y": 1})
        await browser.page.set_content('''<iframe style="width:100px;height:100px" srcdoc="
          <button style='position:fixed;left:200px' onclick='this.innerText=String(17)'>Close</button>"></iframe>''')
        observed = await browser.observe()
        target = next(x["ref"] for x in observed.controls if x["label"] == "Close")
        browser.context.set_default_timeout(500)
        await browser.act("click", {"ref": target})
        assert "17" in (await browser.observe()).text
        await browser.page.set_content('<canvas aria-label="Visible accessibility description"></canvas>')
        assert "Visible accessibility description" in (await browser.observe()).text
    finally:
        await browser.close()
