"""Pure RFQ arithmetic; never discovers records or substitutes unknown inputs."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, localcontext

from .models import BidInput, Material

CENT = Decimal("0.01")
ZERO = Decimal(0)


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def allocate_cents(total: Decimal, weights: dict[str, Decimal]) -> dict[str, Decimal]:
    """Conserve rounded total, largest remainders first; ties by position string."""
    if not total.is_finite() or total < 0 or not weights or any(
        not w.is_finite() or w < 0 for w in weights.values()
    ):
        raise ValueError("Allocation requires finite nonnegative amount and weights")
    total = cents(total)
    weight = sum(weights.values(), ZERO)
    if not weight:
        if total:
            raise ValueError("Cannot allocate a nonzero fee against zero weights")
        return dict.fromkeys(weights, ZERO)
    with localcontext() as ctx:
        ctx.prec = 60
        exact = {key: total * 100 * value / weight for key, value in weights.items()}
        whole = {key: int(value.to_integral_value(rounding=ROUND_FLOOR)) for key, value in exact.items()}
        remainder = int(total * 100) - sum(whole.values())
        order = sorted(weights, key=lambda key: (-(exact[key] - whole[key]), key))
        for key in order[:remainder]:
            whole[key] += 1
        return {key: Decimal(value) / 100 for key, value in whole.items()}


def select_material(position) -> Material | None:
    if not position.catalogue_complete:
        raise ValueError(f"Unresolved catalogue search for {position.position}")
    matches = [m for m in position.candidates if m.active and m.attributes == position.requirement]
    if len(matches) > 1:
        raise ValueError(f"Ambiguous material for {position.position}")
    return matches[0] if matches else None


def calculate_bid(data: BidInput | dict) -> dict:
    """Return answer plus audit trace. Decimal outputs remain exact until wire serialization."""
    data = data if isinstance(data, BidInput) else BidInput.model_validate(data)
    with localcontext() as context:
        context.prec = 60
        return _calculate(data)


def _calculate(data: BidInput) -> dict:
    selected = {p.position: select_material(p) for p in data.positions}
    answer = dict(tender_reference=data.tender_reference, decision="bid", currency="EUR",
                  discount_percent=data.discount.percent, positions=[], total_net=ZERO)
    missing = [key for key, value in selected.items() if value is None]
    if missing:
        answer.update(decision="no_bid", discount_percent=(ZERO if data.discount.minimum_goods_eur is not None
                                                          else data.discount.percent))
        return {"answer": answer, "audit": {"missing_material_positions": missing}}

    demand = defaultdict(int)
    catalogue = {}
    base, goods, trace = {}, {}, {}
    for p in data.positions:
        m = selected[p.position]
        if m.number in catalogue and catalogue[m.number] != m:
            raise ValueError(f"Conflicting ERP facts for material {m.number}")
        catalogue[m.number] = m
        demand[m.number] += p.quantity
        conditions = [c for c in m.conditions if c.valid_from <= data.scenario_date <= c.valid_until]
        if len(conditions) != 1:
            raise ValueError(f"Expected one valid price condition for {p.position}")
        condition = conditions[0]
        scales = [s for s in condition.scales if s.minimum_pieces <= p.quantity]
        if not scales:
            raise ValueError(f"No applicable price scale for {p.position}")
        scale = max(scales, key=lambda s: s.minimum_pieces)
        base[p.position] = cents(scale.price / condition.price_unit_pieces * condition.eur_per_currency)
        goods[p.position] = base[p.position] * p.quantity
        trace[p.position] = {"scale_minimum": scale.minimum_pieces, "goods_eur": goods[p.position]}

    goods_total = cents(sum(goods.values(), ZERO))
    discount = data.discount.percent
    if data.discount.minimum_goods_eur is not None and goods_total < data.discount.minimum_goods_eur:
        discount = ZERO
    answer["discount_percent"] = discount
    factor = 1 - discount / 100
    setup = dict.fromkeys(selected, ZERO)
    pool_audit = {}
    for pool in data.setup_pools:
        weights = {p.position: Decimal(p.quantity) * selected[p.position].allocation_mass_kg
                   for p in data.positions if p.position in pool.positions}
        allocations = allocate_cents(pool.fee_eur, weights)
        pool_audit[pool.key] = allocations
        for key, value in allocations.items():
            setup[key] += value

    rebates = dict.fromkeys(selected, ZERO)
    bonus_total = ZERO
    if data.bonus:
        eligible = {key: goods[key] for key in data.bonus.positions}
        eligible_total = sum(eligible.values(), ZERO)
        lower = ZERO
        raw_bonus = ZERO
        for band in data.bonus.bands:
            upper = eligible_total if band.up_to_eur is None else min(eligible_total, band.up_to_eur)
            raw_bonus += max(ZERO, upper - lower) * band.percent / 100
            if band.up_to_eur is None or band.up_to_eur >= eligible_total:
                break
            lower = band.up_to_eur
        else:
            if eligible_total > lower:
                raise ValueError("Bonus bands do not cover eligible goods total")
        bonus_total = cents(raw_bonus)
        rebates.update(allocate_cents(bonus_total, eligible))

    for p in data.positions:
        key, m = p.position, selected[p.position]
        mass = m.surcharge_mass_kg * p.metal_eur_per_kg
        cartons = (p.quantity + m.carton_pieces - 1) // m.carton_pieces
        packaging = cartons * p.carton_eur
        setup_total = p.ordinary_setup_eur + setup[key]
        unit = base[key] * (factor if p.discount_scope != "none" else 1)
        unit += mass * (factor if p.discount_scope == "base_and_mass" else 1)
        unit += (setup_total + packaging - rebates[key]) / p.quantity
        if unit < 0:
            raise ValueError(f"Negative final unit price for {key}")
        weeks = m.stock_weeks if m.stock_pieces >= demand[m.number] else m.production_weeks
        committed = bool(p.commitment and p.commitment.material_number == m.number
                         and demand[m.number] <= p.commitment.ceiling_pieces)
        if committed:
            weeks = p.commitment.weeks
        # Surcharge reports mass plus per-piece setup, before any discount (rule 25).
        row = dict(position=key, material_number=m.number, quantity=p.quantity,
                   base_unit_price=base[key], surcharge_per_unit=cents(mass + setup_total / p.quantity),
                   packaging_per_unit=cents(packaging / p.quantity), rebate_total=rebates[key],
                   unit_price=cents(unit), lead_time_weeks=weeks)
        answer["positions"].append(row)
        trace[key].update(pooled_demand=demand[m.number], cartons=cartons, mass_eur_per_piece=mass,
                          setup_eur=setup_total, packaging_eur=packaging, commitment_applied=committed,
                          unrounded_unit_price=unit)
    answer["total_net"] = cents(sum((r["quantity"] * r["unit_price"] for r in answer["positions"]), ZERO))
    return {"answer": answer, "audit": {"goods_total_eur": goods_total, "bonus_total_eur": bonus_total,
                                       "setup_allocations": pool_audit, "positions": trace}}
