from __future__ import annotations

import pytest

from atira_agent.contracts import Observation
from atira_agent.evidence import EvidenceLedger
from atira_agent.telemetry import Redactor, Telemetry


@pytest.fixture
def telemetry(tmp_path):
    value = Telemetry(tmp_path / "trace", Redactor(), console=False)
    yield value
    value.close()


@pytest.fixture
def ledger(telemetry):
    value = EvidenceLedger(telemetry)
    value.observe(Observation(id="fixture", action_id=0, tab=0, url="http://synthetic.test",
                              title="Synthetic fixture", text="Synthetic records explicitly supplied for testing."))
    value.cite("fixture", "Synthetic records explicitly supplied for testing.")
    return value


def synthetic_records():
    evidence = ["e1"]
    attributes = dict(bore_mm="40", stroke_mm="120", pressure_bar="160", mounting="flange", certification="CERT-SYN")
    meta = dict(reference="TEST-RFQ", sent_at="2026-01-05T10:00:00Z", evidence=evidence)
    records = [
        ("tender", dict(id="t", evidence=evidence, reference="TEST-RFQ", scenario_date="2026-01-10T12:00:00Z",
                        mailbox_domain="synthetic.test", position_ids=["A", "B"], quantities_complete=True,
                        qa_complete=True, approvals_complete=True, commercial_rules_complete=True, bonus_rules_complete=True)),
        ("revision", dict(id="rev", evidence=evidence, revision="CURRENT", current=True, full=True)),
        ("requirement", dict(id="req", evidence=evidence, requirement_id="R", revision="CURRENT", catalogue_group="GROUP-SYN",
                             attributes=attributes, stroke_mode="nominal")),
        ("material", dict(id="mat", evidence=evidence, material_number="SYN-M", catalogue_group="GROUP-SYN", active=True,
                          attributes=attributes, stock=7, stock_weeks=1, production_weeks=6, carton_size=4,
                          surcharge_kind="fixed_per_kg", mass_kg="0.7", fixed_rate_eur_per_kg="2",
                          ordinary_setup_eur="2", allocation_mass_kg="0.4")),
        ("search", dict(id="search", evidence=evidence, requirement_id="R", revision="CURRENT", catalogue_group="GROUP-SYN",
                        complete=True, candidate_materials=["SYN-M"])),
        ("price", dict(id="price", evidence=evidence, material_number="SYN-M", valid_from="2026-01-01T00:00:00Z",
                       valid_to="2026-12-31T23:59:59Z", currency="USD", price_unit="10", fx_key="FX-SYN",
                       scales=[dict(min_quantity=1, amount="100.05")])),
        ("fx", dict(id="fx", **meta, sender="finanzen@synthetic.test", subject="Devisenfixing TEST-RFQ",
                    key="FX-SYN", currency="USD", eur_per_unit="1")),
        ("packaging", dict(id="pack", **meta, sender="logistik@synthetic.test", subject="Verpackungstarife TEST-RFQ",
                           key="PACK-SYN", carton_fee_eur="2")),
        ("pool", dict(id="pool", **meta, sender="kalkulation@synthetic.test", subject="Rüstpools TEST-RFQ",
                      key="POOL-SYN", fee_eur="5", allocation="largest_remainder", tie_order="position_ascending")),
        ("bonus", dict(id="bonus", **meta, sender="finanzen@synthetic.test", subject="Projektbonus TEST-RFQ",
                       eligible_positions=["A", "B"], bands=[dict(upper_eur="50", percent="2"), dict(upper_eur=None, percent="4")])),
        ("discount", dict(id="disc", **meta, sender="leitung@synthetic.test", subject="Approval TEST-RFQ", percent="10",
                          minimum_base_goods_eur="80")),
    ]
    for pos, qty in (("A", 3), ("B", 5)):
        records.append(("position", dict(id=pos, evidence=evidence, position=pos, requirement_id="R", quantity=qty,
                                         unit="pieces", packaging_key="PACK-SYN", pool_keys=["POOL-SYN"])))
    return records


@pytest.fixture
def priced_ledger(ledger):
    for kind, data in synthetic_records():
        ledger.record(kind, data)
    return ledger
