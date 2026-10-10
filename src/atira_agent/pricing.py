"""Resolve evidence into final EUR prices. Missing information stays explicit."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, localcontext

from .business_rules import (
    ZERO,
    Unresolved,
    allocate,
    effective_position,
    engineering,
    exact_match,
    latest,
    marginal_bonus,
    money,
    pieces,
    price_condition,
    remaining_qa,
    valid_on,
)
from .contracts import PricingResult, ResolvedTender


def one(items, message):
    if len(items) != 1:
        raise Unresolved(message)
    return items[0]


def calculate(ledger, allow_partial=False) -> PricingResult:
    with localcontext() as ctx:
        ctx.prec = 40
        try:
            return _calculate(ledger, allow_partial)
        except (Unresolved, ArithmeticError, ValueError) as exc:
            return PricingResult(answer=None, unresolved={"order": [str(exc)]})


def _calculate(ledger, allow_partial):
    tender = one(ledger.all("tender"), "Need one tender record")
    date = tender.scenario_date
    if len(tender.position_ids) != len(set(tender.position_ids)):
        raise Unresolved("Duplicate tender positions")
    if not tender.quantities_complete or not tender.qa_complete:
        raise Unresolved("Tender quantities and applicable Q&A must be completely investigated")
    revision = one([x for x in ledger.all("revision") if x.current and x.full],
                   "Need one governing current full specification revision")
    answers = remaining_qa(ledger.all("qa"), date)

    def mail(kind, local_part, subject, required=True, **scope):
        result = latest(ledger.all(kind), date=date, reference=tender.reference,
                        sender=local_part + "@" + tender.mailbox_domain, subject=subject, **scope)
        if result is None and required:
            raise Unresolved(f"Missing applicable {subject} for {scope}")
        return result

    resolved = ResolvedTender(reference=tender.reference, decision="unresolved")
    lines, issues, missing = {}, defaultdict(list), []
    for pos in tender.position_ids:
        try:
            original = one([x for x in ledger.all("position") if x.position == pos], f"Missing position {pos}")
            position = effective_position(original, answers)
            req = one([x for x in ledger.all("requirement") if x.requirement_id == position.requirement_id
                       and x.revision == revision.revision], f"Missing current requirement for {pos}")
            technical = mail("technical", "technik", "Technikfreigabe", required=req.stroke_mode == "usable",
                             revision=revision.revision, requirement_id=req.requirement_id)
            attrs = engineering(req, answers, technical.reserve_per_end_mm if technical else None)
            quantity = pieces(position, req)
            search = one([x for x in ledger.all("search") if x.requirement_id == req.requirement_id
                          and x.revision == revision.revision and x.catalogue_group == req.catalogue_group
                          and x.complete], f"Need completed narrow ERP search for {pos}")
            candidates = [x for x in ledger.all("material") if x.material_number in search.candidate_materials]
            if len({x.material_number for x in candidates}) != len(set(search.candidate_materials)):
                raise Unresolved("Some ERP candidates have not been inspected")
            matches = [x for x in candidates if x.catalogue_group == req.catalogue_group and exact_match(x, attrs)]
            if not matches:
                missing.append(pos)
                continue
            material = one(matches, f"Multiple exact active matches for {pos}")
            lines[pos] = {"position": position, "requirement": req, "material": material, "quantity": quantity,
                          "base": None, "mass": None, "setup": position.ordinary_setup_eur
                          if position.ordinary_setup_eur is not None else material.ordinary_setup_eur,
                          "shared": ZERO, "packaging": ZERO, "bonus": ZERO, "scope": "base"}
        except (Unresolved, ValueError) as exc:
            issues[pos].append(str(exc))

    if missing:
        approval = mail("discount", "leitung", "", required=False)
        discount = approval.percent if approval and approval.minimum_base_goods_eur is None else ZERO
        resolved.decision, resolved.missing_materials = "no_bid", missing
        return PricingResult(answer={"tender_reference": tender.reference, "decision": "no_bid", "currency": "EUR",
                                      "discount_percent": discount, "positions": [], "total_net": ZERO},
                             audit=[{"rule": "no_active_exact_match", "positions": missing}])

    demand = defaultdict(int)
    for line in lines.values():
        demand[line["material"].material_number] += line["quantity"]
    # Every known line can depend on an unknown line's material and quantity.
    if len(lines) != len(tender.position_ids):
        raise Unresolved("Resolve quantities and material matches for ALL positions before pooled stock/order pricing")

    for pos, line in lines.items():
        try:
            material, qty, position = line["material"], line["quantity"], line["position"]
            condition, scale = price_condition(ledger.all("price"), material.material_number, qty, date)
            rate = Decimal(1)
            if condition.currency.upper() != "EUR":
                if not condition.fx_key:
                    raise Unresolved("Foreign currency price is missing its FX key")
                fx = mail("fx", "finanzen", "Devisenfixing", key=condition.fx_key, currency=condition.currency)
                if not valid_on(fx, date):
                    raise Unresolved("Latest FX fixing is outside its validity window")
                rate = fx.eur_per_unit
            line["base"] = money(scale.amount / condition.price_unit * rate)
            if material.surcharge_kind == "none":
                line["mass"] = ZERO
            else:
                if material.mass_kg is None:
                    raise Unresolved("Missing surcharge mass")
                if material.surcharge_kind == "fixed_per_kg":
                    metal_rate = material.fixed_rate_eur_per_kg
                else:
                    index = mail("metal_index", "kalkulation", "Preisindizes", key=material.metal_index_key)
                    metal_rate = one([r for r in index.rates if valid_on(r, date)],
                                     "Need one on-date metal index rate").eur_per_kg
                if metal_rate is None:
                    raise Unresolved("Missing mass surcharge rate")
                line["mass"] = material.mass_kg * metal_rate
            if line["setup"] is None:
                raise Unresolved("Need an evidenced ordinary setup fee or explicit zero for this position")
            if position.commercial_key:
                line["scope"] = mail("commercial", "kalkulation", "Konditionsregeln",
                                     key=position.commercial_key).discount_scope
            if position.packaging_key:
                tariff = mail("packaging", "logistik", "Verpackungstarife", key=position.packaging_key)
                if material.carton_size is None:
                    raise Unresolved("Missing pieces per carton")
                cartons = (qty + material.carton_size - 1) // material.carton_size
                line["packaging"] = cartons * tariff.carton_fee_eur
            pooled = demand[material.material_number]
            lead = material.stock_weeks if material.stock >= pooled else material.production_weeks
            if position.commitment_key:
                commitment = mail("commitment", "logistik", "Terminfreigabe", key=position.commitment_key)
                if commitment.material_number == material.material_number and pooled <= commitment.maximum_quantity:
                    lead = commitment.lead_time_weeks
            line["lead"] = lead
        except (Unresolved, ValueError) as exc:
            issues[pos].append(str(exc))

    if not tender.approvals_complete or not tender.commercial_rules_complete or not tender.bonus_rules_complete:
        raise Unresolved("Complete approval, commercial and project-bonus investigation before pricing")
    approval = mail("discount", "leitung", "", required=False)
    if approval and approval.minimum_base_goods_eur is not None and any(x["base"] is None for x in lines.values()):
        raise Unresolved("Conditional discount needs the whole tender's undiscounted base goods")
    goods = {pos: line["quantity"] * line["base"] for pos, line in lines.items() if line["base"] is not None}
    threshold_total = money(sum(goods.values(), ZERO))
    percent = approval.percent if approval else ZERO
    if approval and approval.minimum_base_goods_eur is not None and threshold_total < approval.minimum_base_goods_eur:
        percent = ZERO

    pool_members = defaultdict(list)
    for pos, line in lines.items():
        for key in line["position"].pool_keys:
            pool_members[key].append(pos)
    for key, members in pool_members.items():
        try:
            pool = mail("pool", "kalkulation", "Rüstpools", key=key)
            if any(lines[p]["material"].allocation_mass_kg is None for p in members):
                raise Unresolved("Missing allocation mass (distinct from surcharge mass)")
            allocation = allocate(pool.fee_eur, {p: lines[p]["quantity"] * lines[p]["material"].allocation_mass_kg
                                                for p in members}, pool.allocation)
            for pos, amount in allocation.items():
                lines[pos]["shared"] += amount
        except (Unresolved, ValueError) as exc:
            for pos in members:
                issues[pos].append(str(exc))

    bonus_groups = defaultdict(list)
    for pos, line in lines.items():
        if line["position"].bonus_plan:
            bonus_groups[line["position"].bonus_plan].append(pos)
    if bonus_groups:
        plans = [(mail("bonus", "finanzen", "Projektbonus", key=key), members)
                 for key, members in bonus_groups.items()]
    else:
        bonus = mail("bonus", "finanzen", "Projektbonus", required=False)
        plans = [(bonus, bonus.eligible_positions)] if bonus else []
    for bonus, members in plans:
        if bonus_groups and bonus.eligible_positions and set(bonus.eligible_positions) != set(members):
            raise Unresolved("Project-bonus membership conflicts between Q&A assignments and the finance record")
        if not set(members) <= set(tender.position_ids):
            raise Unresolved("Bonus includes an unknown tender position")
        if any(pos not in goods for pos in members):
            for pos in members:
                issues[pos].append("Whole eligible goods total is needed for project bonus")
        else:
            eligible = {pos: goods[pos] for pos in members}
            credit = marginal_bonus(sum(eligible.values(), ZERO), bonus.bands)
            for pos, amount in allocate(credit, eligible).items():
                lines[pos]["bonus"] = amount

    answer_lines, audit = [], []
    for pos, line in lines.items():
        if issues[pos]:
            continue
        qty, base, mass = line["quantity"], line["base"], line["mass"]
        factor = 1 - percent / 100
        discounted_base = base * factor if line["scope"] != "neither" else base
        discounted_mass = mass * factor if line["scope"] == "base_and_mass" else mass
        fees = line["setup"] + line["shared"] + line["packaging"] - line["bonus"]
        unit = money(discounted_base + discounted_mass + fees / qty)
        if unit < 0:
            issues[pos].append("Negative unit price; reconcile source rules")
            continue
        result = {"position": pos, "material_number": line["material"].material_number, "quantity": qty,
                  "unit_price": unit, "lead_time_weeks": line["lead"], "base_unit_price": base,
                  "surcharge_per_unit": money(mass + (line["setup"] + line["shared"]) / qty),
                  "packaging_per_unit": money(line["packaging"] / qty), "rebate_total": line["bonus"]}
        answer_lines.append(result)
        audit.append({"position": pos, "quantity": qty, "base": base, "mass": mass,
                      "ordinary_setup": line["setup"], "shared_setup": line["shared"],
                      "carton_cost": line["packaging"], "bonus": line["bonus"], "discount_scope": line["scope"],
                      "unit_price": unit, "material_evidence": line["material"].evidence})
    issues = {key: value for key, value in issues.items() if value}
    omitted = sorted(set(tender.position_ids) - {x["position"] for x in answer_lines})
    if omitted and not allow_partial or not answer_lines:
        return PricingResult(answer=None, omitted=omitted, unresolved=issues, audit=audit)
    answer = {"tender_reference": tender.reference, "decision": "bid", "currency": "EUR",
              "discount_percent": percent, "positions": answer_lines,
              "total_net": money(sum((x["quantity"] * x["unit_price"] for x in answer_lines), ZERO))}
    if omitted:
        answer["notes"] = "Unfinished positions explicitly omitted: " + ", ".join(omitted)
    audit.append({"rule": "approved_discount", "base_goods_threshold_total": threshold_total,
                  "percent": percent, "approval_evidence": approval.evidence if approval else tender.evidence})
    return PricingResult(answer=answer, omitted=omitted, unresolved=issues, audit=audit)
