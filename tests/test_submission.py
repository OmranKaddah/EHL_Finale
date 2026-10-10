import unittest
import json
import time
from copy import deepcopy
from unittest.mock import patch, AsyncMock
from scenarios import scenario, ANSWER_SCHEMA
from rfq_agent.resolution import Resolver
from rfq_agent.pricing import calculate
from rfq_agent.answer import validate_answer
from rfq_agent.submission import SubmissionState, scalar_paths, answer_value, format_value, submit_on_site, ExecutionPolicy
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

    def test_formatting_is_presentation_not_recalculation(self):
        self.assertEqual(format_value(12.34, 'decimal_comma'), '12,34')
        self.assertEqual(answer_value(self.answer, 'positions.0.quantity'), 3)
        with self.assertRaises(Unresolved): answer_value(self.answer, 'positions.0.guessed_price')
        with self.assertRaises(Unresolved): format_value(12.34, 'integer')


class SubmissionBrowserTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_synthetic_signed_receipt_flow(self):
        answer = {'tender_reference': 'SHIFTED-EXAMPLE', 'decision': 'no_bid', 'currency': 'EUR', 'discount_percent': 0.0, 'positions': [], 'total_net': 0.0}
        fields = ''.join(f'<input name="{key}" aria-label="{key}">' for key in ('tender_reference', 'decision', 'currency', 'discount_percent', 'total_net'))
        html = fields + '<input name="challenge_code"><button onclick="document.body.innerHTML=\'Accepted SHIFTED-EXAMPLE receipt R-SYNTHETIC\'">Sign and submit</button>'
        await self.page.route('https://submission.invalid/**', lambda route: route.fulfill(body=html, content_type="text/html"))
        await self.page.goto('https://submission.invalid/main')
        async def next_action(messages, **kwargs):
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
                return json.dumps({'action': 'verify_review', 'quote': quote, 'observed_answer': answer, 'observed_omitted': [], 'field_quotes': field_quotes})
            if not payload['tan_captured']:
                # Synthetic selected mail text stands in for runtime TAN mail.
                await self.page.locator('body').evaluate("el => {const p=document.createElement('p'); p.textContent='TAN SHIFTED-EXAMPLE code T-SYNTHETIC'; el.appendChild(p)}")
                return json.dumps({'action': 'wait', 'milliseconds': 250})
            if not payload['tan_entered']:
                target = next(t for t in targets if t['name'] == 'challenge_code')
                return json.dumps({'action': 'fill_tan', 'target': target['id']})
            target = next(t for t in targets if t['tag'] == 'button')
            return json.dumps({'action': 'click', 'target': target['id'], 'purpose': 'commit'})
        async def model_action(messages, **kwargs):
            payload = json.loads(messages[1]['content'])
            quote = 'TAN SHIFTED-EXAMPLE code T-SYNTHETIC'
            if payload['review_verified'] and not payload['tan_captured'] and quote in payload['observation']['visible_text']:
                return json.dumps({'action': 'capture_tan', 'quote': quote, 'value': 'T-SYNTHETIC'})
            return await next_action(messages, **kwargs)
        task = {'brief': 'Synthetic flow only', 'expires_at': (time.time() + 120) * 1000,
                'access': [{'siteId': 'different-site', 'url': 'https://submission.invalid'}],
                'submission': {'kind': 'site', 'url': 'https://submission.invalid/main'}}
        with patch('rfq_agent.model.complete_with_retry', side_effect=model_action):
            result = await submit_on_site(task, answer, [], self.page, EvidenceLedger(), max_steps=20)
        self.assertEqual(result['status'], 'submitted', result)
        self.assertEqual(result['receipt']['receipt_id'], 'R-SYNTHETIC')

    async def test_implicit_submit_button_does_not_bypass_exploration_guard(self):
        await self.page.set_content('<form><button>Unfamiliar action</button></form>')
        observation = await planner.observe(self.page, [], None)
        self.assertEqual(observation['targets'][0]['type'], 'submit')
        with self.assertRaisesRegex(ValueError, 'submission is disabled'):
            await planner._apply({'action': 'click', 'target': observation['targets'][0]['id']}, self.page, [], None)
