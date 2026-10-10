import contextlib
import io
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from rfq_agent import __main__ as cli, missions, model
from rfq_agent.loop import MissionProgress


def approval():
    values = {'tender_reference': 'CASE-42', 'percentage': '7.5%',
              'sender': 'chief@example.test', 'date': '2031-04-02',
              'conditions': 'No additional conditions', 'authority': 'Sales Director'}
    body = 'Original approval for CASE-42: 7.5%. No additional conditions.'
    result = {'action': 'return_discount', 'purpose': 'Return approval',
              'source_kind': 'original', 'body_quote': body,
              'latest_checks': 'Checked newer correspondence for supersession.'}
    result.update({key: {'value': value, 'quote': body if key in (
        'tender_reference', 'percentage', 'conditions') else value} for key, value in values.items()})
    obs = {'url': 'https://shift.test/', 'visible_text': body + '\n' + '\n'.join(values.values()), 'targets': []}
    return result, obs


class MissionValidation(unittest.TestCase):
    def test_opening_a_site_cannot_reset_its_access_form_repeatedly(self):
        progress = MissionProgress()
        progress.observe({'url': 'about:blank'})
        progress.record({'action': 'open_site', 'site_id': 'inventory'})
        progress.observe({'url': 'https://shift.test/notice', 'visible_text': 'Enter access number'})
        self.assertIn(('open_site', 'inventory'), progress.attempted)
        with self.assertRaises(ValueError):
            progress.record({'action': 'open_site', 'site_id': 'inventory'})

    def test_approval_has_quoted_contract(self):
        result, obs = approval()
        self.assertEqual(missions.validate_discount(result, obs)['percentage']['value'], '7.5%')

    def test_tan_and_fabricated_approval_do_not_meet_contract(self):
        result, obs = approval()
        for invalid in ({'tan': '123456'}, dict(result, source_kind='preview'),
                        dict(result, percentage={'value': '9%', 'quote': '7.5%'})):
            with self.assertRaises(ValueError):
                missions.validate_discount(invalid, obs)

    def test_numeric_percentage_is_bounded(self):
        result, obs = approval()
        for value in ('101%', '-1%', 'NaN%', 'Infinity%'):
            altered = json.loads(json.dumps(result).replace('7.5%', value))
            with self.assertRaises(ValueError):
                missions.validate_discount(altered, dict(obs, visible_text=obs['visible_text'].replace('7.5%', value)))

    def test_progress_reset_requires_changed_observation(self):
        progress = MissionProgress()
        progress.observe({'visible_text': 'Inbox'})
        progress.record({'action': 'inspect_screen'})
        progress.observe({'visible_text': 'Inbox'})
        with self.assertRaises(ValueError):
            progress.record({'action': 'inspect_screen'})
        progress.observe({'visible_text': 'New message'})
        progress.record({'action': 'inspect_screen'})

    def test_revisited_navigation_cycle_is_bounded_but_login_can_recover(self):
        progress = MissionProgress()
        inbox = {'url': 'https://shift.test/', 'visible_text': 'Inbox',
                 'targets': [{'id': 'link', 'tag': 'a', 'href': '/other', 'text': 'Open'}]}
        for _ in range(2):
            progress.observe(inbox)
            progress.record({'action': 'click', 'target': 'link'})
            progress.observe({'url': 'https://shift.test/other', 'visible_text': 'Other'})
        progress.observe(dict(inbox, visible_text='Inbox with an unrelated new banner'))
        with self.assertRaises(ValueError):
            progress.record({'action': 'click', 'target': 'link'})
        progress.observe({'url': 'https://shift.test/login', 'targets': [{'id': 'password', 'type': 'password'}]})
        progress.observe(inbox)
        progress.record({'action': 'click', 'target': 'link'})

    def test_cli_options_are_explicit_and_separate(self):
        opts = cli.arguments(['--site', 'shift', '--mission', 'tan', '--after', '19'])
        self.assertEqual(opts.after, 19)
        with contextlib.redirect_stderr(io.StringIO()):
            for args in (['--mission', 'discount'], ['--site', 'shift', '--after', '3'],
                         ['--site', 'shift', '--mission', 'discount', '--goal', 'Other goal']):
                with self.assertRaises(SystemExit):
                    cli.arguments(args)


class MissionRouting(unittest.IsolatedAsyncioTestCase):
    async def test_tan_and_discount_bypass_dispatch_and_submission(self):
        manager = MagicMock()
        manager.__aenter__ = AsyncMock()
        manager.__aexit__ = AsyncMock()
        site = {'site_id': 'renamed', 'url': 'https://shift.test/', '_credentials': {}}
        with patch.object(cli, 'async_playwright', return_value=manager), patch.object(
            cli.browser, 'connect', return_value=(AsyncMock(), MagicMock(), True)), patch.object(
            cli.planner, 'plan_assignments', new_callable=AsyncMock) as dispatch, patch.object(
            cli.mail, 'debug_tan', return_value={'status': 'completed', 'result': '123456'}) as tan, patch.object(
            cli.missions, 'get_discount', return_value={'status': 'completed', 'result': {}}) as discount, patch.object(
            cli, 'submit_on_site', new_callable=AsyncMock) as submit, patch.object(
            cli, 'write_artifact') as write:
            for mission in ('tan', 'discount'):
                opts = cli.arguments(['--site', 'renamed', '--mission', mission])
                self.assertEqual(await cli.investigate_mission({'brief': 'Runtime only'}, site, opts), 0)
            tan.assert_awaited_once(); discount.assert_awaited_once()
            dispatch.assert_not_awaited(); submit.assert_not_awaited()
            paths = [call.args[0] for call in write.call_args_list]
            self.assertIn('sites/renamed/tan/result.json', paths)
            self.assertIn('sites/renamed/discount/result.json', paths)

    async def test_discount_audit_rejects_semantically_wrong_quoted_source(self):
        result, obs = approval()
        session = AsyncMock(); session.frame = None; session.page.url = 'https://shift.test/'
        session.observe.return_value = obs
        decisions = [json.dumps({'decision': result}),
                     json.dumps({'accepted': False, 'reason': 'Sender authority not established'}),
                     json.dumps({'decision': {'action': 'unresolved', 'reason': 'Need authority evidence'}})]
        with patch.object(missions, 'InvestigationSession', return_value=session), patch.object(
            model, 'complete_with_retry', side_effect=decisions):
            actual = await missions.get_discount(object(), {'siteId': 'shift', 'url': 'https://shift.test/'},
                                                  {'brief': 'Approval for CASE-42'}, max_steps=3)
        self.assertEqual(actual['status'], 'unresolved')
        session.apply.assert_not_awaited()
