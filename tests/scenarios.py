"""Invented scenarios only. Never imported by the runtime agent."""
from copy import deepcopy

ANSWER_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['tender_reference', 'decision', 'currency', 'discount_percent', 'positions', 'total_net'],
    'properties': {
        'tender_reference': {'type': 'string'}, 'decision': {'enum': ['bid', 'no_bid']},
        'currency': {'const': 'EUR'}, 'discount_percent': {'type': 'number', 'minimum': 0, 'maximum': 100},
        'total_net': {'type': 'number', 'minimum': 0},
        'positions': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
            'required': ['position', 'material_number', 'quantity', 'unit_price', 'lead_time_weeks'],
            'properties': {'position': {'type': 'string'}, 'material_number': {'type': 'string'},
                'quantity': {'type': 'integer', 'minimum': 1}, 'lead_time_weeks': {'type': 'integer', 'minimum': 0},
                **{key: {'type': 'number', 'minimum': 0} for key in ('unit_price', 'base_unit_price', 'surcharge_per_unit', 'packaging_per_unit', 'rebate_total')}}}}
    }
}


def scenario():
    bundle = {'scenario': {'reference': 'TEST-ORCHARD', 'scenario_date': '2031-05-20',
        'director_email': 'director@invented.example', 'bidder_domain': 'invented.example', 'evidence_ids': ['brief']},
        'records': [], 'coverage': [], 'gaps': []}
    def add(kind, key, data, **metadata):
        record = {'id': f'{kind}-{len(bundle["records"])}', 'kind': kind, 'key': key, 'date': '2031-05-01',
                  'reference': 'TEST-ORCHARD', 'sender': None, 'subject': None, 'evidence_ids': ['source'], 'data': data}
        record.update(metadata); bundle['records'].append(record)
        bundle['coverage'].append({'key': f'{kind}:{key}', 'evidence_ids': ['source']})
        return record
    attrs = {'bore': '40', 'stroke': '80', 'pressure': '120', 'mounting': 'flange', 'certification': 'TEST-CERT'}
    add('tender', 'tender', {'positions': [{'id': 'A', 'requirement': 'R', 'quantity': '3', 'unit': 'piece'}, {'id': 'B', 'requirement': 'R', 'quantity': '2', 'unit': 'piece'}]})
    add('spec', 'spec', {'revision': 'rev-new', 'current': True, 'requirements': [{'id': 'R', 'attributes': attrs, 'pieces_per_set': '2', 'stroke_kind': 'nominal', 'catalog_group': 'TEST-GROUP'}]})
    add('qa', 'answer', {'number': '1', 'withdraws': [], 'quantity_changes': {}, 'amendments': [],
        'assignments': {'A': {'clause_key': 'both', 'tariff_key': 'carton', 'commitment_key': 'early', 'pool_key': 'pool', 'bonus_key': 'bonus'},
                        'B': {'clause_key': None, 'tariff_key': 'carton', 'commitment_key': None, 'pool_key': 'pool', 'bonus_key': 'bonus'}}})
    add('material', 'TEST-MATERIAL', {'number': 'TEST-MATERIAL', 'group': 'TEST-GROUP', 'active': True, 'attributes': deepcopy(attrs),
        'stock': '4', 'stock_weeks': '1', 'production_weeks': '7', 'carton_size': '2', 'surcharge_mass': '2', 'allocation_mass': '2'})
    add('condition', 'TEST-MATERIAL', {'material': 'TEST-MATERIAL', 'valid_from': '2031-01-01', 'valid_to': '2031-12-31',
        'currency': 'EUR', 'price_unit': '1', 'scales': [{'minimum': '0', 'price': '100'}, {'minimum': '3', 'price': '90'}],
        'setup_fee_eur': '6', 'index_key': 'steel', 'fx_key': None})
    add('approval', 'approval', {'percent': '10', 'min_goods_eur': '400'}, sender='director@invented.example', subject='Approval TEST-ORCHARD')
    add('index', 'steel', {'windows': [{'from': '2031-01-01', 'to': '2031-06-30', 'eur_per_kg': '0.555'},
                                     {'from': '2031-07-01', 'to': '2031-12-31', 'eur_per_kg': '9'}]}, sender='kalkulation@invented.example', subject='Preisindizes TEST-ORCHARD')
    add('tariff', 'carton', {'eur_per_carton': '3'}, sender='logistik@invented.example', subject='Verpackungstarife TEST-ORCHARD')
    add('delivery', 'early', {'material': 'TEST-MATERIAL', 'max_quantity': '5', 'weeks': '2'}, sender='logistik@invented.example', subject='Terminfreigabe TEST-ORCHARD')
    add('pool', 'pool', {'fee_eur': '10', 'allocation_rule': 'largest_remainder', 'members': ['A', 'B']}, sender='kalkulation@invented.example', subject='Rüstpools TEST-ORCHARD')
    add('bonus', 'bonus', {'members': ['A', 'B'], 'bands': [{'up_to': '200', 'percent': '10'}, {'up_to': None, 'percent': '5'}]}, sender='finanzen@invented.example', subject='Projektbonus TEST-ORCHARD')
    add('clause', 'both', {'discount_components': 'base_and_surcharge'}, sender='kalkulation@invented.example', subject='Konditionsregeln TEST-ORCHARD')
    for key in ['scenario', 'tender', 'spec', 'qa', 'approval', 'bonus', 'materials:TEST-GROUP']:
        bundle['coverage'].append({'key': key, 'evidence_ids': ['source']})
    return bundle, add
