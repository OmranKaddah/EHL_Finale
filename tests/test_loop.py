import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from rfq_agent.loop import BrowserLoop, MissionProgress


class LoopDeadline(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_evidence_can_be_corrected_without_reloading_source(self):
        progress = MissionProgress()
        progress.observe({'url': 'https://source.invalid', 'visible_text': 'Current quantity: 17.', 'targets': []})
        progress.record({'action': 'record_evidence', 'quote': 'Current quantity: 18.', 'claim': 'quantity'})
        progress.record({'action': 'record_evidence', 'quote': 'Current quantity: 17.', 'claim': 'quantity'})
        with self.assertRaisesRegex(ValueError, 'Repeated action'):
            progress.record({'action': 'record_evidence', 'quote': 'Current quantity: 17.', 'claim': 'renamed claim'})

    async def test_navigation_context_error_reobserves_once(self):
        from playwright.async_api import Error
        session = MagicMock()
        session.page.url = 'https://example.test/'
        session.page.is_closed.return_value = False
        session.observe = AsyncMock(side_effect=[Error('Execution context was destroyed'), {'targets': []}])
        loop = BrowserLoop(session, [], lambda: 10, 'test')
        turns = [item async for item in loop.turns(1)]
        self.assertEqual(len(turns), 1)
        self.assertEqual(session.observe.await_count, 2)

    async def test_persistent_browser_error_is_not_retried_forever(self):
        from playwright.async_api import Error
        session = MagicMock()
        session.page.url = 'https://example.test/'
        session.page.is_closed.return_value = False
        session.observe = AsyncMock(side_effect=Error('Frame unavailable'))
        with self.assertRaises(Error):
            async for _ in BrowserLoop(session, [], lambda: 10, 'test').turns(1):
                pass
        self.assertEqual(session.observe.await_count, 2)

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
