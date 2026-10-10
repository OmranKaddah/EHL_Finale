"""Helpers for records the model has selected and normalized; no network access."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from .models import Attributes


def timestamp(value: str) -> datetime:
    """Date-only records sort at UTC midnight; timestamps must include an offset."""
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value), datetime.min.time(), timezone.utc)
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Record timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def latest(records: list[dict]) -> dict | None:
    if not records:
        return None
    newest = max(timestamp(r["dated"]) for r in records)
    chosen = [r for r in records if timestamp(r["dated"]) == newest]
    if len(chosen) != 1:
        raise ValueError("Ambiguous records with the same latest timestamp")
    return chosen[0]


def authorized_record(records: list[dict], reference: str, sender: str, topic: str,
                      scenario_date: str, key: str | None = None) -> dict | None:
    """Exact reference/topic/key, case-insensitive full sender, no future records.

    The caller derives the authorized full sender from the brief and bidder domain.
    Latest selection happens BEFORE evaluating quantity or value conditions.
    """
    cutoff = date.fromisoformat(scenario_date)
    return latest([r for r in records if r["reference"] == reference
                   and r["sender"].casefold() == sender.casefold() and r["topic"] == topic
                   and (key is None or r.get("key") == key)
                   and timestamp(r["dated"]).date() <= cutoff])


def final_quantity(original: int, unit: str, pieces_per_set: int, position: str,
                   answers: list[dict], scenario_date: str) -> int:
    """Withdrawals remove referenced changes; newest remaining quantity change wins."""
    if type(original) is not int or original <= 0 or type(pieces_per_set) is not int or pieces_per_set <= 0:
        raise ValueError("Quantities and set factors must be positive integers")
    valid = [r for r in answers if timestamp(r["dated"]).date() <= date.fromisoformat(scenario_date)]
    ids = [r["number"] for r in valid]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate Q&A answer numbers")
    indexed = {r["number"]: r for r in valid}
    withdrawn = set()
    for row in valid:
        for number in row.get("withdraws", []):
            if number not in indexed or timestamp(indexed[number]["dated"]) >= timestamp(row["dated"]):
                raise ValueError("Withdrawal must name an earlier observed answer")
            if indexed[number].get("withdraws"):
                raise ValueError("Withdrawal of a withdrawal requires manual rule interpretation")
            withdrawn.add(number)
    change = latest([r for r in valid if r["number"] not in withdrawn
                     and r.get("position") == position and "quantity" in r])
    quantity = original if change is None else change["quantity"]
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("Final quantity must be a positive integer")
    if unit not in {"Stück", "Satz"}:
        raise ValueError("Normalize the observed unit to Stück or Satz")
    return quantity * (pieces_per_set if unit == "Satz" else 1)


def amended_requirement(attributes: dict, revision: str, requirement: str, amendments: list[dict],
                        scenario_date: str, usable_stroke: bool, reserve_per_end_mm: str | None) -> dict:
    """Apply amendments per attribute only to the governing revision, then derive stroke."""
    output = Attributes.model_validate(attributes).model_dump()
    applicable = [r for r in amendments if r["revision"] == revision and r["requirement"] == requirement
                  and timestamp(r["dated"]).date() <= date.fromisoformat(scenario_date)]
    for row in applicable:
        if not set(row["changes"]) <= set(output):
            raise ValueError("Unknown amended attribute")
    for key in output:
        row = latest([r for r in applicable if key in r["changes"]])
        if row:
            output[key] = row["changes"][key]
    if usable_stroke:
        if reserve_per_end_mm is None:
            raise ValueError("Usable stroke requires revision-specific technical reserve")
        reserve = Decimal(reserve_per_end_mm)
        if not reserve.is_finite() or reserve < 0:
            raise ValueError("Invalid per-end reserve")
        output["stroke_mm"] = Decimal(str(output["stroke_mm"])) + 2 * reserve
    return Attributes.model_validate(output).model_dump(mode="json")


def window_rate(windows: list[dict], scenario_date: str) -> str:
    day = date.fromisoformat(scenario_date)
    selected = [r for r in windows if date.fromisoformat(r["valid_from"]) <= day
                <= date.fromisoformat(r["valid_until"])]
    if len(selected) != 1:
        raise ValueError("Expected exactly one applicable index validity window")
    value = Decimal(str(selected[0]["rate"]))
    if not value.is_finite() or value < 0:
        raise ValueError("Invalid index rate")
    return str(value)


RESOLVERS = {"authorized_record": authorized_record, "final_quantity": final_quantity,
             "amended_requirement": amended_requirement, "window_rate": window_rate}
