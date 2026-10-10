"""Submission-boundary schema, completeness and independent arithmetic checks."""

import json
from decimal import Decimal
from jsonschema import Draft202012Validator
from .records import Unresolved
from .pricing import cents


def wire(value):
    """Only convert cents to JSON numbers at the platform boundary."""
    if isinstance(value, Decimal):
        if not value.is_finite(): raise Unresolved('nonfinite answer number')
        number = float(value)
        if Decimal(str(number)) != value: raise Unresolved('answer number cannot be safely serialized')
        return number
    if isinstance(value, dict): return {key: wire(item) for key, item in value.items()}
    if isinstance(value, list): return [wire(item) for item in value]
    return value


def validate_answer(calculation, schema, tender_ids):
    answer = calculation['answer']
    if not isinstance(schema, dict): raise Unresolved('runtime answer schema is required')
    submitted = wire(answer)
    errors = sorted(Draft202012Validator(schema).iter_errors(submitted), key=lambda error: str(error.path))
    if errors: raise Unresolved('answer schema: ' + errors[0].message)
    if len(json.dumps(submitted).encode()) > 65536: raise Unresolved('answer exceeds platform size limit')
    ids = [item['position'] for item in answer['positions']]
    if len(set(ids)) != len(ids): raise Unresolved('duplicate answer position')
    if not set(ids) <= set(tender_ids): raise Unresolved('answer includes an unknown tender position')
    omitted = set(calculation['omitted'])
    if answer['decision'] == 'bid':
        if not tender_ids or omitted & set(ids) or set(ids) | omitted != set(tender_ids):
            raise Unresolved('every bid position must be included or explicitly omitted')
    elif answer['decision'] == 'no_bid':
        if ids or answer['total_net'] != 0 or omitted: raise Unresolved('invalid no-bid answer')
    else: raise Unresolved('invalid decision')
    computed = cents(sum((Decimal(item['quantity']) * Decimal(str(item['unit_price'])) for item in answer['positions']), Decimal(0)))
    if computed != answer['total_net']: raise Unresolved('independent line-total check failed')
    for item in answer['positions']:
        if item['quantity'] <= 0: raise Unresolved('bid quantity must be positive')
        for field in ('unit_price', 'base_unit_price', 'surcharge_per_unit', 'packaging_per_unit', 'rebate_total'):
            if field in item and Decimal(str(item[field])) != cents(Decimal(str(item[field]))):
                raise Unresolved(f'{field} must be rounded to cents')
    return submitted
