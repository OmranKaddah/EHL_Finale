import json
import time
import unittest
from unittest.mock import patch
from scenarios import ANSWER_SCHEMA
from rfq_agent.eligibility import omitted_bid
from rfq_agent.evidence import EvidenceLedger
from rfq_agent.records import Unresolved
from rfq_agent.__main__ import arguments


class EligibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.task = {'brief': 'Tender SHIFTED-EXAMPLE, currency EUR. Positions X1 and X2. '
                     'Every position may be omitted.', 'answer_schema': ANSWER_SCHEMA,
                     'expires_at': (time.time() + 600) * 1000}
        self.result = {'allowed': True, 'permission_quote': 'Every position may be omitted.',
                       'reference_quote': 'Tender SHIFTED-EXAMPLE',
                       'positions': [{'id': 'X1', 'quote': 'Positions X1 and X2.'},
                                     {'id': 'X2', 'quote': 'Positions X1 and X2.'}],
                       'answer': {'tender_reference': 'SHIFTED-EXAMPLE', 'decision': 'bid',
                                  'currency': 'EUR', 'discount_percent': 0,
                                  'total_net': 0, 'positions': []}}

    async def test_all_omitted_bid_validates_without_pricing(self):
        with patch('rfq_agent.model.complete_with_retry', side_effect=[
                json.dumps(self.result), '{"accepted":true}']) as complete:
            answer, omitted = await omitted_bid(self.task, EvidenceLedger())
        for call in complete.call_args_list:
            self.assertIn('json', ' '.join(message['content'] for message in call.args[0]).lower())
        self.assertEqual(omitted, ['X1', 'X2'])
        self.assertEqual(answer['positions'], [])
        self.assertEqual(answer['decision'], 'bid')

    async def test_permission_and_position_evidence_are_required(self):
        for key, value in [('permission_quote', 'invented permission'),
                           ('positions', [{'id': 'invented', 'quote': 'Positions X1 and X2.'}])]:
            result = dict(self.result, **{key: value})
            with self.subTest(key=key), patch('rfq_agent.model.complete_with_retry', return_value=json.dumps(result)):
                with self.assertRaises(Unresolved):
                    await omitted_bid(self.task, EvidenceLedger())

    async def test_failed_source_audit_prevents_bid(self):
        with patch('rfq_agent.model.complete_with_retry', side_effect=[
                json.dumps(self.result), '{"accepted":false}']):
            with self.assertRaisesRegex(Unresolved, 'audit'):
                await omitted_bid(self.task, EvidenceLedger())

    async def test_audit_cannot_accept_with_unresolved_issues(self):
        with patch('rfq_agent.model.complete_with_retry', side_effect=[
                json.dumps(self.result), '{"accepted":true,"issues":["minimum offered count is unmet"]}']):
            with self.assertRaisesRegex(Unresolved, 'contradicts'):
                await omitted_bid(self.task, EvidenceLedger())

    async def test_reference_citation_uses_only_exact_runtime_occurrence(self):
        self.result['reference_quote'] = 'Invented heading: SHIFTED-EXAMPLE'
        diagnostics = []
        with patch('rfq_agent.model.complete_with_retry', side_effect=[json.dumps(self.result), '{"accepted":true}']):
            answer, _ = await omitted_bid(self.task, EvidenceLedger(), diagnostics=diagnostics)
        self.assertEqual(answer['tender_reference'], 'SHIFTED-EXAMPLE')
        self.assertEqual(diagnostics[0]['result']['reference_quote'], self.result['reference_quote'])
        self.task['brief'] = self.task['brief'].replace('SHIFTED-EXAMPLE,', 'SHIFTED-EXAMPLE-OTHER,')
        with patch('rfq_agent.model.complete_with_retry', return_value=json.dumps(self.result)):
            with self.assertRaisesRegex(Unresolved, 'reference lacks'):
                await omitted_bid(self.task, EvidenceLedger())

    def test_eligibility_is_explicit_and_cannot_mix_with_site_debug(self):
        self.assertFalse(arguments([]).eligibility)
        self.assertTrue(arguments(['--eligibility']).eligibility)
        with self.assertRaises(SystemExit): arguments(['--eligibility', '--site', 'invented'])
