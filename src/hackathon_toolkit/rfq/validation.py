"""Independent arithmetic and provenance checks; never discovers business facts."""
from decimal import Decimal, ROUND_HALF_UP

from .browser import same_origin


def check_answer(answer, schema):
    import jsonschema
    jsonschema.validate(answer, schema)
    positions = answer.get("positions", [])
    keys = [row["position"] for row in positions]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate bid positions")
    total = sum((Decimal(str(row["quantity"])) * Decimal(str(row["unit_price"]))
                 for row in positions), Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if total != Decimal(str(answer["total_net"])):
        raise ValueError("Independent quantity × unit price total disagrees")
    if answer["decision"] == "no_bid" and (positions or total):
        raise ValueError("No-bid must have no positions and zero total")


def tender_observation(book, observation_id, submission_url, quote):
    observation = book.observations[observation_id]
    if not same_origin(observation["url"], submission_url):
        raise ValueError("Evidence must come from the tender submission site")
    if not quote.strip() or quote not in observation["text"]:
        raise ValueError("Evidence must quote an observed confirmation exactly")
    return observation
