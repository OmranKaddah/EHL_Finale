import unittest
from decimal import Decimal
from copy import deepcopy
from scenarios import scenario, ANSWER_SCHEMA
from rfq_agent.resolution import Resolver
from rfq_agent.pricing import calculate, allocate, marginal_bonus
from rfq_agent.answer import validate_answer
from rfq_agent.records import Unresolved, decimal, validate_bundle
from rfq_agent.evidence import Evidence


def solve(bundle):
    resolved = Resolver(bundle).resolve()
    calculation = calculate(resolved)
    answer = validate_answer(calculation, ANSWER_SCHEMA, [item['id'] for item in resolved['positions']])
    return calculation, answer


class BusinessRules(unittest.TestCase):
    def test_full_shared_pricing_and_rounding(self):
        bundle, _ = scenario(); calculation, answer = solve(bundle)
        a, b = answer['positions']
        self.assertEqual((a['unit_price'], b['unit_price'], answer['total_net']), (81.59, 90.48, 425.73))
        self.assertEqual((a['rebate_total'], b['rebate_total']), (19.24, 14.26))
        self.assertEqual((a['base_unit_price'], b['base_unit_price']), (90.0, 100.0))
        self.assertEqual((a['lead_time_weeks'], b['lead_time_weeks']), (2, 7))
        self.assertEqual(a['surcharge_per_unit'], 1.11)
        self.assertEqual((a['packaging_per_unit'], b['packaging_per_unit']), (2, 1.5))
        self.assertEqual(calculation['omitted'], [])

    def test_latest_conditional_failure_does_not_revive_old_approval(self):
        bundle, add = scenario()
        add('approval', 'approval', {'percent': '25', 'min_goods_eur': '471'}, date='2031-05-10', sender='director@invented.example')
        _, answer = solve(bundle)
        self.assertEqual(answer['discount_percent'], 0)
        add('approval', 'approval', {'percent': '99', 'min_goods_eur': None}, date='2031-05-21', sender='director@invented.example')
        add('approval', 'approval', {'percent': '98', 'min_goods_eur': None}, date='2031-05-19', sender='director@other.example')
        self.assertEqual(solve(bundle)[1]['discount_percent'], 0)

    def test_withdrawn_quantity_and_set_conversion(self):
        bundle, add = scenario()
        bundle['records'][0]['data']['positions'][0]['unit'] = 'set'
        add('qa', 'answer', {'number': '2', 'quantity_changes': {'A': '50'}}, date='2031-05-03')
        add('qa', 'answer', {'number': '3', 'withdraws': ['2'], 'quantity_changes': {'A': '4'}}, date='2031-05-04')
        add('qa', 'answer', {'number': '4', 'withdraws': ['3']}, date='2031-05-05')
        resolved = Resolver(bundle).resolve()
        self.assertEqual(resolved['positions'][0]['quantity'], 6)

    def test_scoped_amendment_then_nominal_stroke_derivation(self):
        bundle, add = scenario(); requirement = bundle['records'][1]['data']['requirements'][0]
        requirement['stroke_kind'] = 'usable'
        add('qa', 'answer', {'number': '2', 'amendments': [{'revision': 'rev-new', 'requirement': 'R', 'changes': {'stroke': '70'}}]}, date='2031-05-03')
        add('qa', 'answer', {'number': '3', 'amendments': [{'revision': 'old', 'requirement': 'R', 'changes': {'stroke': '999'}}]}, date='2031-05-04')
        add('tech', 'rev-new:R', {'revision': 'rev-new', 'requirement': 'R', 'reserve_per_end': '5'}, sender='technik@invented.example', subject='Technikfreigabe TEST-ORCHARD')
        self.assertFalse(Resolver(bundle).resolve()['no_bid'])

    def test_no_bid_requires_complete_catalogue_coverage(self):
        bundle, _ = scenario(); bundle['records'][3]['data']['active'] = False
        calculation, answer = solve(bundle)
        self.assertEqual(answer['decision'], 'no_bid'); self.assertEqual(answer['positions'], [])
        self.assertEqual(answer['total_net'], 0); self.assertEqual(answer['discount_percent'], 0)
        bundle['coverage'] = [item for item in bundle['coverage'] if not item['key'].startswith('materials:')]
        with self.assertRaises(Unresolved): solve(bundle)

    def test_ambiguous_same_date_approval_blocks(self):
        bundle, add = scenario()
        add('approval', 'approval', {'percent': '11', 'min_goods_eur': None}, sender='director@invented.example')
        with self.assertRaisesRegex(Unresolved, 'ambiguous'): solve(bundle)

    def test_currency_price_unit_conversion_rounds_before_threshold(self):
        bundle, add = scenario(); condition = bundle['records'][4]['data']
        condition.update(currency='USD', price_unit='100', fx_key='fx')
        condition['scales'] = [{'minimum': '0', 'price': '10000.55'}]
        add('fx', 'fx', {'eur_per_unit': '0.8'}, sender='finanzen@invented.example', subject='Devisenfixing TEST-ORCHARD')
        _, answer = solve(bundle)
        self.assertEqual(answer['positions'][0]['base_unit_price'], 80)
        self.assertEqual(answer['discount_percent'], 10)  # 5 * 80 == inclusive 400.

    def test_latest_delivery_ceiling_failure_uses_shared_production(self):
        bundle, add = scenario()
        add('delivery', 'early', {'material': 'TEST-MATERIAL', 'max_quantity': '4', 'weeks': '1'}, date='2031-05-10', sender='logistik@invented.example', subject='Terminfreigabe TEST-ORCHARD')
        _, answer = solve(bundle)
        self.assertEqual([item['lead_time_weeks'] for item in answer['positions']], [7, 7])

    def test_allocation_conserves_cents_and_tie_order(self):
        self.assertEqual(allocate('0.02', {'C': '1', 'A': '1', 'B': '1'}), {'C': Decimal('0'), 'A': Decimal('.01'), 'B': Decimal('.01')})
        self.assertEqual(marginal_bonus('300', [{'up_to': '200', 'percent': '10'}, {'up_to': None, 'percent': '5'}]), Decimal('25'))

    def test_partial_bid_keeps_independent_position_and_checks_omission(self):
        bundle, _ = scenario()
        # Missing a position-specific clause does not make its known shared goods
        # disappear from the bonus/conditional-threshold base.
        bundle['records'][2]['data']['assignments']['A']['clause_key'] = 'missing'
        bundle['coverage'].append({'key': 'clause:missing', 'evidence_ids': ['source']})
        calculation, answer = solve(bundle)
        self.assertEqual(calculation['omitted'], ['A']); self.assertEqual(answer['positions'][0]['position'], 'B')
        self.assertEqual(answer['total_net'], 180.96)
        calculation['omitted'] = []
        with self.assertRaisesRegex(Unresolved, 'explicitly omitted'): validate_answer(calculation, ANSWER_SCHEMA, ['A', 'B'])

    def test_independent_arithmetic_check(self):
        bundle, _ = scenario(); calculation, _ = solve(bundle)
        calculation['answer']['total_net'] += Decimal('.01')
        with self.assertRaisesRegex(Unresolved, 'line-total'): validate_answer(calculation, ANSWER_SCHEMA, ['A', 'B'])

    def test_float_inputs_and_unknown_citations_are_rejected(self):
        with self.assertRaises(Unresolved): decimal(0.1)
        bundle, _ = scenario()
        with self.assertRaisesRegex(Unresolved, 'citations'): validate_bundle(bundle, [])

    def test_held_out_renaming_and_record_order_preserve_formula(self):
        bundle, _ = scenario()
        # A separate renamed scenario family, without changing solver logic.
        serialized = __import__('json').dumps(bundle).replace('TEST-ORCHARD', 'ANOTHER-SCENARIO').replace('TEST-MATERIAL', 'DifferentPart').replace('invented.example', 'held-out.invalid').replace('TEST-GROUP', 'AnotherGroup')
        shifted = __import__('json').loads(serialized); shifted['records'].reverse()
        answer = solve(shifted)[1]
        self.assertEqual(answer['tender_reference'], 'ANOTHER-SCENARIO')
        self.assertEqual(answer['total_net'], 425.73)
        self.assertEqual(answer['positions'][0]['material_number'], 'DifferentPart')

    def test_bonus_membership_is_finance_evidence_not_qa_location(self):
        bundle, _ = scenario()
        for assignment in bundle['records'][2]['data']['assignments'].values(): assignment['bonus_key'] = None
        self.assertEqual(solve(bundle)[1]['total_net'], 425.73)

    def test_unknown_active_status_never_becomes_no_bid(self):
        bundle, _ = scenario(); del bundle['records'][3]['data']['active']
        with self.assertRaisesRegex(Unresolved, 'active status'): solve(bundle)

    def test_wrong_authority_and_future_index_are_ignored(self):
        bundle, add = scenario()
        add('index', 'steel', {'windows': [{'from': '2031-01-01', 'to': '2031-12-31', 'eur_per_kg': '100'}]}, date='2031-05-19', sender='finanzen@invented.example', subject='Preisindizes TEST-ORCHARD')
        add('index', 'steel', {'windows': [{'from': '2031-01-01', 'to': '2031-12-31', 'eur_per_kg': '100'}]}, date='2031-05-21', sender='kalkulation@invented.example', subject='Preisindizes TEST-ORCHARD')
        self.assertEqual(solve(bundle)[1]['total_net'], 425.73)

    def test_future_source_calendar_date_is_not_backdated_by_timezone(self):
        bundle, add = scenario()
        add('approval', 'approval', {'percent': '99', 'min_goods_eur': None}, date='2031-05-21T00:30:00+03:00', sender='director@invented.example')
        self.assertEqual(solve(bundle)[1]['discount_percent'], 10)

    def test_mixed_date_precision_requires_disambiguation(self):
        bundle, add = scenario()
        add('approval', 'approval', {'percent': '11', 'min_goods_eur': None}, date='2031-05-01T12:00:00+02:00', sender='director@invented.example')
        with self.assertRaisesRegex(Unresolved, 'mixed date precision'): solve(bundle)
