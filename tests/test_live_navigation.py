"""Opt-in paid model integration; all website data is invented and locally routed."""
import asyncio
import os
import unittest
from playwright.async_api import async_playwright
from rfq_agent.planner import run_planner
from rfq_agent.evidence import EvidenceLedger


@unittest.skipUnless(os.environ.get('RFQ_LIVE_MODEL_TEST') == '1', 'opt-in paid model navigation test')
class LiveNavigation(unittest.IsolatedAsyncioTestCase):
    async def test_independent_mail_list_and_reading_gates(self):
        async with async_playwright() as pw:
            instance = await pw.chromium.launch(headless=True)
            try:
                context = await instance.new_context(viewport={'width': 1200, 'height': 850})
                html = '''<title>Invented mailbox</title><h1>Messages</h1><p>Find the current delivery commitment and quote its message body.</p>
                <main style="display:flex;gap:40px"><section id="list"><h2>Message list</h2>
                <form onsubmit="event.preventDefault();document.querySelector('#delivery').style.display=/delivery/i.test(this.querySelector('input').value)?'block':'none'">
                <label>Search messages<input type="search" name="query"></label><button type="submit">Search</button></form>
                <p>Human verification: drag fully right, then check I am not a robot.</p>
                <input type="range" min="0" max="100" value="0" style="width:320px" oninput="unlock(this)">
                <label><input type="checkbox" onchange="unlock(this)">I am not a robot</label><p class="status">Locked</p>
                <fieldset disabled style="pointer-events:none"><legend>Protected message list</legend>
                <a href="#" onclick="event.preventDefault();document.querySelector('#body').src='/decoy'">Signing code request 287</a>
                <a id="delivery" style="display:none" href="#" onclick="event.preventDefault();document.querySelector('#body').src='/original-body'">Current delivery commitment</a></fieldset></section>
                <section id="reader"><h2>Reading pane</h2><p>Human verification: drag fully right, then check I am not a robot.</p>
                <input type="range" min="0" max="100" value="0" style="width:320px" oninput="unlock(this)">
                <label><input type="checkbox" onchange="unlock(this)">I am not a robot</label><p class="status">Locked</p>
                <fieldset disabled style="pointer-events:none"><legend>Protected reading area</legend>
                <details><summary>Open reading pane</summary><iframe id="body" title="Original message body" style="width:450px;height:400px"></iframe></details></fieldset></section></main>
                <script>function unlock(el){const section=el.closest('section');const ready=Number(section.querySelector('input[type=range]').value)>=99 && section.querySelector('input[type=checkbox]').checked;section.querySelector('fieldset').disabled=!ready;section.querySelector('fieldset').style.pointerEvents=ready?'auto':'none';section.querySelector('.status').textContent=ready?'Unlocked':'Locked';}</script>'''
                body = '''<title>Original delivery message</title><section><h2>Original body</h2>
                <p>Human verification: drag fully right, then check I am not a robot.</p>
                <input type="range" min="0" max="100" value="0" style="width:280px" oninput="unlock(this)">
                <label><input type="checkbox" onchange="unlock(this)">I am not a robot</label>
                <fieldset disabled><p>Invented delivery commitment: 23 days.</p></fieldset></section>
                <script>function unlock(el){const s=el.closest('section');s.querySelector('fieldset').disabled=!(Number(s.querySelector('input[type=range]').value)>=99 && s.querySelector('input[type=checkbox]').checked);}</script>'''
                await context.route('https://mail-shift.example.test/**', lambda route: route.fulfill(content_type='text/html', body=body if route.request.url.endswith('/original-body') else html))
                page = await context.new_page(); ledger = EvidenceLedger()
                task = {'brief': 'Find and quote the current delivery commitment from its message body. Message list and reading area have independent access gates; use their visible instructions.', 'access': [{'siteId': 'invented-mail', 'url': 'https://mail-shift.example.test/'}]}
                result = await run_planner(task, page, {'site_id': 'invented-mail', 'objective': task['brief'], 'review_completion': True}, ledger, max_steps=30)
                self.assertEqual(result['status'], 'completed', result)
                self.assertTrue(any('23 days' in record.quote for record in await ledger.snapshot()), result)
                self.assertTrue(any(e['action'] == 'fill' for e in result['history']), result)
                self.assertFalse(any(e.get('target_label') == 'Signing code request 287' for e in result['history']), result)
                self.assertEqual(await page.locator('fieldset[disabled]').count(), 0)
                self.assertEqual(await page.locator('input[type=checkbox]:checked').count(), 2)
                frame = next(f for f in page.frames if f.url.endswith('/original-body'))
                self.assertEqual(await frame.locator('fieldset[disabled]').count(), 0)
                self.assertEqual(await frame.locator('input[type=checkbox]:checked').count(), 1)
            finally:
                await instance.close()

    async def test_image_receipt_gate_then_acknowledgment(self):
        async with async_playwright() as pw:
            instance = await pw.chromium.launch(headless=True)
            try:
                context = await instance.new_context(viewport={'width': 1100, 'height': 900})
                html = '''<title>System access notice</title><section><h1>System notice</h1>
                  <p>Read the receipt number shown in the image, unlock the protected section,
                  copy the number into its field, acknowledge operating conditions and continue.</p>
                  <canvas width="600" height="100" id="picture"></canvas>
                  <p>Human verification: drag all the way right and check I am not a robot.</p>
                  <input type="range" min="0" max="100" value="0" style="width:400px" oninput="unlock()">
                  <label><input type="checkbox" id="robot" onchange="unlock()">I am not a robot</label>
                  <p id="status">Locked</p>
                  <form onsubmit="event.preventDefault(); if(this.receipt.value==='TEST-482619')location.href='/facts'; else document.querySelector('#status').textContent='Receipt does not match the image'">
                  <fieldset disabled><legend>Protected section</legend>
                  <label>Receipt number<input name="receipt" required></label>
                  <label><input type="checkbox" required>Operating conditions read</label>
                  <button type="submit">Obtain read access</button></fieldset></form></section>
                  <script>const paint=document.querySelector('canvas').getContext('2d');
                  paint.font='28px sans-serif';paint.fillText('Receipt number',20,30);paint.fillText('TEST-482619',20,75);
                  function unlock(){const ready=document.querySelector('input[type=range]').value>=99 && document.querySelector('#robot').checked;document.querySelector('fieldset').disabled=!ready;document.querySelector('#status').textContent=ready?'Unlocked':'Locked';}</script>'''
                await context.route('https://gate.example.test/**', lambda route: route.fulfill(content_type='text/html', body='<p>Invented delivery period: 17 days.</p>' if '/facts' in route.request.url else html))
                page = await context.new_page()
                ledger = EvidenceLedger()
                task = {'brief': 'Complete the visible access instructions, then record the delivery period from its source page.', 'access': [{'siteId': 'invented-gate', 'url': 'https://gate.example.test/'}]}
                result = await run_planner(task, page, {'site_id': 'invented-gate', 'objective': task['brief']}, ledger, max_steps=18)
                self.assertTrue(any('17 days' in record.quote for record in await ledger.snapshot()), result)
            finally:
                await instance.close()

    async def test_four_independent_logins_and_evidence(self):
        access = [{'siteId': f'invented-{i}', 'url': f'https://shifted-{i}.example.test/',
                   'credentials': {'username': f'fake-user-{i}', 'password': f'fake-password-{i}'}} for i in range(4)]
        ledger = EvidenceLedger()
        async with async_playwright() as pw:
            instance = await pw.chromium.launch(headless=True)
            try:
                async def route_handler(route):
                    index = int(route.request.url.split('shifted-')[1].split('.')[0])
                    if '/facts' in route.request.url:
                        body = f'<title>Record {index}</title><p>Invented delivery period: {index + 11} days.</p>'
                    else:
                        body = ('<title>Access</title><form action="/facts" method="post">'
                                '<label>User name<input name="account" autocomplete="username" required></label>'
                                '<label>Password<input type="password" name="secret" required></label>'
                                '<button type="submit">Sign in</button></form>')
                    await route.fulfill(body=body, content_type='text/html')
                pages = []
                for _ in access:
                    context = await instance.new_context()
                    await context.route('https://*.example.test/**', route_handler)
                    pages.append(await context.new_page())
                task = {'brief': 'Read the invented delivery period from each assigned site. Log in using runtime credentials. Record its exact source quote.', 'access': access}
                results = await asyncio.gather(*(run_planner(task, page, {'site_id': site['siteId'], 'worker_id': site['siteId'], 'objective': 'Log in and record the delivery period on your assigned site.'}, ledger, max_steps=12) for page, site in zip(pages, access)))
                records = await ledger.snapshot()
                self.assertEqual({record.site_id for record in records}, {site['siteId'] for site in access}, results)
                for record in records:
                    index = int(record.site_id.split('-')[1])
                    self.assertIn(f'{index + 11} days', record.quote)
            finally:
                await instance.close()
