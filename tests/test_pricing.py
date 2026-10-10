from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal as D

import pytest
from hypothesis import given
from hypothesis import strategies as st

from atira_agent.business_rules import (
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
from atira_agent.contracts import QA, Band
from atira_agent.pricing import calculate

DATE = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("value,expected", [("1.005", "1.01"), ("2.675", "2.68"), ("-1.005", "-1.01"), ("0.0049", "0.00")])
def test_half_up(value, expected):
    assert money(D(value)) == D(expected)


def test_full_price_and_breakdown(priced_ledger):
    result = calculate(priced_ledger)
    assert not result.unresolved
    assert result.answer["total_net"] == D("96.07")
    a, b = result.answer["positions"]
    assert a["base_unit_price"] == D("10.01")  # FX rounding precedes downstream math.
    assert a["unit_price"] == D("12.09")
    assert b["unit_price"] == D("11.96")
    assert (a["rebate_total"], b["rebate_total"]) == (D("0.83"), D("1.37"))
    assert a["surcharge_per_unit"] == D("2.69")
    assert [x["lead_time_weeks"] for x in (a, b)] == [6, 6]  # Pooled 8 > stock 7.
    assert [x["quantity"] for x in (a, b)] == [3, 5]  # Cartons don't increase quantities.


@pytest.mark.parametrize("threshold,expected", [("80.08", "10"), ("80.09", "0")])
def test_inclusive_approval_threshold(priced_ledger, threshold, expected):
    value = priced_ledger.records["discount"]["disc"]
    priced_ledger.records["discount"]["disc"] = value.model_copy(update={"minimum_base_goods_eur": D(threshold)})
    assert calculate(priced_ledger).answer["discount_percent"] == D(expected)


def test_latest_failed_condition_does_not_revive_old(priced_ledger):
    old = priced_ledger.records["discount"]["disc"]
    priced_ledger.records["discount"]["new"] = old.model_copy(update={"id": "new", "sent_at": DATE,
                                                                 "minimum_base_goods_eur": D("1000"), "percent": D("20")})
    assert calculate(priced_ledger).answer["discount_percent"] == 0


@pytest.mark.parametrize("scope,expected", [("base", "12.09"), ("base_and_mass", "11.95"), ("neither", "13.09")])
def test_commercial_clauses(priced_ledger, scope, expected):
    pos = priced_ledger.records["position"]["A"]
    priced_ledger.records["position"]["A"] = pos.model_copy(update={"commercial_key": "C"})
    priced_ledger.record("commercial", dict(id="c", evidence=["e1"], reference="TEST-RFQ", sender="kalkulation@synthetic.test",
        subject="Konditionsregeln TEST-RFQ", sent_at="2026-01-06T00:00:00Z", key="C", discount_scope=scope))
    assert calculate(priced_ledger).answer["positions"][0]["unit_price"] == D(expected)


def test_withdrawn_qa_and_scoped_amendment(priced_ledger):
    pos = priced_ledger.all("position")[0]
    req = priced_ledger.all("requirement")[0]
    data = dict(evidence=["e1"], issued_at=DATE, position="A")
    answers = [QA(id="q1", quantity=9, **data), QA(id="q2", quantity=12, **data), QA(id="q3", withdraws=["q2"], **data)]
    remaining = remaining_qa(answers, DATE)
    assert effective_position(pos, remaining).quantity == 9
    amendments = [QA(id="wrong", revision="OLD", requirement_id="R", amendments={"stroke_mm": "999"}, **data),
                  QA(id="right", revision="CURRENT", requirement_id="R", amendments={"stroke_mm": "100"}, **data)]
    usable = req.model_copy(update={"stroke_mode": "usable"})
    assert engineering(usable, amendments, D(7)).stroke_mm == 114
    with pytest.raises(Unresolved):
        engineering(usable, amendments, None)


def test_sets_and_exact_certification(priced_ledger):
    pos, req, material = priced_ledger.all("position")[0], priced_ledger.all("requirement")[0], priced_ledger.all("material")[0]
    assert pieces(pos.model_copy(update={"unit": "set"}), req.model_copy(update={"pieces_per_set": 4})) == 12
    attrs = req.attributes.model_copy(update={"certification": "OTHER"})
    assert not exact_match(material, attrs)
    assert not exact_match(material.model_copy(update={"active": False}), req.attributes)


def test_price_tiers_and_inclusive_windows(priced_ledger):
    condition = priced_ledger.all("price")[0]
    assert valid_on(condition, condition.valid_from)
    assert valid_on(condition, condition.valid_to)
    from atira_agent.contracts import Scale
    condition = condition.model_copy(update={"scales": [Scale(min_quantity=1, amount=100), Scale(min_quantity=5, amount=90)]})
    assert price_condition([condition], "SYN-M", 5, DATE)[1].amount == 90
    assert price_condition([condition], "SYN-M", 3, DATE)[1].amount == 100


def test_authority_reference_future(priced_ledger):
    original = priced_ledger.all("discount")[0]
    wrong = original.model_copy(update={"reference": "OTHER", "sent_at": DATE, "percent": D(99)})
    future = original.model_copy(update={"sent_at": datetime(2030, 1, 1, tzinfo=timezone.utc)})
    spoof = original.model_copy(update={"sender": "leitung@lookalike.test"})
    assert latest([wrong, future, spoof, original], date=DATE, reference="TEST-RFQ",
                  sender="leitung@synthetic.test", subject="") == original


def test_authority_comparison_ignores_zero_width_formatting(priced_ledger):
    original = priced_ledger.all("discount")[0]
    marked = original.model_copy(update={"reference": "TEST-\u200bRFQ", "subject": "Approval TEST-\u200bRFQ"})
    assert latest([marked], date=DATE, reference="TEST-RFQ", sender="leitung@synthetic.test",
                  subject="Approval TEST-RFQ") == marked


def test_conditional_commitment_uses_pooled_quantity(priced_ledger):
    pos = priced_ledger.records["position"]["A"]
    priced_ledger.records["position"]["A"] = pos.model_copy(update={"commitment_key": "D"})
    record = dict(id="delivery", evidence=["e1"], reference="TEST-RFQ", sender="logistik@synthetic.test",
                  subject="Terminfreigabe TEST-RFQ", sent_at="2026-01-06T00:00:00Z", key="D",
                  material_number="SYN-M", maximum_quantity=8, lead_time_weeks=2)
    priced_ledger.record("commitment", record)
    assert calculate(priced_ledger).answer["positions"][0]["lead_time_weeks"] == 2
    record["maximum_quantity"] = 7
    priced_ledger.record("commitment", record)
    assert calculate(priced_ledger).answer["positions"][0]["lead_time_weeks"] == 6


def test_metal_index_selects_window_not_last(priced_ledger):
    material = priced_ledger.records["material"]["mat"]
    priced_ledger.records["material"]["mat"] = material.model_copy(update={"surcharge_kind": "index", "metal_index_key": "I"})
    priced_ledger.record("metal_index", dict(id="idx", evidence=["e1"], reference="TEST-RFQ", sender="kalkulation@synthetic.test",
        subject="Preisindizes TEST-RFQ", sent_at="2026-01-06T00:00:00Z", key="I", rates=[
            dict(valid_from="2026-01-01T00:00:00Z", valid_to="2026-01-31T23:59:59Z", eur_per_kg="2"),
            dict(valid_from="2026-02-01T00:00:00Z", valid_to="2026-02-28T23:59:59Z", eur_per_kg="99")]))
    assert calculate(priced_ledger).answer["total_net"] == D("96.07")


def test_no_bid_requires_completed_search(priced_ledger):
    material = priced_ledger.records["material"]["mat"]
    priced_ledger.records["material"]["mat"] = material.model_copy(update={"active": False})
    result = calculate(priced_ledger)
    assert result.answer["decision"] == "no_bid"
    assert result.answer["positions"] == []
    assert result.answer["discount_percent"] == 0
    priced_ledger.records["search"].clear()
    assert calculate(priced_ledger).answer is None


def test_partial_keeps_whole_order_allocation(priced_ledger):
    pos = priced_ledger.records["position"]["B"]
    priced_ledger.records["position"]["B"] = pos.model_copy(update={"commitment_key": "UNKNOWN"})
    assert calculate(priced_ledger).answer is None
    result = calculate(priced_ledger, allow_partial=True)
    assert result.omitted == ["B"]
    assert result.answer["positions"][0]["rebate_total"] == D("0.83")
    assert result.answer["positions"][0]["unit_price"] == D("12.09")
    assert result.answer["total_net"] == D("36.27")


def test_unknown_global_dependency_blocks_partial(priced_ledger):
    priced_ledger.records["position"].pop("B")
    assert calculate(priced_ledger, allow_partial=True).answer is None


def test_bonus_is_marginal():
    assert marginal_bonus(D(150), [Band(upper_eur=100, percent=1), Band(upper_eur=None, percent=3)]) == D("2.50")


def test_qa_setup_override_is_position_scoped(priced_ledger):
    priced_ledger.record("qa", dict(id="setup-change", evidence=["e1"], issued_at=DATE,
                                   position="A", ordinary_setup_eur="4"))
    result = calculate(priced_ledger)
    a, b = result.answer["positions"]
    assert a["unit_price"] == D("12.76")
    assert b["unit_price"] == D("11.96")
    assert result.audit[0]["ordinary_setup"] == D("4")


def test_amended_unit_is_converted_using_current_specification(priced_ledger):
    position = priced_ledger.all("position")[0]
    requirement = priced_ledger.all("requirement")[0].model_copy(update={"pieces_per_set": 4})
    amendment = QA(id="units", evidence=["e1"], issued_at=DATE, position="A", quantity=2, unit="set")
    assert pieces(effective_position(position, [amendment]), requirement) == 8


def test_bonus_keys_do_not_select_a_newer_unrelated_plan(priced_ledger):
    original = priced_ledger.all("bonus")[0]
    for pos in ("A", "B"):
        row = priced_ledger.records["position"][pos]
        priced_ledger.records["position"][pos] = row.model_copy(update={"bonus_plan": "PLAN-A"})
    priced_ledger.records["bonus"][original.id] = original.model_copy(update={"key": "PLAN-A"})
    priced_ledger.records["bonus"]["other"] = original.model_copy(update={"id": "other", "key": "PLAN-B",
        "sent_at": DATE, "bands": [Band(upper_eur=None, percent=99)]})
    assert calculate(priced_ledger).answer["total_net"] == D("96.07")


def test_bonus_nonmembers_receive_zero_and_membership_conflicts_block(priced_ledger):
    original = priced_ledger.all("bonus")[0]
    a = priced_ledger.records["position"]["A"]
    priced_ledger.records["position"]["A"] = a.model_copy(update={"bonus_plan": "PLAN-A"})
    priced_ledger.records["bonus"][original.id] = original.model_copy(update={"key": "PLAN-A"})
    assert "membership conflicts" in calculate(priced_ledger).unresolved["order"][0]
    priced_ledger.records["bonus"][original.id] = original.model_copy(update={"key": "PLAN-A", "eligible_positions": [],
        "bands": [Band(upper_eur=None, percent=10)]})
    a, b = calculate(priced_ledger).answer["positions"]
    assert a["rebate_total"] == D("3.00")
    assert b["rebate_total"] == 0


def test_allocation_tie_and_alternative_rules():
    weights = {"B": D(1), "A": D(1), "C": D(1)}
    assert allocate(D("0.02"), weights) == {"A": D(".01"), "B": D(".01"), "C": D(0)}
    assert allocate(D("0.02"), weights, "half_up_adjust_last")["C"] == 0
    assert allocate(D("0.02"), weights, "floor_remainder_last")["C"] == D(".02")


@given(st.integers(0, 100000), st.lists(st.integers(1, 1000), min_size=1, max_size=20))
def test_allocated_cents_conserved(cents, values):
    total = D(cents) / 100
    result = allocate(total, {str(i): D(weight) for i, weight in enumerate(values)})
    assert sum(result.values()) == total
    assert all(value >= 0 and value == money(value) for value in result.values())
