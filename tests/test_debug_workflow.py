import asyncio
import contextlib
import io
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from rfq_agent import __main__ as workflow, planner, model
from rfq_agent.evidence import Evidence, EvidenceLedger


class DebugWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_default_batch_is_sequential_and_parallel_is_explicit(self):
        active = 0; peak = 0
        async def investigate(*args, **kwargs):
            nonlocal active, peak
            active += 1; peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1
            return {'status': 'completed'}
        sessions = [MagicMock(), MagicMock()]
        assignments = [{'site_id': 'a'}, {'site_id': 'b'}]
        with patch.object(planner, 'run_planner', side_effect=investigate):
            await workflow.run_batch({}, sessions, assignments, EvidenceLedger())
            self.assertEqual(peak, 1)
            peak = 0
            await workflow.run_batch({}, sessions, assignments, EvidenceLedger(), parallel=True)
            self.assertEqual(peak, 2)

    async def test_site_debug_is_restricted_and_never_submits(self):
        site = {'site_id': 'shifted-site', 'url': 'https://example.test', '_credentials': {}, 'credential_keys': []}
        async def investigate(task, page, assignment, ledger, **kwargs):
            self.assertEqual(planner.normalize_sites(task['access'])[0]['site_id'], site['site_id'])
            self.assertEqual(len(task['access']), 1)
            self.assertEqual(kwargs['max_steps'], 7)
            await ledger.add(Evidence('invented fact', 'invented quote', site['site_id'], site['url'], 'Test', 1, site['site_id']))
            return {'status': 'completed'}
        manager = MagicMock(); manager.__aenter__ = AsyncMock(); manager.__aexit__ = AsyncMock()
        artifacts = {}
        with patch.object(workflow, 'async_playwright', return_value=manager), patch.object(workflow.browser, 'connect', return_value=(AsyncMock(), MagicMock(), True)), patch.object(planner, 'plan_assignments', return_value=[{'site_id': site['site_id'], 'objective': 'Read evidence'}]), patch.object(planner, 'run_planner', side_effect=investigate), patch.object(workflow, 'submit_on_site', new_callable=AsyncMock) as submit, patch.object(workflow.run_contract, 'submit_answer') as api_submit, patch.object(workflow, 'write_artifact', side_effect=lambda name, value: artifacts.update({name: value})):
            self.assertEqual(await workflow.investigate_site({'brief': 'Invented brief'}, site, 7), 0)
        submit.assert_not_awaited(); api_submit.assert_not_called()
        self.assertEqual(artifacts['sites/shifted-site/workflow.json']['submission']['status'], 'not_attempted')
        self.assertEqual(len(artifacts['sites/shifted-site/evidence.json']), 1)

    async def test_list_sites_does_not_call_model(self):
        task = {'access': [{'siteId': 'shifted', 'url': 'https://example.test'}]}
        output = io.StringIO()
        with patch.object(workflow.run_contract, 'load_run', return_value=(task, None)), patch.object(planner, 'plan_assignments', new_callable=AsyncMock) as dispatch, contextlib.redirect_stdout(output):
            self.assertEqual(await workflow.main(workflow.arguments(['--list-sites'])), 0)
        dispatch.assert_not_awaited()
        self.assertEqual(output.getvalue(), 'shifted\n')

    async def test_successful_model_call_has_no_console_noise(self):
        output = io.StringIO()
        with patch.object(model, 'complete', return_value='{"ok":true}'), contextlib.redirect_stdout(output):
            await model.complete_with_retry([], 10, lambda: 20)
        self.assertEqual(output.getvalue(), '')
