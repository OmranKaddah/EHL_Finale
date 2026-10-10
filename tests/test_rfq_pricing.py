"""Invented fixtures, not public challenge values or answers."""
from copy import deepcopy
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from hackathon_toolkit.rfq.models import BidInput
from hackathon_toolkit.rfq.pricing import allocate_cents, calculate_bid


@pytest.fixture
def bid():
    attrs = dict(bore_mm="37", stroke_mm="123", pressure_bar="210", mounting="fixture-mount", certification="fixture-cert")
    material = dict(number="SYNTHETIC-A", active=True, attributes=attrs.copy(), stock_pieces=12,
                    stock_weeks=1, production_weeks=7, carton_pieces=4, surcharge_mass_kg="2",
                    allocation_mass_kg="3", conditions=[dict(valid_from="2025-01-01", valid_until="2025-12-31",
                    currency="EUR", price_unit_pieces=1, eur_per_currency="1",
                    scales=[dict(minimum_pieces=0, price="10"), dict(minimum_pieces=10, price="8")])])
    position = dict(position="01", quantity=6, requirement=attrs.copy(), catalogue_complete=True,
                    candidates=[material], discount_scope="base", metal_eur_per_kg="0.5", ordinary_setup_eur="3",
                    carton_eur="2", commitment=None, evidence_ids=["ev-1"])
    return dict(tender_reference="SYNTHETIC-UNIT-TEST", scenario_date="2025-06-01", positions=[position],
                discount=dict(percent="10", minimum_goods_eur=None, evidence_ids=["ev-1"]),
                setup_pools=[], bonus=None, evidence_ids=["ev-1"])


def test_complete_price_and_breakdown(bid):
    output = calculate_bid(bid)
    row = output["answer"]["positions"][0]
    # 10*.9 + 2*.5 + (3 + ceil(6/4)*2)/6 = 11.16666...
    assert row == dict(position="01", material_number="SYNTHETIC-A", quantity=6,
                       base_unit_price=D("10.00"), surcharge_per_unit=D("1.50"),
                       packaging_per_unit=D("0.67"), rebate_total=D("0"),
                       unit_price=D("11.17"), lead_time_weeks=1)
    assert output["answer"]["total_net"] == D("67.02")


@pytest.mark.parametrize("scope,expected", [("base", "11.17"), ("base_and_mass", "11.07"), ("none", "12.17")])
def test_clause_discount_scope(bid, scope, expected):
    bid["positions"][0]["discount_scope"] = scope
    assert calculate_bid(bid)["answer"]["positions"][0]["unit_price"] == D(expected)


def test_shared_stock_scales_stay_per_position_and_commitments(bid):
    second = deepcopy(bid["positions"][0])
    second.update(position="02", quantity=8)
    bid["positions"].append(second)
    bid["positions"][0]["commitment"] = dict(material_number="SYNTHETIC-A", ceiling_pieces=14, weeks=2)
    rows = calculate_bid(bid)["answer"]["positions"]
    assert [r["base_unit_price"] for r in rows] == [D(10), D(10)]
    assert [r["lead_time_weeks"] for r in rows] == [2, 7]
    bid["positions"][0]["commitment"]["ceiling_pieces"] = 13
    assert [r["lead_time_weeks"] for r in calculate_bid(bid)["answer"]["positions"]] == [7, 7]


@pytest.mark.parametrize("threshold,expected", [("60", "10"), ("60.01", "0")])
def test_discount_threshold_excludes_extras_and_is_inclusive(bid, threshold, expected):
    bid["discount"]["minimum_goods_eur"] = threshold
    assert calculate_bid(bid)["answer"]["discount_percent"] == D(expected)


def test_currency_price_unit_half_up_and_scale_selection(bid):
    p = bid["positions"][0]
    p["quantity"] = 10
    condition = p["candidates"][0]["conditions"][0]
    condition.update(currency="USD", price_unit_pieces=100, eur_per_currency="0.5",
                     scales=[dict(minimum_pieces=0, price="9999"), dict(minimum_pieces=10, price="1001")])
    bid["discount"]["minimum_goods_eur"] = "50.10"
    output = calculate_bid(bid)
    assert output["answer"]["positions"][0]["base_unit_price"] == D("5.01")
    assert output["answer"]["discount_percent"] == D(10)


