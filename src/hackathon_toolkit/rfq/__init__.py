"""RFQ challenge agent and deterministic business rules (optional browser dependencies)."""

from .pricing import calculate_bid
from .models import BidInput

__all__ = ["BidInput", "calculate_bid"]
