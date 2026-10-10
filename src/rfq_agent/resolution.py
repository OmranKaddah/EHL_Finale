"""Deterministic authority, time, revision, withdrawal and matching resolution."""

import re
from datetime import date as calendar_date
from .records import Unresolved, MAIL_AUTHORITY, date, decimal, integer

ATTRIBUTES = ('bore', 'stroke', 'pressure', 'mounting', 'certification')


def exact(value):
    if not isinstance(value, str):
        raise Unresolved('expected an exact string identifier')
    # Ignore typographic invisible separators, not meaningful punctuation/content.
    return re.sub('[\u200b\u200c\u200d\ufeff]', '', value).strip()


def attributes(value):
    if not isinstance(value, dict) or set(value) != set(ATTRIBUTES):
        raise Unresolved('all five material attributes are required')
    return {key: decimal(value[key]) if key in {'bore', 'stroke', 'pressure'} else exact(value[key])
            for key in ATTRIBUTES}


class Resolver:
    def __init__(self, bundle):
        self.scenario = bundle['scenario']
        for key in ('reference', 'scenario_date', 'director_email', 'bidder_domain'):
            if not self.scenario.get(key): raise Unresolved(f'scenario.{key} unresolved')
        self.reference = exact(self.scenario['reference'])
        self.when = date(self.scenario['scenario_date'])
        self.day = calendar_date.fromisoformat(self.scenario['scenario_date'][:10])
        self.coverage = {item['key'] for item in bundle['coverage']}
        self.records = bundle['records']
        self.used = set()

    def covered(self, key):
        if key not in self.coverage: raise Unresolved(f'complete source coverage required: {key}')

    def eligible(self, record):
        if record['reference'] is None:
            if record['kind'] not in {'spec', 'material', 'condition'}: return False
        elif exact(record['reference']) != self.reference: return False
        stamp = date(record['date']) if record.get('date') is not None else None
        if stamp is None:
            if record['kind'] not in {'tender', 'spec', 'material', 'condition'}: return False
        elif len(self.scenario['scenario_date']) == 10:
            if calendar_date.fromisoformat(record['date'][:10]) > self.day: return False
        elif stamp > self.when:
            return False
        kind = record['kind']
        if kind == 'approval':
            return exact(record.get('sender') or '').casefold() == self.scenario['director_email'].casefold()
        if kind in MAIL_AUTHORITY:
            local, subject = MAIL_AUTHORITY[kind]
            sender = f"{local}@{self.scenario['bidder_domain']}"
            if exact(record.get('sender') or '').casefold() != sender.casefold(): return False
            # Require a whole authorized subject family, plus exact reference in
            # normalized reference metadata; no loose sender substring matching.
            return bool(re.search(r'(?<!\w)' + re.escape(subject) + r'(?!\w)', record.get('subject') or '', re.I))
        return True

    def records_for(self, kind, key=None):
        return [item for item in self.records if item['kind'] == kind and self.eligible(item)
                and (key is None or exact(item['key']) == exact(key))]

    def latest(self, kind, key=None, required=True, candidates=None):
        if kind in MAIL_AUTHORITY: self.covered(f'{kind}:{key}')
        records = self.records_for(kind, key) if candidates is None else candidates
        if not records:
            if required: raise Unresolved(f'missing applicable {kind}:{key}')
            return None
        if len(records) == 1:
            self.used.add(records[0]['id'])
            return records[0]
        if any(item.get('date') is None for item in records):
            raise Unresolved(f'ambiguous unversioned {kind}:{key}')
        newest_day = max(item['date'][:10] for item in records)
        on_day = [item for item in records if item['date'][:10] == newest_day]
        if len(on_day) > 1 and any(len(item['date']) == 10 for item in on_day) and any(len(item['date']) > 10 for item in on_day):
            raise Unresolved(f'ambiguous mixed date precision for {kind}:{key}')
        stamp = max(date(item['date']) for item in records)
        latest = [item for item in records if date(item['date']) == stamp]
        if len(latest) != 1:
            raise Unresolved(f'ambiguous equally dated {kind}:{key}')
        self.used.add(latest[0]['id'])
        return latest[0]

    def resolve(self):
        for key in ('scenario', 'tender', 'spec', 'qa', 'approval', 'bonus'): self.covered(key)
        tender = self.latest('tender')['data']
        specs = self.records_for('spec')
        current = [record for record in specs if record['data'].get('current') is True]
        if len(current) != 1: raise Unresolved('exactly one governing current full specification is required')
        spec_record = current[0]; self.used.add(spec_record['id']); spec = spec_record['data']
        requirements = {item['id']: item for item in spec['requirements']}
        if len(requirements) != len(spec['requirements']): raise Unresolved('duplicate requirement IDs')
        qa = self.records_for('qa')
        numbers = [item['data']['number'] for item in qa]
        if len(set(numbers)) != len(numbers): raise Unresolved('duplicate Q&A answer numbers')
        withdrawn = {number for item in qa for number in item['data'].get('withdraws', [])}
        changes = [item for item in qa if item['data']['number'] not in withdrawn]
        self.used.update(item['id'] for item in qa)
        positions = []
        ids = set()
        for position in tender['positions']:
            pid = exact(position['id'])
            if pid in ids: raise Unresolved('duplicate position identifier')
            ids.add(pid)
            requirement = requirements.get(position['requirement'])
            if requirement is None: raise Unresolved(f'missing requirement for {pid}')
            needed = attributes(requirement['attributes'])
            quantity_records = [item for item in changes if pid in item['data'].get('quantity_changes', {})]
            quantity_record = self.latest('qa', candidates=quantity_records, required=False)
            quantity = decimal(quantity_record['data']['quantity_changes'][pid] if quantity_record else position['quantity'])
            for item in changes:
                for amendment in item['data'].get('amendments', []):
                    if amendment['revision'] == spec['revision'] and amendment['requirement'] == requirement['id'] and not set(amendment['changes']) <= set(ATTRIBUTES):
                        raise Unresolved('unsupported governing technical amendment attributes')
            for attribute in ATTRIBUTES:
                applicable = [(item, amendment) for item in changes for amendment in item['data'].get('amendments', [])
                              if amendment['revision'] == spec['revision'] and amendment['requirement'] == requirement['id']
                              and attribute in amendment['changes']]
                if applicable:
                    chosen = self.latest('qa', candidates=list({item['id']: item for item, _ in applicable}.values()))
                    updates = [amendment['changes'][attribute] for item, amendment in applicable if item['id'] == chosen['id']]
                    if len(updates) != 1: raise Unresolved('conflicting amendments in one answer')
                    needed[attribute] = decimal(updates[0]) if attribute in {'bore', 'stroke', 'pressure'} else exact(updates[0])
            stroke_kind = requirement['stroke_kind']
            if stroke_kind == 'usable':
                key = f"{spec['revision']}:{requirement['id']}"
                release = self.latest('tech', key)['data']
                if release['revision'] != spec['revision'] or release['requirement'] != requirement['id']:
                    raise Unresolved('technical release scope mismatch')
                needed['stroke'] += 2 * decimal(release['reserve_per_end'])
            elif stroke_kind != 'nominal': raise Unresolved('unknown stroke interpretation')
            if position['unit'] == 'set': quantity *= integer(requirement['pieces_per_set'], positive=True)
            elif position['unit'] != 'piece': raise Unresolved('unsupported tender unit')
            quantity = integer(quantity, positive=True)
            group = requirement['catalog_group']; self.covered(f'materials:{group}')
            materials = [item for item in self.records_for('material') if item['data'].get('group') == group]
            if any(not isinstance(item['data'].get('active'), bool) for item in materials):
                raise Unresolved('material active status is unknown')
            matches = [item for item in materials if item['data'].get('active') is True
                       and attributes(item['data']['attributes']) == needed]
            # Multiple sources/versions for one material require explicit resolution.
            if len(matches) > 1: raise Unresolved(f'ambiguous active material match for {pid}')
            assignments = {key: None for key in ('clause_key', 'tariff_key', 'commitment_key', 'pool_key', 'bonus_key')}
            for key in assignments:
                applicable = [item for item in changes if key in item['data'].get('assignments', {}).get(pid, {})]
                selected = self.latest('qa', candidates=applicable, required=False)
                if selected: assignments[key] = selected['data']['assignments'][pid][key]
            positions.append({'id': pid, 'quantity': quantity, 'material': matches[0]['data'] if matches else None,
                              'assignments': assignments, 'required_attributes': needed})
            if matches: self.used.add(matches[0]['id'])
        if not positions: raise Unresolved('tender has no positions')
        approval = self.latest('approval', required=False)
        no_bid = any(item['material'] is None for item in positions)
        return {'reference': self.reference, 'positions': positions, 'approval': approval['data'] if approval else None,
                'no_bid': no_bid, 'resolver': self}

    def price_condition(self, material):
        candidates = [item for item in self.records_for('condition') if item['data']['material'] == material]
        valid = []
        for item in candidates:
            data = item['data']
            if date(data['valid_from']).date() <= self.day <= date(data['valid_to']).date(): valid.append(item)
        return self.latest('condition', material, candidates=valid)['data']