def test_no_bid_only_for_proven_missing_active_exact_material(bid):
    bid["positions"][0]["candidates"][0]["active"] = False
    bid["discount"]["minimum_goods_eur"] = "0"
    answer = calculate_bid(bid)["answer"]
    assert (answer["decision"], answer["positions"], answer["total_net"], answer["discount_percent"]) == ("no_bid", [], 0, 0)
    bid["positions"][0]["catalogue_complete"] = False
    with pytest.raises(ValueError, match="Unresolved"):
        calculate_bid(bid)


def test_exact_match_and_ambiguity(bid):
    p = bid["positions"][0]
    p["candidates"][0]["attributes"]["stroke_mm"] = "124"
    assert calculate_bid(bid)["answer"]["decision"] == "no_bid"
    p["candidates"][0]["attributes"]["stroke_mm"] = "123"
    other = deepcopy(p["candidates"][0])
    other["number"] = "SYNTHETIC-B"
    p["candidates"].append(other)
    with pytest.raises(ValueError, match="Ambiguous"):
        calculate_bid(bid)


def test_setup_and_marginal_bonus_allocations_conserve_cents(bid):
    second = deepcopy(bid["positions"][0])
    second.update(position="02", quantity=3)
    bid["positions"].append(second)
    bid["setup_pools"] = [dict(key="synthetic-pool", positions=["01", "02"], fee_eur="0.05",
                               allocation="largest_remainder", evidence_ids=["ev-1"])]
    bid["bonus"] = dict(positions=["01", "02"], bands=[dict(up_to_eur="50", percent="1"),
                         dict(up_to_eur=None, percent="2")], evidence_ids=["ev-1"])
    output = calculate_bid(bid)
    assert output["audit"]["setup_allocations"]["synthetic-pool"] == {"01": D(".03"), "02": D(".02")}
    assert output["audit"]["bonus_total_eur"] == D("1.30")  # 50*.01 + 40*.02
    rows = output["answer"]["positions"]
    assert [r["rebate_total"] for r in rows] == [D(".87"), D(".43")]
    assert sum(r["rebate_total"] for r in rows) == D("1.30")
    assert rows[0]["unit_price"] == D("11.03")


def test_largest_remainders_ties_are_identifier_order_not_input_order():
    assert allocate_cents(D(".02"), {"03": D(1), "01": D(1), "02": D(1)}) == {
        "01": D(".01"), "02": D(".01"), "03": D(0)}
    for n in range(1, 30):
        weights = {f"{i:02}": D(i + 1) for i in range(n)}
        allocation = allocate_cents(D("17.135"), weights)
        assert sum(allocation.values()) == D("17.14")
        assert all(v >= 0 and v == v.quantize(D(".01")) for v in allocation.values())


@pytest.mark.parametrize("mutation", ["duplicate", "quantity_bool", "nan", "unknown", "bad_members"])
def test_invalid_inputs_rejected(bid, mutation):
    if mutation == "duplicate":
        bid["positions"].append(deepcopy(bid["positions"][0]))
    elif mutation == "quantity_bool":
        bid["positions"][0]["quantity"] = True
    elif mutation == "nan":
        bid["discount"]["percent"] = "NaN"
    elif mutation == "unknown":
        bid["positions"][0]["guessed"] = True
    else:
        bid["bonus"] = dict(positions=["absent"], bands=[dict(up_to_eur=None, percent="1")], evidence_ids=["ev-1"])
    with pytest.raises(ValidationError):
        BidInput.model_validate(bid)


def test_conflicting_material_and_overlapping_conditions(bid):
    second = deepcopy(bid["positions"][0])
    second["position"] = "02"
    second["candidates"][0]["stock_pieces"] = 99
    bid["positions"].append(second)
    with pytest.raises(ValueError, match="Conflicting ERP"):
        calculate_bid(bid)
    bid["positions"].pop()
    conditions = bid["positions"][0]["candidates"][0]["conditions"]
    conditions.append(deepcopy(conditions[0]))
    with pytest.raises(ValueError, match="one valid price"):
        calculate_bid(bid)


def test_rounded_breakdowns_are_not_fed_back_to_final_price(bid):
    p = bid["positions"][0]
    p.update(quantity=3, ordinary_setup_eur=".01", carton_eur=".01", metal_eur_per_kg="0")
    bid["discount"]["percent"] = "0"
    row = calculate_bid(bid)["answer"]["positions"][0]
    assert row["surcharge_per_unit"] == row["packaging_per_unit"] == D("0.00")
    assert row["unit_price"] == D("10.01")
