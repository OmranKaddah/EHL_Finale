import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from rfq_agent.loop import BrowserLoop


class LoopDeadline(unittest.IsolatedAsyncioTestCase):
    async def test_model_presentation_is_normalized_without_changing_source(self):
        loop = BrowserLoop(AsyncMock(), [], lambda: 60, 'test')
        observation = {'visible_text': 'O\u200br\u200bi\u200bg\u200bi\u200bn\u200ba\u200bl'}
        with patch('rfq_agent.loop.model.complete_with_retry', new_callable=AsyncMock,
                   return_value='{}') as complete:
            await loop.decide('system', observation['visible_text'], {}, None)
        self.assertEqual(complete.call_args.args[0][1]['content'], 'Original')
        self.assertIn('\u200b', observation['visible_text'])

    async def test_unavailable_model_action_is_repaired_before_execution(self):
        loop = BrowserLoop(AsyncMock(), [], lambda: 60, 'test')
        schema = {'type': 'object', 'properties': {'decision': {'type': 'object',
                  'properties': {'action': {'enum': ['fill']}, 'target': {'enum': ['query']},
                                 'value': {'type': 'string'}},
                  'required': ['action', 'target', 'value'], 'additionalProperties': False}},
                  'required': ['decision'], 'additionalProperties': False}
        with patch('rfq_agent.loop.model.complete_with_retry', new_callable=AsyncMock) as complete:
            complete.side_effect = ['{"decision":{"action":"inspect_screen"}}',
                                   '{"decision":{"action":"fill","target":"query","value":"delivery"}}']
            result = await loop.decide('system', 'prompt', {}, schema)
        self.assertIn('delivery', result)
        self.assertEqual(complete.await_count, 2)
        loop.session.apply.assert_not_awaited()

    async def test_invalid_action_after_repair_is_rejected(self):
        loop = BrowserLoop(AsyncMock(), [], lambda: 60, 'test')
        schema = {'type': 'object', 'properties': {'action': {'enum': ['fill']}},
                  'required': ['action'], 'additionalProperties': False}
        with patch('rfq_agent.loop.model.complete_with_retry', new_callable=AsyncMock,
                   return_value='{"action":"press"}'):
            with self.assertRaisesRegex(ValueError, 'current allowed decisions'):
                await loop.decide('system', 'prompt', {}, schema)
        loop.session.apply.assert_not_awaited()

    async def test_stalled_observation_is_cancelled_at_shared_deadline(self):
        cancelled = asyncio.Event()

        async def stalled(_):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        session = AsyncMock()
        session.page.url = 'about:blank'
        session.observe.side_effect = stalled
        loop = BrowserLoop(session, [], lambda: 0.01, 'invented')
        with self.assertRaises(TimeoutError):
            async for _ in loop.turns(1):
                self.fail('A stalled observation must never reach mission handling')
        self.assertTrue(cancelled.is_set())
