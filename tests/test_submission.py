import unittest
import json
import time
from copy import deepcopy
from unittest.mock import patch, AsyncMock
from scenarios import scenario, ANSWER_SCHEMA
from rfq_agent.resolution import Resolver
from rfq_agent.pricing import calculate
from rfq_agent.answer import validate_answer
from rfq_agent.submission import SubmissionState, scalar_paths, answer_value, format_value, submit_on_site, ExecutionPolicy, SigningAttempt, submission_schema, review_field_entry
from rfq_agent.records import Unresolved
from rfq_agent.evidence import EvidenceLedger
from rfq_agent import planner


def reviewed(answer):
    text = '\n'.join(f'{path}: {answer_value(answer, path)}' for path in scalar_paths(answer))
    action = {'quote': text, 'observed_answer': deepcopy(answer), 'observed_omitted': [],
              'field_quotes': {path: f'{path}: {answer_value(answer, path)}' for path in scalar_paths(answer)}}
    return action, {'visible_text': text, 'url': 'https://tender.invalid/review'}


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        bundle, _ = scenario(); resolved = Resolver(bundle).resolve()
        self.answer = validate_answer(calculate(resolved), ANSWER_SCHEMA, ['A', 'B'])

    def test_review_rejects_changed_price_and_missing_source(self):
        state = SubmissionState(self.answer, [])
        action, observation = reviewed(self.answer)
        action['observed_answer']['positions'][0]['unit_price'] += .01
        with self.assertRaisesRegex(Unresolved, 'differs'): state.verify_review(action, observation)
        action, observation = reviewed(self.answer); action['field_quotes']['total_net'] = 'invented quote'
        with self.assertRaisesRegex(Unresolved, 'source quote'): state.verify_review(action, observation)
        self.assertFalse(state.reviewed)

    def test_tan_and_receipt_require_verified_state_and_exact_reference(self):
        state = SubmissionState(self.answer, [])
        quote = 'TAN TEST-ORCHARD code SYNTHETIC-CODE'
        with self.assertRaises(Unresolved): state.capture_tan({'quote': quote, 'value': 'SYNTHETIC-CODE'}, {'visible_text': quote})
        action, observation = reviewed(self.answer); state.verify_review(action, observation)
        unrelated = 'TAN OTHER-TENDER code SYNTHETIC-CODE'
        with self.assertRaises(Unresolved): state.capture_tan({'quote': unrelated, 'value': 'SYNTHETIC-CODE'}, {'visible_text': unrelated})
        state.capture_tan({'quote': quote, 'value': 'SYNTHETIC-CODE'}, {'visible_text': quote})
        receipt = 'Accepted TEST-ORCHARD receipt RECEIPT-INVENTED'
        action = {'quote': receipt, 'receipt_id': 'RECEIPT-INVENTED'}
        observation = {'visible_text': receipt, 'url': 'https://tender.invalid/receipt'}
        with self.assertRaises(Unresolved): state.confirm_receipt(action, observation)
        state.commit_initiated = True; state.confirm_receipt(action, observation)
        self.assertEqual(state.receipt['receipt_id'], 'RECEIPT-INVENTED')

    def test_review_requires_evidence_for_each_omitted_position(self):
        state = SubmissionState(self.answer, ['MISSING'])
        action, observation = reviewed(self.answer)
        action['observed_omitted'] = ['MISSING']
        with self.assertRaisesRegex(Unresolved, 'omitted position'):
            state.verify_review(action, observation)
        observation['visible_text'] += '\nMISSING: omitted'
        action['omission_quotes'] = {'MISSING': 'MISSING: omitted'}
        state.verify_review(action, observation)
        self.assertTrue(state.reviewed)

    def test_formatting_is_presentation_not_recalculation(self):
        self.assertEqual(format_value(12.34, 'decimal_comma'), '12,34')
        self.assertEqual(answer_value(self.answer, 'positions.0.quantity'), 3)
        with self.assertRaises(Unresolved): answer_value(self.answer, 'positions.0.guessed_price')
        with self.assertRaises(Unresolved): format_value(12.34, 'integer')

    def test_signing_request_is_latched_once_and_expires(self):
        attempt = SigningAttempt()
        with self.assertRaises(Unresolved): attempt.mark_requested()
        attempt.access = {'siteId': 'invented'}
        attempt.mark_requested()
        with self.assertRaises(Unresolved): attempt.mark_requested()
        attempt.requested_at = time.monotonic() - 301
        with self.assertRaisesRegex(Unresolved, 'expired'): attempt.check_validity()

    def test_contract_rejects_invented_paths_readonly_targets_and_early_commit(self):
        from jsonschema import validate, ValidationError
        observation = {'url': 'https://tender.invalid/main', 'visible_text': 'Form', 'targets': [
            {'id': 'editable', 'tag': 'input', 'type': 'text'},
            {'id': 'chrome', 'tag': 'input', 'type': 'text', 'readonly': True},
            {'id': 'button', 'tag': 'button', 'type': 'button'}]}
        schema = submission_schema(observation, [], SubmissionState(self.answer, []), SigningAttempt())
        action = {'action': 'fill_answer', 'target': 'editable', 'path': 'tender_reference', 'format': 'text'}
        validate({'decision': action}, schema)
        for change in ({'path': 'answer.tender_reference'}, {'target': 'chrome'}):
            with self.assertRaises(ValidationError):
                validate({'decision': dict(action, **change)}, schema)
        with self.assertRaises(ValidationError):
            validate({'decision': {'action': 'click', 'target': 'button', 'purpose': 'commit'}}, schema)
        self.assertFalse(any(item['properties']['action']['enum'] == ['verify_review']
                             for item in schema['properties']['decision']['anyOf']))

    def test_review_requires_entry_and_receipt_requires_commit(self):
        observation = {'url': 'https://tender.invalid/main', 'visible_text': 'Form', 'targets': []}
        state = SubmissionState(self.answer, ['unfinished'])
        state.filled_paths.add('tender_reference')
        schema = submission_schema(observation, [], state, SigningAttempt())
        kinds = [item['properties']['action']['enum'][0] for item in schema['properties']['decision']['anyOf']]
        self.assertNotIn('verify_review', kinds)
        state.omitted_entered.add('unfinished')
        schema = submission_schema(observation, [], state, SigningAttempt())
        kinds = [item['properties']['action']['enum'][0] for item in schema['properties']['decision']['anyOf']]
        self.assertIn('verify_review', kinds)
        self.assertNotIn('confirm_receipt', kinds)
        state.commit_initiated = True
        schema = submission_schema(observation, [], state, SigningAttempt())
        kinds = [item['properties']['action']['enum'][0] for item in schema['properties']['decision']['anyOf']]
        self.assertIn('confirm_receipt', kinds)
        self.assertNotIn('fill_answer', kinds)
        self.assertNotIn('verify_review', kinds)


class SubmissionBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_currency_cannot_be_entered_as_company_name(self):
        loop = AsyncMock()
        loop.decide.return_value = '{"allowed":false,"reason":"currency is not company identity"}'
        with self.assertRaisesRegex(Unresolved, 'field meaning'):
            await review_field_entry(loop, {'brief': 'Bidder: Invented Orchard Ltd'},
                                     {'currency': 'EUR'},
                                     {'action': 'fill_answer', 'path': 'currency'},
                                     {'label': 'Company name', 'name': 'organization'}, 'EUR')
        payload = json.loads(loop.decide.call_args.args[1])
        self.assertEqual(payload['observed_field']['label'], 'Company name')
        self.assertEqual(payload['answer_path'], 'currency')

    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(headless=True)
        self.page = await self.browser.new_page()

    async def asyncTearDown(self):
        await self.browser.close(); await self.pw.stop()

    async def test_final_control_requires_capability(self):
        await self.page.set_content('<button type="submit">Sign and submit</button>')
        observation = await planner.observe(self.page, [], None)
        action = {'action': 'click', 'target': observation['targets'][0]['id']}
        with self.assertRaisesRegex(ValueError, 'authorization'): await planner._apply(action, self.page, [], None)
        await planner._apply(action, self.page, [], None, policy=ExecutionPolicy(True, True))

    async def test_observation_failure_keeps_history_without_exception_secrets(self):
        async def fail(task, answer, omitted, page, ledger, signing, steps, history):
            history.append({'step': 1, 'action': 'click', 'result': 'navigation complete'})
            raise RuntimeError('browser message containing SECRET-123')
        with patch('rfq_agent.submission._submit_on_site', side_effect=fail):
            result = await submit_on_site({}, {}, [], self.page, EvidenceLedger())
        self.assertEqual(result['status'], 'unconfirmed')
        self.assertEqual(result['history'][0]['action'], 'click')
        self.assertNotIn('SECRET-123', json.dumps(result))

    async def test_synthetic_signed_receipt_flow(self):
        answer = {'tender_reference': 'SHIFTED-EXAMPLE', 'decision': 'no_bid', 'currency': 'EUR', 'discount_percent': 0.0, 'positions': [], 'total_net': 0.0}
        fields = ''.join(f'<input name="{key}" aria-label="{key}">' for key in ('tender_reference', 'decision', 'currency', 'discount_percent', 'total_net'))
        html = fields + '<input name="challenge_code"><button id="request" onclick="this.disabled=true">Request signing code</button><button onclick="if(confirm(\'Confirm binding submission?\')) document.body.innerHTML=\'Accepted SHIFTED-EXAMPLE receipt R-SYNTHETIC\'">Sign and submit</button>'
        await self.page.route('https://submission.invalid/**', lambda route: route.fulfill(body=html, content_type="text/html"))
        await self.page.goto('https://submission.invalid/main')
        initial_finish = True
        async def next_action(messages, **kwargs):
            nonlocal initial_finish
            if messages[0]['content'].startswith('Audit a proposed form field entry.'):
                return '{"allowed":true,"reason":"matching synthetic field"}'
            if initial_finish:
                initial_finish = False
                return json.dumps({"action": "finish"})
            content = messages[1]['content']
            if isinstance(content, list): content = content[0]['text']
            payload = json.loads(content); obs = payload['observation']; targets = obs['targets']
            if payload['commit_initiated']:
                return json.dumps({'action': 'confirm_receipt', 'quote': obs['visible_text'].strip(), 'receipt_id': 'R-SYNTHETIC'})
            for target in targets:
                key = target['name']
                if key in answer and key != 'positions' and not target['populated']:
                    return json.dumps({'action': 'fill_answer', 'target': target['id'], 'path': key, 'format': 'text'})
            if not payload['review_verified'] or (payload['tan_entered'] and not payload['commit_review_verified']):
                quote = obs['visible_text']
                field_quotes = {}
                for key in scalar_paths(answer):
                    target = next(t for t in targets if t['name'] == key)
                    field_quotes[key] = next(line for line in quote.splitlines() if line.startswith(target['id'] + ':'))
                return json.dumps({'action': 'verify_review', 'quote': quote, 'observed_answer': answer, 'observed_omitted': [], 'omission_quotes': {}, 'field_quotes': field_quotes})
            if not payload['tan_captured']:
                target = next(t for t in targets if t.get('text') == 'Request signing code')
                return json.dumps({'action': 'click', 'target': target['id'], 'purpose': 'request_tan', 'mail_site_id': 'letters'})
            if not payload['tan_entered']:
                target = next(t for t in targets if t['name'] == 'challenge_code')
                return json.dumps({'action': 'fill_tan', 'target': target['id']})
            target = next(t for t in targets if t.get('text') == 'Sign and submit')
            return json.dumps({'action': 'click', 'target': target['id'], 'purpose': 'commit'})
        task = {'brief': 'Synthetic flow only', 'expires_at': (time.time() + 360) * 1000,
                'access': [{'siteId': 'different-site', 'url': 'https://submission.invalid'},
                           {'siteId': 'letters', 'url': 'https://letters.invalid', 'credentials': {'user': 'invented-user'}}],
                'submission': {'kind': 'site', 'url': 'https://submission.invalid/main'}}
        async def baseline(mail_page, access):
            self.assertFalse(await self.page.locator('#request').is_disabled())
            self.assertIsNot(mail_page, self.page)
            self.assertEqual(access['credentials'], {'user': 'invented-user'})
            await self.page.evaluate("document.body.insertAdjacentHTML('afterbegin', '<input readonly name=chrome value=Notice>')")
            return 7
        async def retrieve(mail_page, access, reference, **kwargs):
            self.assertTrue(await self.page.locator('#request').is_disabled())
            self.assertEqual(kwargs['after'], 7)
            self.assertEqual(reference, 'SHIFTED-EXAMPLE')
            return 'FRESH-8123'
        with patch('rfq_agent.model.complete_with_retry', side_effect=next_action), \
             patch('rfq_agent.mail.latest_tan_number', side_effect=baseline) as get_baseline, \
             patch('rfq_agent.mail.get_tan_for_reference', side_effect=retrieve) as get_code:
            result = await submit_on_site(task, answer, [], self.page, EvidenceLedger(), max_steps=20)
        self.assertEqual(result['status'], 'submitted', result)
        get_baseline.assert_awaited_once()
        get_code.assert_awaited_once()
        self.assertEqual(len(self.page.context.pages), 1)
        self.assertEqual(result['receipt']['receipt_id'], 'R-SYNTHETIC')
        self.assertNotIn('finish', [entry['action'] for entry in result['history']])
        self.assertEqual(sum(entry['action'] == 'verify_review' for entry in result['history']), 2)
        self.assertEqual(result['history'][-1]['action'], 'confirm_receipt')
        self.assertNotIn('FRESH-8123', json.dumps(result['history']))
        requests = [entry for entry in result['history'] if entry.get('purpose') == 'request_tan']
        self.assertEqual(len(requests), 2)
        self.assertIn('Reobserve', requests[0]['result'])
        self.assertGreaterEqual(result['signing_metrics']['baseline_elapsed_s'], 0)
        self.assertGreaterEqual(result['signing_metrics']['request_to_code_s'], 0)

    async def test_implicit_submit_button_does_not_bypass_exploration_guard(self):
        await self.page.set_content('<form><button>Unfamiliar action</button></form>')
        observation = await planner.observe(self.page, [], None)
        self.assertEqual(observation['targets'][0]['type'], 'submit')
        with self.assertRaisesRegex(ValueError, 'submission is disabled'):
            await planner._apply({'action': 'click', 'target': observation['targets'][0]['id']}, self.page, [], None)
