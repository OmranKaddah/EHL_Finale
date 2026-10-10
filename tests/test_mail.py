import unittest
import json
from unittest.mock import AsyncMock, patch
from rfq_agent.mail import validate_result
from rfq_agent import mail, model


class MailValidation(unittest.TestCase):
    def setUp(self):
        self.observation = {'visible_text': 'Signing request 12\nSigning request 18\nOriginal message: code 482913'}
        self.result = {'requests': [{'number': 12, 'quote': 'Signing request 12'},
                                    {'number': 18, 'quote': 'Signing request 18'}],
                       'number': 18, 'source_kind': 'original', 'body_quote': 'Original message: code 482913',
                       'tan': '482913'}

    def test_highest_number_and_new_code(self):
        self.assertEqual(validate_result(self.result, self.observation, number_only=True), 18)
        self.assertEqual(validate_result(self.result, self.observation, after=12), '482913')

    def test_old_request_and_wrong_selection_rejected(self):
        with self.assertRaises(ValueError):
            validate_result(self.result, self.observation, after=18)
        with self.assertRaises(ValueError):
            validate_result(dict(self.result, number=12), self.observation)

    def test_draft_preview_and_invented_body_rejected(self):
        for kind in ('preview', 'draft'):
            with self.assertRaises(ValueError):
                validate_result(dict(self.result, source_kind=kind), self.observation)
        with self.assertRaises(ValueError):
            validate_result(dict(self.result, tan='999999'), self.observation)

    def test_zero_width_text_is_presentation_only(self):
        observation = {'visible_text': self.observation['visible_text'].replace('482913', '4\u200b8\u200b2913')}
        self.assertEqual(validate_result(self.result, observation), '482913')

    def test_locked_inbox_cannot_claim_no_mail(self):
        with self.assertRaises(ValueError):
            validate_result({'requests': []}, {'visible_text': '', 'verification_gates': [
                {'disabled_targets': ['message']}]}, number_only=True)


class MailWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_signing_integration_rejects_lookalike_reference(self):
        session = AsyncMock(); session.frame = None; session.page.url = 'https://mail.test'
        quote = 'Original SHIFTED-EXAMPLE-OTHER code 222222'
        session.observe.return_value = {'url': 'https://mail.test', 'targets': [],
                                        'visible_text': 'Signing request 9\n' + quote}
        decision = {'action': 'return_mail', 'requests': [{'number': 9, 'quote': 'Signing request 9'}],
                    'number': 9, 'source_kind': 'original', 'body_quote': quote, 'tan': '222222'}
        with patch.object(mail, 'InvestigationSession', return_value=session), patch.object(
                model, 'complete_with_retry', return_value=json.dumps({'decision': decision})):
            result = await mail._run(object(), {'siteId': 'letters', 'url': 'https://mail.test'},
                                     4, 30, False, max_steps=1, report=True, reference='SHIFTED-EXAMPLE')
        self.assertEqual(result['status'], 'unresolved')
        self.assertNotIn('result', result)

    async def test_current_code_is_not_returned_when_message_binding_is_rejected(self):
        session = AsyncMock(); session.frame = None; session.page.url = 'https://mail.test'
        session.observe.return_value = {'url': 'https://mail.test', 'targets': [],
            'visible_text': 'Signing request 9\nOriginal code 222222'}
        result = {'action': 'return_mail', 'requests': [{'number': 9, 'quote': 'Signing request 9'}],
                  'number': 9, 'source_kind': 'original', 'body_quote': 'Original code 222222', 'tan': '222222'}
        decisions = [json.dumps({'decision': result}), json.dumps({'accepted': False,
                     'reason': 'The original body belongs to an older selected message'})]
        with patch.object(mail, 'InvestigationSession', return_value=session), patch.object(
            model, 'complete_with_retry', side_effect=decisions):
            actual = await mail.debug_tan(object(), {'siteId': 'invented-mail', 'url': 'https://mail.test'},
                                          after=4, max_steps=1)
        self.assertEqual(actual['status'], 'unresolved')
        self.assertNotIn('result', actual)
        self.assertEqual(actual['history'][0]['status'], 'rejected')

    async def test_model_waits_for_newer_request_and_returns_original_code(self):
        session = AsyncMock()
        session.frame = None
        session.page.url = 'https://mail.test'
        old = {'url': 'https://mail.test', 'visible_text': 'Signing request 4\nOriginal code 111111', 'targets': []}
        new = dict(old, visible_text='Signing request 9\nOriginal code 222222')
        session.observe.side_effect = [old, old, new]
        session.apply.return_value = ('invented-mail', 'waited')
        def result(number, code):
            return {'action': 'return_mail', 'requests': [{'number': number, 'quote': f'Signing request {number}'}],
                    'number': number, 'source_kind': 'original', 'body_quote': f'Original code {code}', 'tan': code}
        actions = [result(4, '111111'), {'action': 'wait', 'milliseconds': 3000, 'purpose': 'Wait for a new request'}, result(9, '222222')]
        with patch.object(mail, 'InvestigationSession', return_value=session), patch.object(
                model, 'complete_with_retry', side_effect=[json.dumps({'decision': a}) for a in actions] +
                [json.dumps({'accepted': True, 'reason': 'Original request matches selected message'})]):
            value = await mail.get_tan(object(), {'siteId': 'invented-mail', 'url': 'https://mail.test'}, after=4)
        self.assertEqual(value, '222222')
        session.apply.assert_awaited_once_with({'action': 'wait', 'milliseconds': 3000}, 'invented-mail')
