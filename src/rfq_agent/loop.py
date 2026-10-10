"""Shared observe/model/execute loop; missions validate their own decisions."""

import asyncio
import json
import os
import hashlib
import re
from jsonschema import validate, ValidationError

from . import model


class MissionProgress:
    """Prevent unchanged action loops without choosing an alternative route."""

    def __init__(self):
        self.state = None
        self.attempted = set()
        self.navigation_visits = {}
        self.targets = {}
        self.opened_sites = set()
        self.screen_visits = {}

    def observe(self, observation):
        self.context = (observation.get('url'), observation.get('selected_frame'), observation.get('selected_tab'))
        self.screen_context = self.context
        self.targets = {target['id']: target for target in observation.get('targets', [])}
        # Reauthentication is legitimate recovery, even if its view repeats.
        if any(t.get('type') == 'password' for t in self.targets.values()):
            self.navigation_visits.clear()
        state = hashlib.sha256(json.dumps({key: observation.get(key) for key in (
            'url', 'visible_text', 'targets', 'selected_frame', 'selected_tab',
            'scroll_state', 'document_offset', 'text_offset')},
            sort_keys=True, default=str).encode()).hexdigest()
        if self.state != state:
            self.state = state
            self.attempted.clear()
        for target_id, target in self.targets.items():
            if self.navigation_visits.get(self.navigation_key(target), 0) >= 2:
                self.attempted.add(('click', target_id))
        for site_id in self.opened_sites:
            self.attempted.add(('open_site', site_id))
        if self.screen_visits.get(self.screen_context, 0) >= 2:
            self.attempted.add(('inspect_screen', ''))

    def navigation_key(self, target):
        return (self.context, target.get('tag'), target.get('href', ''), target.get('text', ''),
                target.get('label', ''), target.get('gate_context', ''))

    def record(self, action):
        kind = action['action']
        key = (kind, action.get('target', action.get('site_id', action.get('direction', ''))))
        if kind == 'record_evidence':
            # A rejected quote must not prohibit a corrected quote from the same
            # unchanged source. Identical quotes still cannot loop indefinitely.
            key = (kind, hashlib.sha256(str(action.get('quote', '')).encode()).hexdigest())
        if key in self.attempted:
            raise ValueError('Repeated action on unchanged content; choose a different action')
        self.attempted.add(key)
        if kind == 'open_site':
            self.opened_sites.add(action.get('site_id'))
        if kind == 'inspect_screen':
            self.screen_visits[self.screen_context] = self.screen_visits.get(self.screen_context, 0) + 1
        target = self.targets.get(action.get('target'), {})
        if kind == 'click' and target.get('tag') == 'a' and not target.get('in_active_modal'):
            key = self.navigation_key(target)
            self.navigation_visits[key] = self.navigation_visits.get(key, 0) + 1


class BrowserLoop:
    def __init__(self, session, sites, budget, phase, timeout=180, site_id=None):
        self.session, self.sites, self.budget = session, sites, budget
        self.phase, self.timeout, self.site_id = phase, timeout, site_id
        self.inspect_screen = False

    async def turns(self, max_steps):
        from .planner import _site_for_url
        for step in range(1, max_steps + 1):
            if self.budget() <= 0:
                break
            current = _site_for_url(self.session.page.url, self.sites)
            if current:
                self.site_id = current['site_id']
            from playwright.async_api import Error as BrowserError
            try:
                observation = await asyncio.wait_for(self.session.observe(self.site_id), self.budget())
            except BrowserError:
                if self.session.page.is_closed() or self.budget() <= 1:
                    raise
                # Navigation can replace the execution context between DOM reads.
                # Retry observation once; never reuse targets from the failed read.
                await asyncio.sleep(0.25)
                observation = await asyncio.wait_for(self.session.observe(self.site_id), self.budget())
            yield step, self.site_id, observation

    async def decide(self, system, content, observation, schema=None):
        from .planner import _has_visual_challenge, _visual_challenge_screenshot
        # Presentation-only zero-width characters obscure subjects and codes.
        # Source observations remain intact for quote/provenance validation.
        content = re.sub('[\u200b\u200c\u200d\ufeff]', '', content)
        # Hosted Qwen does not use the OpenAI structured-output option.
        if schema and os.environ.get('RFQ_MODEL_PROVIDER', 'openai').lower() == 'qwen':
            content += '\nRequired decision schema: ' + json.dumps(schema)
        if self.inspect_screen or _has_visual_challenge(observation):
            shot = await asyncio.wait_for(_visual_challenge_screenshot(self.session.page), self.budget())
            if shot:
                content = [{'type': 'text', 'text': content},
                           {'type': 'image_url', 'image_url': {'url': shot, 'detail': 'high'}}]
        self.inspect_screen = False
        options = {'response_schema': schema} if schema else {}
        messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}]
        for attempt in range(2):
            raw = await model.complete_with_retry(
                messages, timeout=max(0.1, min(self.timeout, self.budget())), budget=self.budget,
                phase=self.phase, **options)
            if not schema:
                return raw
            try:
                decoded = json.loads(raw)
                if 'decision' in schema.get('properties', {}) and isinstance(decoded, dict) and 'decision' not in decoded:
                    decoded = {'decision': decoded}
                validate(decoded, schema)
                return json.dumps(decoded, ensure_ascii=False)
            except (ValueError, ValidationError):
                if attempt:
                    raise ValueError('model response did not match the current allowed decisions') from None
                messages.append({'role': 'user', 'content':
                    'Your previous response was invalid for the current allowed decision schema. '
                    'Choose an available action and target, with all required fields. Do not repeat unavailable actions.'})

    async def apply(self, action, site_id=None):
        return await asyncio.wait_for(self.session.apply(action, site_id or self.site_id), self.budget())
