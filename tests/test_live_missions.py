"""Paid, opt-in objective tests using invented local sites, never public values."""
import os
import json
from pathlib import Path
from decimal import Decimal
import unittest
from playwright.async_api import async_playwright
from rfq_agent import mail, missions


@unittest.skipUnless(os.environ.get('RFQ_LIVE_MODEL_TEST') == '1', 'opt-in paid mission navigation')
class LiveMissions(unittest.IsolatedAsyncioTestCase):
    async def run_site(self, mission):
        async with async_playwright() as pw:
            instance = await pw.chromium.launch(headless=True)
            try:
                context = await instance.new_context()
                html = '''<title>Correspondence</title><h1>Incoming correspondence</h1>
                <p>Two signing requests are visible. Older approvals can be found by search.</p>
                <form onsubmit="event.preventDefault();document.querySelector('#approvals').hidden=false">
                <label>Search correspondence<input type="search" name="query"></label><button>Find</button></form>
                <a href="/request-21">Signing request 21</a><br>
                <a href="/request-29">Signing request 29</a>
                <section id="approvals" hidden><p>All approval correspondence for CASE-42: one record;
                no subsequent withdrawals or replacements.</p>
                <a href="/approval">Sales Director: discount approval CASE-42, 2031-04-02</a></section>'''
                async def route_handler(route):
                    url = route.request.url
                    if url.endswith('/approval'):
                        body = '''<title>Original approval</title><h1>Original message</h1>
                        <p>From: chief@example.test (Sales Director)</p><p>Date: 2031-04-02</p>
                        <p>Original approval for CASE-42: 7.5%. No additional conditions.</p>'''
                    elif '/request-' in url:
                        number = int(url.rsplit('-', 1)[1])
                        body = f'''<title>Signing request {number}</title><h1>Signing request {number}</h1>
                        <details><summary>Draft preview</summary>False code: 000000</details>
                        <details><summary>Original message body</summary>
                        <p>Original signing request {number}: signing code {number}4839.</p></details>'''
                    else:
                        body = html
                    await route.fulfill(content_type='text/html', body=body)
                await context.route('https://correspondence.example.test/**', route_handler)
                page = await context.new_page()
                access = {'siteId': 'correspondence', 'url': 'https://correspondence.example.test/'}
                if mission == 'tan':
                    result = await mail.debug_tan(page, access, after=21, timeout_s=120, max_steps=20)
                    self.save(mission, result)
                    self.assertEqual(result['status'], 'completed', result.get('reason'))
                    self.assertEqual(result['result'], '294839')
                    self.assertEqual(result['evidence']['number'], 29)
                else:
                    result = await missions.get_discount(page, access, {
                        'brief': 'Tender CASE-42. Find the latest discount approved by the Sales Director.'},
                        timeout_s=120, max_steps=20)
                    self.save(mission, result)
                    self.assertEqual(result['status'], 'completed', result.get('reason'))
                    self.assertEqual(Decimal(result['result']['percentage']['value'].strip().rstrip('%')), Decimal('7.5'))
                    self.assertTrue(any(item['action'] == 'fill' for item in result['history']))
                return result
            finally:
                await instance.close()

    def save(self, mission, result):
        # Invented test results only. Separate settings and missions retain failures.
        setting = os.environ.get('OPENAI_REASONING_EFFORT', 'low')
        folder = Path('artifacts', 'mission-evaluation', os.environ.get('OPENAI_MODEL', 'gpt-5-nano') + '-' + setting)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (mission + '.json')).write_text(json.dumps(result, indent=2, default=str))

    async def test_tan_ignores_approval_and_older_request(self):
        await self.run_site('tan')

    async def test_discount_searches_past_signing_distractions(self):
        await self.run_site('discount')
