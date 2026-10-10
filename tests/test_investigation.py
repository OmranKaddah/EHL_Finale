import unittest
from unittest.mock import patch
from copy import deepcopy
import json
import time
from scenarios import scenario, ANSWER_SCHEMA
from rfq_agent.investigation import InvestigationState
from rfq_agent.evidence import Evidence, EvidenceLedger
from rfq_agent.records import Unresolved


class InvestigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_coordinator_json_is_retried(self):
        from rfq_agent.investigation import InvestigationState
        with patch('rfq_agent.investigation.model.complete_with_retry', side_effect=['{"assignments":', '{"assignments":[]}']) as call:
            result = await InvestigationState().call({}, 'Return assignments JSON', {})
        self.assertEqual(result, {'assignments': []})
        self.assertEqual(call.await_count, 2)
    async def asyncSetUp(self):
        self.bundle, _ = scenario()
        self.evidence = Evidence('invented source record set', json.dumps(self.bundle), 'shifted-source', 'https://shifted.invalid/doc', 'Synthetic source', 1)
        for record in self.bundle['records']: record['evidence_ids'] = [self.evidence.evidence_id]
        for covered in self.bundle['coverage']: covered['evidence_ids'] = [self.evidence.evidence_id]
        self.ledger = EvidenceLedger(); await self.ledger.add(self.evidence)
        self.task = {'brief': 'Invented test brief only', 'answer_schema': ANSWER_SCHEMA,
                     'expires_at': (time.time() + 900) * 1000}

    async def test_normalization_audit_resolution_and_answer_pipeline(self):
        state = InvestigationState()
        with patch('rfq_agent.investigation.model.complete_with_retry', side_effect=[json.dumps(self.bundle), '{"accepted":true,"issues":[]}']):
            await state.review(self.task, self.ledger)
        self.assertEqual(state.answer['total_net'], 425.73)
        self.assertEqual(state.calculation['omitted'], [])
        self.assertEqual(state.snapshot()['scenario']['reference'], 'TEST-ORCHARD')

    async def test_source_audit_rejection_revokes_previous_answer(self):
        state = InvestigationState(); state.answer = {'old': 'answer'}
        replies = [json.dumps(self.bundle), '{"accepted":false,"issues":["unsupported base price"]}'] * 2
        with patch('rfq_agent.investigation.model.complete_with_retry', side_effect=replies):
            await state.review(self.task, self.ledger)
        self.assertIsNone(state.answer)
        self.assertTrue(any('unsupported base price' in gap for gap in state.gaps))

    async def test_reassignment_can_move_same_gap_to_another_site(self):
        state = InvestigationState(); state.gaps = ['Find current specification']
        sites = [{'site_id': 'source-z', 'url': 'https://z.invalid'}, {'site_id': 'source-y', 'url': 'https://y.invalid'}]
        reply = {'assignments': [{'site_id': 'source-y', 'objective': 'Find specification discovered in the mail archive'}]}
        with patch('rfq_agent.investigation.model.complete_with_retry', return_value=json.dumps(reply)):
            result = await state.assignments(self.task, sites, 2)
        self.assertEqual(result[0]['site_id'], 'source-y')
        reply['assignments'][0]['site_id'] = 'invented-host'
        with patch('rfq_agent.investigation.model.complete_with_retry', return_value=json.dumps(reply)):
            with self.assertRaises(Unresolved): await state.assignments(self.task, sites, 2)

    async def test_source_date_absence_is_not_invented(self):
        for record in self.bundle['records']:
            if record['kind'] in {'tender', 'spec', 'material', 'condition'}: record['date'] = None
        state = InvestigationState()
        with patch('rfq_agent.investigation.model.complete_with_retry', side_effect=[json.dumps(self.bundle), '{"accepted":true,"issues":[]}']):
            await state.review(self.task, self.ledger)
        self.assertEqual(state.answer['total_net'], 425.73)
