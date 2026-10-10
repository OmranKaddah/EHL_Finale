from decimal import Decimal

import pytest

from hackathon_toolkit.rfq.resolution import authorized_record, final_quantity, amended_requirement, window_rate


def test_latest_exact_authority_ignores_decoys_and_future():
    base = dict(reference="TEST", sender="logistik@bidder.test", topic="Terminfreigabe", key="K")
    rows = [{**base, "dated": "2025-01-01", "ceiling": 100},
            {**base, "dated": "2025-02-01", "ceiling": 1},
            {**base, "dated": "2026-01-01", "ceiling": 500},
            {**base, "dated": "2025-03-01", "reference": "TEST-OTHER"},
            {**base, "dated": "2025-03-01", "sender": "logistik@other.test"}]
    chosen = authorized_record(rows, "TEST", "LOGISTIK@bidder.test", "Terminfreigabe", "2025-06-01", "K")
    assert chosen["ceiling"] == 1  # Failed ceiling cannot revive January approval.


def test_withdrawal_restores_previous_quantity_then_converts_sets():
    rows = [dict(number="1", dated="2025-01-01", position="01", quantity=5),
            dict(number="2", dated="2025-02-01", position="01", quantity=9),
            dict(number="3", dated="2025-03-01", withdraws=["2"])]
    assert final_quantity(2, "Satz", 3, "01", rows, "2025-04-01") == 15
    rows[2]["withdraws"].append("1")
    assert final_quantity(2, "Satz", 3, "01", rows, "2025-04-01") == 6
    assert final_quantity(2, "Stück", 3, "01", rows, "2025-02-01") == 9


def test_amendments_are_scoped_per_attribute_before_technical_reserve():
    attrs = dict(bore_mm="40", stroke_mm="100", pressure_bar="200", mounting="A", certification="B")
    rows = [dict(dated="2025-01-01", revision="R2", requirement="Q", changes={"stroke_mm": "110", "bore_mm": "42"}),
            dict(dated="2025-02-01", revision="R2", requirement="Q", changes={"stroke_mm": "120"}),
            dict(dated="2025-03-01", revision="R1", requirement="Q", changes={"bore_mm": "99"})]
    result = amended_requirement(attrs, "R2", "Q", rows, "2025-04-01", True, "2.5")
    assert Decimal(result["stroke_mm"]) == 125
    assert Decimal(result["bore_mm"]) == 42
    assert result["mounting"] == "A"
    with pytest.raises(ValueError, match="reserve"):
        amended_requirement(attrs, "R2", "Q", rows, "2025-04-01", True, None)


def test_index_selects_inclusive_window_not_last_rate():
    windows = [dict(valid_from="2025-01-01", valid_until="2025-06-01", rate="2"),
               dict(valid_from="2025-06-02", valid_until="2025-12-31", rate="8")]
    assert window_rate(windows, "2025-06-01") == "2"
    with pytest.raises(ValueError, match="exactly one"):
        window_rate(windows, "2026-01-01")


def test_same_timestamp_authority_is_ambiguous():
    row = dict(reference="X", sender="a@b.test", topic="T", dated="2025-01-01")
    with pytest.raises(ValueError, match="Ambiguous"):
        authorized_record([row, row], "X", "a@b.test", "T", "2025-01-01")
