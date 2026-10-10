"""Deterministic scope, precedence and matching rules; no browser knowledge."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from email.utils import parseaddr

from .contracts import Engineering

CENT = Decimal("0.01")
ZERO = Decimal(0)


class Unresolved(ValueError):
    pass


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise Unresolved("A date is missing its source timezone")
    return value.astimezone(timezone.utc)


def valid_on(item, date: datetime) -> bool:
    return ((item.valid_from is None or aware(item.valid_from) <= aware(date)) and
            (item.valid_to is None or aware(date) <= aware(item.valid_to)))


def latest(items, *, date: datetime, reference: str, sender: str, subject: str, **scope):
    applicable = [x for x in items if x.reference == reference and
                  parseaddr(x.sender)[1].casefold() == sender.casefold() and
                  subject.casefold() in x.subject.casefold() and aware(x.sent_at) <= aware(date) and
                  all(getattr(x, key) == value for key, value in scope.items())]
    if not applicable:
        return None
    applicable.sort(key=lambda x: aware(x.sent_at), reverse=True)
    if len(applicable) > 1 and applicable[0].sent_at == applicable[1].sent_at:
        a, b = (x.model_dump(exclude={"id", "evidence"}) for x in applicable[:2])
        if a != b:
            raise Unresolved("Conflicting equally recent authorized records")
    return applicable[0]


def remaining_qa(answers, date: datetime):
    dated = [x for x in answers if aware(x.issued_at) <= aware(date)]
    withdrawn = {target for x in dated for target in x.withdraws}
    return sorted([x for x in dated if x.id not in withdrawn], key=lambda x: (aware(x.issued_at), x.id))


def effective_position(position, answers):
    updates = {}
    for answer in answers:
        if answer.position != position.position:
            continue
        for key in ("quantity", "unit", "commercial_key", "packaging_key", "commitment_key", "pool_keys", "ordinary_setup_eur"):
            value = getattr(answer, key)
            if value is not None:
                updates[key] = value
        if "bonus_plan" in answer.model_fields_set:
            updates["bonus_plan"] = answer.bonus_plan
    return position.model_copy(update=updates)


def engineering(requirement, answers, reserve: Decimal | None):
    attributes = requirement.attributes.model_dump()
    for answer in answers:
        if answer.revision == requirement.revision and answer.requirement_id == requirement.requirement_id:
            unknown = set(answer.amendments) - set(attributes)
            if unknown:
                raise Unresolved(f"Unsupported technical amendments: {sorted(unknown)}")
            attributes.update(answer.amendments)
    result = Engineering.model_validate(attributes)
    if requirement.stroke_mode == "usable":
        if reserve is None:
            raise Unresolved("Missing revision-specific per-end stroke reserve")
        result = result.model_copy(update={"stroke_mm": result.stroke_mm + 2 * reserve})
    return result


def pieces(position, requirement) -> int:
    if position.unit == "pieces":
        return position.quantity
    if requirement.pieces_per_set is None:
        raise Unresolved("Missing pieces per set in the governing revision")
    return position.quantity * requirement.pieces_per_set


def exact_match(material, required: Engineering) -> bool:
    return material.active and material.attributes == required


def price_condition(conditions, material_number, quantity: int, date: datetime):
    applicable = [x for x in conditions if x.material_number == material_number and valid_on(x, date)]
    if len(applicable) != 1:
        raise Unresolved(f"Need one unambiguous on-date price condition for {material_number}")
    condition = applicable[0]
    scales = [x for x in condition.scales if x.min_quantity <= quantity]
    if not scales:
        raise Unresolved("No applicable price scale")
    maximum = max(x.min_quantity for x in scales)
    best = [x for x in scales if x.min_quantity == maximum]
    if len({x.amount for x in best}) != 1:
        raise Unresolved("Conflicting quantity scales")
    return condition, best[0]


def allocate(total: Decimal, weights: dict[str, Decimal], rule="largest_remainder") -> dict[str, Decimal]:
    from decimal import ROUND_DOWN

    total = money(total)
    if total < 0 or any(value < 0 for value in weights.values()):
        raise Unresolved("Negative allocation")
    if not weights:
        if total:
            raise Unresolved("Nonzero fee has no allocation members")
        return {}
    keys = sorted(weights)
    weight = sum(weights.values(), ZERO)
    if not weight:
        if total:
            raise Unresolved("Nonzero fee has zero allocation weight")
        return dict.fromkeys(keys, ZERO)
    cents = int(total * 100)
    raw = {key: Decimal(cents) * weights[key] / weight for key in keys}
    mode = ROUND_HALF_UP if rule == "half_up_adjust_last" else ROUND_DOWN
    shares = {key: int(raw[key].to_integral_value(rounding=mode)) for key in keys}
    remainder = cents - sum(shares.values())
    if rule == "largest_remainder":
        order = sorted(keys, key=lambda key: (-(raw[key] - shares[key]), key))
        for key in order[:remainder]:
            shares[key] += 1
    elif rule in {"half_up_adjust_last", "floor_remainder_last"}:
        shares[keys[-1]] += remainder
    else:
        raise Unresolved(f"Unsupported cent-allocation rule: {rule}")
    if any(value < 0 for value in shares.values()) or sum(shares.values()) != cents:
        raise Unresolved("Invalid cent allocation")
    return {key: Decimal(value) / 100 for key, value in shares.items()}


def marginal_bonus(goods: Decimal, bands) -> Decimal:
    lower, credit = ZERO, ZERO
    for index, band in enumerate(bands):
        upper = band.upper_eur
        if upper is None and index != len(bands) - 1:
            raise Unresolved("Unbounded bonus band must be last")
        if upper is not None and upper <= lower:
            raise Unresolved("Bonus bands must have increasing cumulative upper boundaries")
        part = max(ZERO, min(goods, upper if upper is not None else goods) - lower)
        credit += part * band.percent / 100
        if upper is None:
            break
        lower = upper
    return money(credit)
