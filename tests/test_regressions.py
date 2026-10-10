import json
import unittest
from unittest.mock import AsyncMock, patch
from rfq_agent import planner, browser, model
from rfq_agent.evidence import Evidence, EvidenceLedger
from rfq_agent.documents import parse_document


class RegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_navigation_relevance_is_a_model_decision(self):
        loop = AsyncMock()
        loop.decide.return_value = '{"allowed":false}'
        self.assertFalse(await planner.review_navigation(loop, 'Find delivery approval',
                         {'text': 'Signing code request 287'}, 'Open delivery message'))
        loop.decide.return_value = '{"allowed":true}'
        self.assertTrue(await planner.review_navigation(loop, 'Find delivery approval',
                        {'text': 'Approved delivery commitment'}, 'Read delivery message'))

    def test_search_remains_available_while_gate_is_incomplete(self):
        obs = {'targets': [
            {'id': 'slider', 'gate_id': 'g', 'type': 'range', 'slider_value': 0, 'slider_maximum': 100},
            {'id': 'query', 'tag': 'input', 'type': 'search'},
            {'id': 'submit', 'tag': 'button', 'type': 'submit', 'form_has_search': True},
            {'id': 'decoy', 'tag': 'a'}]}
        branches = planner.decision_schema(obs, [], {'objective': 'Find approval'})['properties']['decision']['anyOf']
        click = next(b for b in branches if b['properties']['action']['enum'] == ['click'])
        # A pending gate must not choose navigation policy or hide enabled links.
        self.assertEqual(click['properties']['target']['enum'], ['submit', 'decoy'])
        fill = next(b for b in branches if b['properties']['action']['enum'] == ['fill'])
        self.assertEqual(fill['properties']['target']['enum'], ['query'])
        self.assertIn('purpose', fill['required'])

    async def test_focused_completion_requires_model_verification(self):
        loop = AsyncMock()
        loop.decide.return_value = '{"complete":true}'
        self.assertTrue(await planner.review_completion(loop, {'objective': 'Read original code'},
                        {'visible_text': 'Original code: invented', 'url': 'https://example.test'}, [], []))
        loop.decide.return_value = '{"complete":false}'
        self.assertFalse(await planner.review_completion(loop, {'objective': 'Find delivery terms'},
                         {'visible_text': 'Original code: invented', 'url': 'https://example.test'}, [], []))

    def test_gated_message_heading_is_not_body_evidence(self):
        obs = {'gated_disclosures': True, 'disclosed_text': ''}
        self.assertTrue(planner.access_only_quote('Message request 15\nUnlocked\nOriginal body', obs))
        obs['disclosed_text'] = 'Invented original message: delivery 23 days.'
        self.assertFalse(planner.access_only_quote(obs['disclosed_text'], obs))

    def test_body_frame_must_be_read_before_leaving(self):
        obs = {'selected_frame': 1, 'source_needs_quote': True, 'targets': [],
               'visible_text': 'Original body: invented content', 'tabs': [{'index': 2}]}
        kinds = {b['properties']['action']['enum'][0] for b in
                 planner.decision_schema(obs, [], {})['properties']['decision']['anyOf']}
        self.assertIn('record_evidence', kinds)
        self.assertFalse(kinds & {'return_to_page', 'select_tab', 'open_site', 'finish'})

    def test_unchanged_page_cannot_loop_on_screenshots_notes_or_scroll(self):
        obs = {'targets': [], 'scroll_state': {'up': True, 'down': True, 'nested': True}}
        attempts = {('inspect_screen', ''), ('remember', ''), ('scroll', 'down')}
        branches = planner.decision_schema(obs, [], {}, attempted_targets=attempts)['properties']['decision']['anyOf']
        kinds = {b['properties']['action']['enum'][0] for b in branches}
        self.assertNotIn('inspect_screen', kinds)
        self.assertNotIn('remember', kinds)
        scroll = next(b for b in branches if b['properties']['action']['enum'] == ['scroll'])
        self.assertEqual(scroll['properties']['direction']['enum'], ['up'])

    def test_modal_dismissal_and_empty_evidence_choices(self):
        obs = {'visible_text': 'Notice', 'targets': [
            {'id': 'close', 'tag': 'button', 'text': '×', 'in_active_modal': True},
            {'id': 'redirect', 'tag': 'a', 'text': 'Continue', 'in_active_modal': True},
            {'id': 'behind', 'tag': 'button', 'text': 'Message'}]}
        branches = planner.decision_schema(obs, [], {})['properties']['decision']['anyOf']
        click = next(b for b in branches if b['properties']['action']['enum'] == ['click'])
        self.assertEqual(click['properties']['target']['enum'], ['close'])
        self.assertFalse(any(b['properties']['action']['enum'] == ['record_evidence'] for b in branches))
        empty = planner.decision_schema({'visible_text': '', 'targets': []}, [], {})
        self.assertFalse(any(b['properties']['action']['enum'] == ['record_evidence'] for b in empty['properties']['decision']['anyOf']))

    def test_pending_body_frame_precedes_evidence(self):
        obs = {'visible_text': 'Message heading', 'targets': [], 'selected_frame': None,
               'source_needs_quote': True, 'frames': [{'index': 2, 'title': 'Original body'}]}
        branches = planner.decision_schema(obs, [], {})['properties']['decision']['anyOf']
        self.assertFalse(any(b['properties']['action']['enum'] == ['record_evidence'] for b in branches))
        frame = next(b for b in branches if b['properties']['action']['enum'] == ['select_frame'])
        self.assertEqual(frame['properties']['index']['enum'], [2])

    def test_unchecked_frame_gate_cannot_quote_or_finish(self):
        obs = {'visible_text': 'Human verification', 'targets': [],
               'verification_gates': [{'sliders': [{'value': 100, 'maximum': 100}],
                                        'checkboxes': [{'checked': False}]}]}
        kinds = [b['properties']['action']['enum'][0] for b in
                 planner.decision_schema(obs, [], {})['properties']['decision']['anyOf']]
        self.assertNotIn('record_evidence', kinds)
        self.assertNotIn('finish', kinds)

    def test_source_quote_retains_actual_invisible_and_whitespace_text(self):
        source = 'Original body: delivery\u200b period\n\n23 days.'
        self.assertEqual(planner.source_quote('delivery period 23 days.', source),
                         'delivery\u200b period\n\n23 days.')
        with self.assertRaises(ValueError):
            planner.source_quote('delivery period 24 days.', source)

    def test_gate_instructions_do_not_count_as_source_evidence(self):
        observation = {'targets': [{'gate_id': 'g', 'type': 'range', 'label': 'Move right'},
                                   {'gate_id': 'g', 'type': 'checkbox', 'label': 'Verify human'}]}
        self.assertTrue(planner.access_only_quote('Move right   Verify human', observation))
        self.assertFalse(planner.access_only_quote('Original delivery: 23 days', observation))

    def test_unchanged_target_attempt_is_removed_from_choices(self):
        obs = {'url': 'https://example.test', 'targets': [{'id': 'message', 'tag': 'a', 'text': 'Message'}, {'id': 'robot', 'tag': 'input', 'type': 'checkbox'}], 'text_length': 30}
        schema = planner.decision_schema(obs, [], {}, attempted_targets={('click', 'message')})
        click = next(b for b in schema['properties']['decision']['anyOf'] if b['properties']['action']['enum'] == ['click'])
        self.assertEqual(click['properties']['target']['enum'], ['robot'])
        self.assertFalse(any(b['properties']['action']['enum'] == ['read_page'] for b in schema['properties']['decision']['anyOf']))
        wait = next(b for b in schema['properties']['decision']['anyOf'] if b['properties']['action']['enum'] == ['wait'])
        self.assertEqual(wait['properties']['milliseconds']['minimum'], 250)
        self.assertEqual(wait['properties']['milliseconds']['maximum'], 3000)
        waited = planner.decision_schema(obs, [], {}, attempted_targets={('wait', '')})
        self.assertFalse(any(b['properties']['action']['enum'] == ['wait'] for b in waited['properties']['decision']['anyOf']))

    def test_action_contract_rejects_missing_fields_and_button_press(self):
        for action in [{'action': 'fill_credential', 'credential_key': 'password'}, {'action': 'press', 'target': 'rfq-3', 'key': 'click'}]:
            with self.assertRaises(ValueError): planner._parse_action(json.dumps(action))
        self.assertEqual(planner._parse_action('{"decision":{"action":"click","target":"rfq-3"}}')['action'], 'click')

    def test_live_schema_constrains_initial_site_and_empty_credential_fields(self):
        sites = [{'site_id': 'one', 'url': 'https://one.test', 'credential_keys': ['username', 'password']}, {'site_id': 'two', 'url': 'https://two.test', 'credential_keys': ['username', 'password']}]
        blank = planner.decision_schema({'url': 'about:blank', 'targets': []}, sites, {'site_id': 'two'})
        branch = next(b for b in blank['properties']['decision']['anyOf'] if b['properties']['action']['enum'] == ['open_site'])
        self.assertEqual(branch['properties']['site_id']['enum'], ['two'])
        without_evidence = planner.decision_schema({'url': 'about:blank', 'targets': []}, sites, {'site_id': 'two'}, has_evidence=False)
        self.assertFalse(any(b['properties']['action']['enum'] == ['finish'] for b in without_evidence['properties']['decision']['anyOf']))
        form = {'url': 'https://two.test/login', 'targets': [{'id': 'filled', 'tag': 'input', 'populated': True}, {'id': 'empty', 'tag': 'input', 'type': 'password', 'populated': False}, {'id': 'button', 'tag': 'button'}]}
        schema = planner.decision_schema(form, sites, {'site_id': 'two'})
        credential = next(b for b in schema['properties']['decision']['anyOf'] if b['properties']['action']['enum'] == ['fill_credential'])
        self.assertEqual(credential['properties']['target']['enum'], ['empty'])
        self.assertFalse(any(b['properties']['action']['enum'] == ['press'] for b in schema['properties']['decision']['anyOf']))

    async def test_cdp_alias_connections_get_distinct_tabs(self):
        page_one, page_two = object(), object()
        context = AsyncMock(); context.new_page.side_effect = [page_one, page_two]
        instance = AsyncMock(); instance.contexts = [context]
        pw = AsyncMock(); pw.chromium.connect_over_cdp.return_value = instance
        with patch.object(browser, 'cdp_urls', return_value=['http://local.test:1', 'http://local.test:1']):
            first = await browser.connect(pw, 0)
            second = await browser.connect(pw, 1)
        self.assertIs(first[1], page_one)
        self.assertIs(second[1], page_two)

    def test_openai_defaults_and_local_empty_key_fallback(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}, clear=True), patch.object(model, 'load_dotenv'), patch.object(model, 'dotenv_values', return_value={'OPENAI_API_KEY': 'invented-test-key'}):
            self.assertEqual(model.configuration(), ('openai', 'gpt-5-nano', 'https://api.openai.com/v1', 'invented-test-key'))

    def test_scored_openai_uses_proxy_and_never_local_dotenv(self):
        env = {'CHALLENGE_RUN_TOKEN': 'invented-run', 'LLM_PROXY_URL': 'https://platform.test/llm/run/invented', 'OPENAI_BASE_URL': 'https://api.openai.com/v1', 'OPENAI_API_KEY': 'invented-team-key'}
        with patch.dict('os.environ', env, clear=True), patch.object(model, 'load_dotenv') as load:
            self.assertEqual(model.configuration()[2], env['LLM_PROXY_URL'] + '/openai/v1')
            load.assert_not_called()
        del env['LLM_PROXY_URL']
        with patch.dict('os.environ', env, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'LLM_PROXY_URL'):
                model.configuration()

    def test_qwen_remains_explicitly_available(self):
        env = {'RFQ_MODEL_PROVIDER': 'qwen', 'QWEN_BASE_URL': 'https://platform.test/qwen/v1', 'QWEN_API_KEY': 'invented'}
        with patch.dict('os.environ', env, clear=True), patch.object(model, 'load_dotenv'):
            self.assertEqual(model.configuration()[:2], ('qwen', model.QWEN_MODEL))

    async def test_dispatch_allows_slow_start_and_preserves_reserve(self):
        sites = [{'site_id': 'shifted-site', 'url': 'https://example.test', 'credential_keys': []}]
        response = json.dumps({'assignments': [{'site_id': 'shifted-site', 'objective': 'Read the runtime evidence'}]})
        with patch.object(model, 'complete_with_retry', return_value=response) as call, patch.object(planner, 'seconds_left', return_value=1200):
            assignments = await planner.plan_assignments({'brief': 'Invented test brief'}, sites, 1)
            self.assertEqual(call.call_args.kwargs['budget'](), 900)
        self.assertEqual(assignments[0]['site_id'], 'shifted-site')
        self.assertEqual(call.call_args.kwargs['timeout'], 360)
        self.assertEqual(call.call_args.kwargs['phase'], 'dispatch')

    async def test_dispatch_transport_failure_is_not_retried_by_outer_loop(self):
        sites = [{'site_id': 's', 'url': 'https://example.test', 'credential_keys': []}]
        with patch.object(model, 'complete_with_retry', side_effect=TimeoutError) as call:
            with self.assertRaises(TimeoutError):
                await planner.plan_assignments({'brief': 'Invented test brief'}, sites, 1)
        self.assertEqual(call.await_count, 1)

    async def test_startup_reports_failed_phase_without_extra_checklist_call(self):
        from rfq_agent import __main__ as workflow
        artifacts = {}
        task = {'brief': 'Invented test brief', 'access': [{'siteId': 's', 'url': 'https://example.test'}]}
        with patch.object(workflow.run_contract, 'load_run', return_value=(task, None)), patch.object(browser, 'available_count', return_value=1), patch.object(planner, 'plan_assignments', side_effect=TimeoutError), patch.object(workflow.InvestigationState, 'call', new_callable=AsyncMock) as coordinator, patch.object(workflow, 'write_artifact', side_effect=lambda name, value: artifacts.update({name: value})):
            self.assertEqual(await workflow.main(), 1)
        coordinator.assert_not_awaited()
        self.assertEqual(artifacts['workflow.json']['failure'], {'phase': 'dispatch', 'error_type': 'TimeoutError'})
        self.assertEqual(artifacts['workflow.json']['investigations'], [])

    async def test_reauthentication_after_state_transition(self):
        login = {'url': 'https://example.test/login', 'title': 'login', 'visible_text': '', 'targets': [
            {'id': 'rfq-1', 'tag': 'input', 'type': 'text', 'autocomplete': 'username', 'name': 'username', 'populated': False},
            {'id': 'rfq-2', 'tag': 'button', 'type': 'button'}]}
        home = dict(login, url='https://example.test/home')
        actions = [{'action': 'fill_credential', 'target': 'rfq-1', 'credential_key': 'username'},
                   {'action': 'click', 'target': 'rfq-2'},
                   {'action': 'fill_credential', 'target': 'rfq-1', 'credential_key': 'username'}]
        session = AsyncMock()
        session.notes = []; session.history = []
        session.page.url = 'https://example.test/login'
        session.observe.side_effect = [login, home, login]
        session.apply.return_value = ('s', 'applied')
        task = {'access': [{'siteId': 's', 'url': 'https://example.test', 'credentials': {'username': 'invented-login'}}]}
        with patch.object(planner, 'InvestigationSession', return_value=session), patch.object(model, 'complete_with_retry', side_effect=[json.dumps(a) for a in actions]):
            result = await planner.run_planner(task, session.page, {'site_id': 's'}, EvidenceLedger(), 3)
        self.assertEqual(session.apply.await_count, 3)
        self.assertEqual(result['status'], 'exhausted')

    async def test_unchanged_page_repeat_is_blocked(self):
        observation = {'url': 'https://example.test', 'title': '', 'visible_text': '', 'targets': [
            {'id': 'rfq-1', 'tag': 'button', 'type': 'button'}]}
        session = AsyncMock(); session.notes = []; session.history = []; session.page.url = observation['url']
        session.observe.return_value = observation
        session.apply.return_value = ('s', 'applied')
        task = {'access': [{'siteId': 's', 'url': observation['url']}]}
        with patch.object(planner, 'InvestigationSession', return_value=session), patch.object(model, 'complete_with_retry', return_value='{"action":"click","target":"rfq-1"}'):
            await planner.run_planner(task, session.page, {'site_id': 's'}, EvidenceLedger(), 3)
        self.assertEqual(session.apply.await_count, 1)

    async def test_ledger_keeps_all_evidence(self):
        ledger = EvidenceLedger()
        for i in range(80): await ledger.add(Evidence('fact', str(i), 's', 'url', 'title', i))
        self.assertFalse(await ledger.add(Evidence('another claim', '0', 's', 'url', 'title', 81)))
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
    async def test_unlabelled_image_requests_visual_observation(self):
        await self.page.set_content('<canvas width="500" height="90"></canvas><label>Access number<input required></label>')
        observation = await planner.observe(self.page, [], None)
        self.assertEqual(observation['visual_content'][0]['kind'], 'canvas')
        self.assertTrue(planner._has_visual_challenge(observation))
        await self.page.set_content('<fieldset disabled><canvas width="500" height="90"></canvas></fieldset>')
        self.assertFalse((await planner.observe(self.page, [], None))['visual_content'])

    async def test_grouped_unlock_only_executes_the_selected_pair(self):
        section = ('<section><h2>{name}</h2><input type="range" value="0" min="0" max="100">'
                   '<input type="checkbox" onchange="this.parentElement.querySelector(\'fieldset\').disabled='
                   '!(this.checked && this.parentElement.querySelector(\'input[type=range]\').value==100)">'
                   '<fieldset disabled>Private selected content</fieldset></section>')
        await self.page.set_content(section.format(name='First region') + section.format(name='Other region'))
        obs = await planner.observe(self.page, [], None)
        sliders = [t for t in obs['targets'] if t.get('type') == 'range']
        boxes = [t for t in obs['targets'] if t.get('type') == 'checkbox']
        with self.assertRaisesRegex(ValueError, 'belonging'):
            await planner._apply({'action': 'unlock_gate', 'target': sliders[0]['id'], 'checkbox': boxes[1]['id']}, self.page, [], None)
        self.assertEqual(await self.page.locator('input[type=range]').first.input_value(), '0')
        await planner._apply({'action': 'unlock_gate', 'target': sliders[0]['id'], 'checkbox': boxes[0]['id']}, self.page, [], None)
        self.assertTrue(await self.page.locator('input[type=checkbox]').first.is_checked())
        self.assertFalse(await self.page.locator('input[type=checkbox]').nth(1).is_checked())
        self.assertFalse(await self.page.locator('fieldset').first.evaluate('el => el.disabled'))
        self.assertTrue(await self.page.locator('fieldset').nth(1).evaluate('el => el.disabled'))

    async def test_search_submit_uses_native_semantics_not_button_language(self):
        await self.page.set_content('<form onsubmit="event.preventDefault();document.querySelector(\'#result\').textContent=\'Found\'">'
                                    '<input type="search" value="approval"><button type="submit">Buscar</button></form><p id="result"></p>')
        obs = await planner.observe(self.page, [], None)
        target = next(t for t in obs['targets'] if t['tag'] == 'button')
        await planner._apply({'action': 'click', 'target': target['id']}, self.page, [], None)
        self.assertEqual(await self.page.locator('#result').inner_text(), 'Found')

    async def test_body_frame_is_offered_only_after_parent_disclosure_opens(self):
        from rfq_agent.documents import InvestigationSession
        sites = [{'site_id': 's', 'url': 'https://example.test'}]
        await self.page.route('https://example.test/**', lambda route: route.fulfill(content_type='text/html', body=
            '<section><p>Human verification</p><input type="range" value="0"><label><input type="checkbox">Verify human</label><fieldset disabled><p>Invented original body: 31 days.</p></fieldset></section>'
            if route.request.url.endswith('/body') else '<details><summary>Read message</summary><iframe title="Original body" src="/body"></iframe></details>'))
        await self.page.goto('https://example.test/main')
        session = InvestigationSession(self.page, sites)
        obs = await session.observe('s')
        self.assertEqual(obs['frames'], [])
        summary = next(t for t in obs['targets'] if t['tag'] == 'summary')
        await session.apply({'action': 'click', 'target': summary['id']}, 's')
        obs = await session.observe('s')
        self.assertEqual(len(obs['frames']), 1)
        self.assertEqual(obs['frames'][0]['title'], 'Original body')
        await session.apply({'action': 'select_frame', 'index': obs['frames'][0]['index']}, 's')
        obs = await session.observe('s')
        self.assertNotIn('31 days', obs['visible_text'])
        self.assertTrue(obs['verification_gates'])
        self.assertFalse(any(b['properties']['action']['enum'] == ['select_frame'] for b in planner.decision_schema(obs, sites, {'site_id': 's'})['properties']['decision']['anyOf']))

    async def test_locked_fieldset_anchors_and_summaries_are_not_offered(self):
        await self.page.set_content('<section><input type="range" value="0"><label><input type="checkbox">I am not a robot</label><fieldset disabled><a href="/message">Invented protected message</a><details><summary>Open reading pane</summary><p>Protected source text</p></details></fieldset></section>')
        obs = await planner.observe(self.page, [], None)
        anchor = next(t for t in obs['targets'] if t['tag'] == 'a')
        summary = next(t for t in obs['targets'] if t['tag'] == 'summary')
        self.assertTrue(anchor['disabled']); self.assertTrue(summary['disabled'])
        self.assertNotIn('Invented protected message', obs['visible_text'])
        self.assertIn(anchor['id'], obs['verification_gates'][0]['disabled_targets'])
        with self.assertRaisesRegex(ValueError, 'locked section'):
            await planner._apply({'action': 'click', 'target': anchor['id']}, self.page, [], None)
        await self.page.locator('fieldset').evaluate('el => el.disabled=false')
        unlocked = await planner.observe(self.page, [], None)
        self.assertFalse(next(t for t in unlocked['targets'] if t['tag'] == 'a')['disabled'])

    async def test_checked_body_gate_with_locked_plain_text_is_not_readable(self):
        await self.page.set_content('<section><input type="range" value="100"><input type="checkbox" checked><fieldset disabled><p>Protected original body: 31 days</p></fieldset></section>')
        obs = await planner.observe(self.page, [], None)
        self.assertEqual(obs['verification_gates'][0]['disabled_targets'], [])
        self.assertTrue(obs['verification_gates'][0]['protected_locked'])
        self.assertNotIn('31 days', obs['visible_text'])
        kinds = {b['properties']['action']['enum'][0] for b in
                 planner.decision_schema(obs, [], {})['properties']['decision']['anyOf']}
        self.assertNotIn('record_evidence', kinds)
        self.assertNotIn('finish', kinds)

    async def test_separate_gate_contexts_and_collapsed_reading_area(self):
        await self.page.set_content('<section><h2>Message list</h2><label>Verification<input type="range" value="100"></label><input type="checkbox" checked><fieldset><button>Open message</button></fieldset></section><section><h2>Reading area</h2><input type="range" value="0"><input type="checkbox"><fieldset disabled><details><summary>Expand reading area</summary><p>Hidden message content</p></details></fieldset></section>')
        obs = await planner.observe(self.page, [], None)
        left = next(t for t in obs['targets'] if t.get('text') == 'Open message')
        right = next(t for t in obs['targets'] if t.get('tag') == 'summary')
        self.assertNotEqual(left['gate_id'], right['gate_id'])
        self.assertIn('Message list', left['gate_context'])
        self.assertIn('Reading area', right['gate_context'])
        self.assertFalse(right['disclosure_open'])
        schema = planner.decision_schema(obs, [], {})
        drag = next(b for b in schema['properties']['decision']['anyOf'] if b['properties']['action']['enum'] == ['drag_to_end'])
        sliders = [t for t in obs['targets'] if t.get('type') == 'range']
        self.assertEqual(sliders[0]['slider_maximum'], 100)
        self.assertNotIn(sliders[0]['id'], drag['properties']['target']['enum'])
        self.assertIn(sliders[1]['id'], drag['properties']['target']['enum'])
        self.assertFalse(any(b['properties']['action']['enum'] == ['fill']
                             for b in schema['properties']['decision']['anyOf']))
        with self.assertRaisesRegex(ValueError, 'editable text field'):
            await planner._apply({'action': 'fill', 'target': sliders[1]['id'], 'value': '100'}, self.page, [], None)
        click = next(b for b in schema['properties']['decision']['anyOf']
                     if b['properties']['action']['enum'] == ['click'])
        box = next(t for t in obs['targets'] if t.get('type') == 'checkbox' and not t.get('checked'))
        self.assertNotIn(box['id'], click['properties']['target']['enum'])
        with self.assertRaisesRegex(ValueError, 'slider to maximum'):
            await planner._apply({'action': 'click', 'target': box['id']}, self.page, [], None)
        await self.page.locator('input[type=range]').nth(1).fill('100')
        ready = await planner.observe(self.page, [], None)
        choices = planner.decision_schema(ready, [], {})['properties']['decision']['anyOf']
        click = next(b for b in choices if b['properties']['action']['enum'] == ['click'])
        self.assertIn(box['id'], click['properties']['target']['enum'])
        self.assertNotIn(sliders[0]['id'], click['properties']['target']['enum'])
        with self.assertRaisesRegex(ValueError, 'drag_to_end'):
            await planner._apply({'action': 'click', 'target': sliders[0]['id']}, self.page, [], None)

    async def test_disclosure_control_can_reveal_selected_text(self):
        await self.page.set_content('<details><summary>Reading area</summary><p>Invented selected message</p></details>')
        obs = await planner.observe(self.page, [], None)
        target = next(t for t in obs['targets'] if t['tag'] == 'summary')
        await planner._apply({'action': 'click', 'target': target['id']}, self.page, [], None)
        self.assertIn('Invented selected message', (await planner.observe(self.page, [], None))['visible_text'])

    async def test_disclosure_provenance_keeps_closed_preview_separate(self):
        await self.page.set_content('<details><summary>Draft</summary>False code 000000</details>'
                                    '<details open><summary>Original</summary>Correct code 123456</details>')
        obs = await planner.observe(self.page, [], None)
        sections = {s['label']: s for s in obs['disclosure_sections']}
        self.assertFalse(sections['Draft']['open'])
        self.assertEqual(sections['Draft']['text'], '')
        self.assertIn('123456', sections['Original']['text'])
        self.assertNotIn('000000', obs['visible_text'])

    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def test_worker_cannot_select_another_workers_tab(self):
        from rfq_agent.documents import InvestigationSession
        context = await self.browser.new_context()
        self.page = await context.new_page()
        sites = [{'site_id': 's', 'url': 'https://example.test', 'credential_keys': [], 'credentials': {}}]
        await context.route('https://example.test/**', lambda route: route.fulfill(body='<p>Worker one</p>'))
        await self.page.goto('https://example.test/one')
        other = await self.page.context.new_page()
        await other.goto('https://example.test/two')
        session = InvestigationSession(self.page, sites)
        observation = await session.observe('s')
        self.assertEqual(observation['tabs'], [])
        self.assertEqual(observation['selected_tab'], 0)
        with self.assertRaises(ValueError):
            await session.apply({'action': 'select_tab', 'index': 1}, 's')
        self.assertIs(session.page, self.page)

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
