from decimal import Decimal

from hackathon_toolkit.observability import estimate_cost_usd


def test_cost_uses_measured_tokens_and_supplied_rates():
    assert estimate_cost_usd(input_tokens=1_000_000, output_tokens=500_000,
        input_per_million_usd=Decimal("1"), output_per_million_usd=Decimal("2")) == Decimal("2")
