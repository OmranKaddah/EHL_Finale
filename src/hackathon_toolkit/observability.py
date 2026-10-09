from __future__ import annotations

from decimal import Decimal


def estimate_cost_usd(*, input_tokens: int = 0, output_tokens: int = 0,
                      input_per_million_usd: Decimal, output_per_million_usd: Decimal) -> Decimal:
    """Calculate cost from measured tokens and caller-supplied current prices."""
    if min(input_tokens, output_tokens) < 0 or min(input_per_million_usd, output_per_million_usd) < 0:
        raise ValueError("tokens and rates must be nonnegative")
    return ((Decimal(input_tokens) * input_per_million_usd) +
            (Decimal(output_tokens) * output_per_million_usd)) / Decimal(1_000_000)
