"""Decimal-only bid calculation; browser layouts cannot change these formulas."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, localcontext
from .records import Unresolved, decimal, integer, date

CENT = Decimal('0.01')
ZERO = Decimal('0')
ONE = Decimal('1')


def cents(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def allocate(total, weights):
    """Conserve every cent, largest fractional remainders then position identifier."""
    total = cents(decimal(total))
    weights = {key: decimal(value) for key, value in weights.items()}
    denominator = sum(weights.values(), ZERO)
    if not weights or denominator <= 0:
        if total == 0: return {key: ZERO for key in weights}
        raise Unresolved('positive allocation total requires positive aggregate weight')
    count = integer(total / CENT)
    quotas = {key: Decimal(count) * value / denominator for key, value in weights.items()}
    floors = {key: int(value.to_integral_value(rounding=ROUND_FLOOR)) for key, value in quotas.items()}
    remainder = count - sum(floors.values())
    order = sorted(weights, key=lambda key: (-(quotas[key] - floors[key]), key))
    for key in order[:remainder]: floors[key] += 1
    return {key: Decimal(value) * CENT for key, value in floors.items()}


def marginal_bonus(total, bands):
    total = decimal(total); lower = ZERO; result = ZERO
    if not isinstance(bands, list) or not bands: raise Unresolved('bonus bands are missing')
    unlimited = False
    for index, band in enumerate(bands):
        rate = decimal(band['percent'])
        if rate > 100: raise Unresolved('bonus percentage exceeds 100')
        upper = decimal(band['up_to']) if band['up_to'] is not None else None
        if upper is not None and upper <= lower: raise Unresolved('bonus bands must be strictly ascending')
        if upper is None:
            if index != len(bands) - 1: raise Unresolved('unlimited band must be last')
            unlimited = True
        portion = max(ZERO, (total if upper is None else min(total, upper)) - lower)
        result += portion * rate / 100
        if upper is not None: lower = upper
    if not unlimited and total > lower: raise Unresolved('bonus bands do not cover the goods total')
    return cents(result)


def discount_percent(approval, goods, no_bid=False):
    if approval is None: return ZERO
    rate = decimal(approval['percent'])
    if rate > 100: raise Unresolved('discount percentage exceeds 100')
    threshold = approval['min_goods_eur']
    if threshold is not None and (no_bid or cents(goods) < decimal(threshold)): return ZERO
    return rate


def calculate(resolved):
    with localcontext() as context:
        context.prec = 50
        return _calculate(resolved)


def _calculate(resolved):
    resolver = resolved['resolver']
    result = {'tender_reference': resolved['reference'], 'currency': 'EUR',
              'positions': [], 'decision': 'no_bid' if resolved['no_bid'] else 'bid', 'total_net': ZERO}
    if resolved['no_bid']:
        result['discount_percent'] = discount_percent(resolved['approval'], ZERO, no_bid=True)
        return {'answer': result, 'omitted': [], 'gaps': [], 'audit': {'selected_record_ids': sorted(resolver.used)}}
    positions = resolved['positions']
    ids = {item['id'] for item in positions}
    pooled = {}
    for position in positions:
        number = position['material']['number']
        pooled[number] = pooled.get(number, 0) + position['quantity']
    work = {}; errors = {}
    for position in positions:
        pid = position['id']; material = position['material']; quantity = position['quantity']
        try:
            condition = resolver.price_condition(material['number'])
            scales = condition['scales']
            thresholds = [integer(scale['minimum']) for scale in scales]
            if len(set(thresholds)) != len(thresholds): raise Unresolved('duplicate price scale threshold')
            reached = [scale for scale in scales if integer(scale['minimum']) <= quantity]
            if not reached: raise Unresolved('no reached price scale')
            scale = max(reached, key=lambda item: integer(item['minimum']))
            price_unit = decimal(condition['price_unit'])
            if price_unit <= 0: raise Unresolved('price unit must be positive')
            base = decimal(scale['price']) / price_unit
            currency = condition['currency']
            if currency != 'EUR':
                fx_key = condition['fx_key']
                base *= decimal(resolver.latest('fx', fx_key)['data']['eur_per_unit'])
            base = cents(base)
            work[pid] = {'position': position, 'base': base, 'goods': base * quantity,
                         'ordinary_setup': decimal(condition['setup_fee_eur']), 'condition': condition,
                         'pool_setup': ZERO, 'bonus': ZERO}
        except (Unresolved, KeyError, TypeError) as exc:
            errors[pid] = f'{pid}: base/condition unresolved ({exc})'
    approval = resolved['approval']
    if approval is not None and approval['min_goods_eur'] is not None and len(work) != len(positions):
        raise Unresolved('conditional order discount needs base goods for every position')
    goods = sum((item['goods'] for item in work.values()), ZERO)
    rate = discount_percent(approval, goods)
    result['discount_percent'] = rate
    pool_keys = {item['assignments']['pool_key'] for item in positions if item['assignments']['pool_key'] is not None}
    bonus_keys = {item['key'] for item in resolver.records_for('bonus')} | {item['assignments']['bonus_key'] for item in positions if item['assignments']['bonus_key'] is not None}
    bonus_members_seen = set()
    for kind, keys in [('pool', pool_keys), ('bonus', bonus_keys)]:
        for key in sorted(keys):
            members = [item for item in positions if item['assignments'][kind + '_key'] == key]
            member_ids = {item['id'] for item in members}
            try:
                payload = resolver.latest(kind, key)['data']
                if kind == 'pool' and set(payload['members']) != member_ids:
                    raise Unresolved('pool membership conflicts with governing Q&A')
                if kind == 'bonus':
                    member_ids = set(payload['members'])
                    if bonus_members_seen & member_ids: raise Unresolved('overlapping project bonus memberships')
                    bonus_members_seen.update(member_ids)
                if not member_ids <= ids:
                    raise Unresolved(f'{kind} includes an unknown tender position')
                if kind == 'pool':
                    if payload['allocation_rule'] != 'largest_remainder': raise Unresolved('unsupported shared setup allocation rule')
                    weights = {item['id']: item['quantity'] * decimal(item['material']['allocation_mass']) for item in members}
                    shares = allocate(decimal(payload['fee_eur']), weights)
                    for pid, value in shares.items():
                        if pid in work: work[pid]['pool_setup'] += value
                else:
                    if not member_ids <= work.keys(): raise Unresolved('bonus needs goods for every eligible member')
                    weights = {pid: work[pid]['goods'] for pid in member_ids}
                    shares = allocate(marginal_bonus(sum(weights.values(), ZERO), payload['bands']), weights)
                    for pid, value in shares.items(): work[pid]['bonus'] += value
            except (Unresolved, KeyError, TypeError) as exc:
                if kind == 'bonus' and not member_ids:
                    raise Unresolved(f'project bonus scope unresolved: {exc}') from exc
                for pid in member_ids: errors[pid] = f'{pid}: {kind} unresolved ({exc})'
    for pid, item in work.items():
        if pid in errors: continue
        position = item['position']; material = position['material']; quantity = position['quantity']
        assigned = position['assignments']
        try:
            clause = 'base'
            if assigned['clause_key'] is not None:
                clause = resolver.latest('clause', assigned['clause_key'])['data']['discount_components']
            if clause not in {'base', 'base_and_surcharge', 'none'}: raise Unresolved('unsupported discount clause')
            surcharge = ZERO
            key = item['condition']['index_key']
            if key is not None:
                payload = resolver.latest('index', key)['data']
                windows = [window for window in payload['windows'] if date(window['from']).date() <= resolver.day <= date(window['to']).date()]
                if len(windows) != 1: raise Unresolved('metal index must have exactly one applicable window')
                surcharge = decimal(material['surcharge_mass']) * decimal(windows[0]['eur_per_kg'])
            carton_cost = ZERO
            if assigned['tariff_key'] is not None:
                tariff = resolver.latest('tariff', assigned['tariff_key'])['data']
                carton_size = integer(material['carton_size'], positive=True)
                cartons = (quantity + carton_size - 1) // carton_size
                carton_cost = cartons * decimal(tariff['eur_per_carton'])
            stock = integer(material['stock'])
            weeks = integer(material['stock_weeks'] if stock >= pooled[material['number']] else material['production_weeks'])
            if assigned['commitment_key'] is not None:
                commitment = resolver.latest('delivery', assigned['commitment_key'])['data']
                if commitment['material'] == material['number'] and pooled[material['number']] <= integer(commitment['max_quantity']):
                    weeks = integer(commitment['weeks'])
            factor = ONE - rate / 100
            final = item['base'] * (factor if clause != 'none' else ONE)
            final += surcharge * (factor if clause == 'base_and_surcharge' else ONE)
            setup = item['ordinary_setup'] + item['pool_setup']
            final += (setup + carton_cost - item['bonus']) / quantity
            if final < 0: raise Unresolved('calculated negative final price')
            result['positions'].append({'position': pid, 'material_number': material['number'], 'quantity': quantity,
                                       'base_unit_price': item['base'], 'surcharge_per_unit': cents(surcharge),
                                       'packaging_per_unit': cents(carton_cost / quantity), 'rebate_total': item['bonus'],
                                       'unit_price': cents(final), 'lead_time_weeks': weeks})
        except (Unresolved, KeyError, TypeError) as exc:
            errors[pid] = f'{pid}: final price/delivery unresolved ({exc})'
    result['positions'].sort(key=lambda item: item['position'])
    result['total_net'] = cents(sum((item['quantity'] * item['unit_price'] for item in result['positions']), ZERO))
    if not result['positions']: raise Unresolved('no validated positions available for a partial bid')
    return {'answer': result, 'omitted': sorted(errors), 'gaps': list(errors.values()),
            'audit': {'selected_record_ids': sorted(resolver.used), 'pooled_demand': pooled,
                      'undiscounted_goods': str(goods), 'discount_percent': str(rate)}}
