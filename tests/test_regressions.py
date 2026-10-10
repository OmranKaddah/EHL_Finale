import json
import unittest
from unittest.mock import AsyncMock, patch
from rfq_agent import planner, browser, model
from rfq_agent.evidence import Evidence, EvidenceLedger
from rfq_agent.documents import parse_document


class RegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_reauthentication_after_state_transition(self):
        login = {'url': 'https://example.test/login', 'title': 'login', 'visible_text': '', 'targets': []}
        home = dict(login, url='https://example.test/home')
        actions = [{'action': 'fill_credential', 'target': 'rfq-1', 'credential_key': 'username'},
                   {'action': 'click', 'target': 'rfq-2'},
                   {'action': 'fill_credential', 'target': 'rfq-1', 'credential_key': 'username'}]
        session = AsyncMock()
        session.page.url = 'https://example.test/login'
        session.observe.side_effect = [login, home, login]
        session.apply.return_value = ('s', 'applied')
        task = {'access': [{'siteId': 's', 'url': 'https://example.test'}]}
        with patch.object(planner, 'InvestigationSession', return_value=session), patch.object(model, 'complete_with_retry', side_effect=[json.dumps(a) for a in actions]):
            result = await planner.run_planner(task, session.page, {'site_id': 's'}, EvidenceLedger(), 3)
        self.assertEqual(session.apply.await_count, 3)
        self.assertEqual(result['status'], 'exhausted')

    async def test_unchanged_page_repeat_is_blocked(self):
        observation = {'url': 'https://example.test', 'title': '', 'visible_text': '', 'targets': []}
        session = AsyncMock(); session.page.url = observation['url']
        session.observe.return_value = observation
        session.apply.return_value = ('s', 'applied')
        task = {'access': [{'siteId': 's', 'url': observation['url']}]}
        with patch.object(planner, 'InvestigationSession', return_value=session), patch.object(model, 'complete_with_retry', return_value='{"action":"click","target":"rfq-1"}'):
            await planner.run_planner(task, session.page, {'site_id': 's'}, EvidenceLedger(), 3)
        self.assertEqual(session.apply.await_count, 1)

    async def test_ledger_keeps_all_evidence(self):
        ledger = EvidenceLedger()
        for i in range(80): await ledger.add(Evidence('fact', str(i), 's', 'url', 'title', i))
        self.assertEqual(len(await ledger.snapshot()), 80)

    async def test_run_cannot_launch_browser(self):
        with patch.dict('os.environ', {'CHALLENGE_RUN_TOKEN': 'test'}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'CDP'):
                await browser.connect(AsyncMock())

    async def test_transient_model_retry(self):
        from openai import APITimeoutError
        import httpx
        with patch.object(model, 'complete', side_effect=[APITimeoutError(request=httpx.Request('POST', 'https://example.test')), 'ok']), patch('asyncio.sleep', new_callable=AsyncMock):
            self.assertEqual(await model.complete_with_retry([], 10, lambda: 30), 'ok')

    def test_document_formats(self):
        self.assertEqual(parse_document(b'\xef\xbb\xbfcolumn\nvalue', 'selected.csv'), 'column\nvalue')
        self.assertNotIn('secret', parse_document(b'<p>visible</p><script>secret</script>', 'selected.html'))
        with self.assertRaises(ValueError): parse_document(b'unknown', 'selected.exe')


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def test_disabled_fieldset_and_slider_outcome(self):
        await self.page.set_content('<p>Human verification</p><input type="range" min="0" max="100" value="0"><fieldset disabled><input name="receipt"></fieldset>')
        observation = await planner.observe(self.page, [], None)
        slider, receipt = observation['targets']
        self.assertTrue(receipt['disabled'])
        with self.assertRaisesRegex(ValueError, 'disabled'):
            await planner._apply({'action': 'fill', 'target': receipt['id'], 'value': 'test'}, self.page, [], None)
        _, result = await planner._apply({'action': 'drag_to_end', 'target': slider['id']}, self.page, [], None)
        self.assertIn('maximum', result)
        self.assertEqual(await self.page.locator('input[type=range]').input_value(), '100')

    async def test_failed_slider_gesture_is_not_success(self):
        await self.page.set_content('<p>Human verification</p><input type="range" min="0" max="100" value="0" oninput="this.value=0">')
        observation = await planner.observe(self.page, [], None)
        with self.assertRaisesRegex(ValueError, 'did not reach'):
            await planner._apply({'action': 'drag_to_end', 'target': observation['targets'][0]['id']}, self.page, [], None)

    async def test_model_selected_frame(self):
        from rfq_agent.documents import InvestigationSession
        await self.page.route('https://example.test/**', lambda route: route.fulfill(body='<iframe src="https://example.test/frame"></iframe>' if route.request.url.endswith('/main') else '<p>Selected frame fact</p>'))
        await self.page.goto('https://example.test/main')
        session = InvestigationSession(self.page, [{'site_id': 's', 'url': 'https://example.test'}])
        observation = await session.observe('s')
        self.assertNotIn('Selected frame fact', observation['visible_text'])
        await session.apply({'action': 'select_frame', 'index': observation['frames'][0]['index']}, 's')
        self.assertIn('Selected frame fact', (await session.observe('s'))['visible_text'])

    async def test_download_becomes_evidence_observation(self):
        from rfq_agent.documents import InvestigationSession
        async def respond(route):
            if route.request.url.endswith('/file'):
                await route.fulfill(body='header\nSelected document fact', headers={'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename="selected.csv"'})
            else:
                await route.fulfill(body='<a href="/file">Selected document</a>')
        await self.page.route('https://example.test/**', respond)
        await self.page.goto('https://example.test/main')
        session = InvestigationSession(self.page, [{'site_id': 's', 'url': 'https://example.test'}])
        observation = await session.observe('s')
        await session.apply({'action': 'click', 'target': observation['targets'][0]['id']}, 's')
        observation = await session.observe('s')
        self.assertIn('Selected document fact', observation['visible_text'])
        self.assertEqual(observation['url'], 'https://example.test/file')
        await session.apply({'action': 'return_to_page'}, 's')
        self.assertNotIn('Selected document fact', (await session.observe('s'))['visible_text'])

    async def test_shifted_accessible_controls_and_dropdown(self):
        # Unfamiliar labels, IDs, order and custom ARIA controls: no public fixture data.
        await self.page.set_content('''<span id="random-caption">Account identifier</span>
            <input id="unfamiliar-id" aria-labelledby="random-caption">
            <div role="checkbox" tabindex="0" aria-label="Acknowledgment">Confirm</div>
            <select aria-label="Issuer"><option value="all">Everyone</option>
            <option value="synthetic-issuer">Example organization</option></select>''')
        observation = await planner.observe(self.page, [], None)
        self.assertIn('Account identifier', observation['targets'][0]['label'])
        self.assertEqual(observation['targets'][1]['role'], 'checkbox')
        dropdown = observation['targets'][2]
        self.assertEqual(dropdown['options'][1]['value'], 'synthetic-issuer')
        await planner._apply({'action': 'select_option', 'target': dropdown['id'], 'value': 'synthetic-issuer'}, self.page, [], None)
        self.assertEqual(await self.page.locator('select').input_value(), 'synthetic-issuer')
        with self.assertRaisesRegex(ValueError, 'enabled option'):
            await planner._apply({'action': 'select_option', 'target': dropdown['id'], 'value': 'invented'}, self.page, [], None)

    async def test_long_selected_page_is_readable_without_crawling(self):
        from rfq_agent.documents import InvestigationSession
        await self.page.set_content('<p>' + 'x' * 15000 + ' Later relevant fact</p>')
        session = InvestigationSession(self.page, [])
        observation = await session.observe(None)
        self.assertNotIn('Later relevant fact', observation['visible_text'])
        await session.apply({'action': 'read_page', 'offset': 14000}, None)
        self.assertIn('Later relevant fact', (await session.observe(None))['visible_text'])
