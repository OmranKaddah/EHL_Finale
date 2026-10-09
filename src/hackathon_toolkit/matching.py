from __future__ import annotations

from enum import Enum
from typing import Any
import re

from pydantic import BaseModel, Field
from functools import lru_cache


@lru_cache(maxsize=1)
def _unit_registry():
    try:
        from pint import UnitRegistry
    except ImportError as exc:
        raise ImportError("Unit conversion requires hackathon-toolkit[matching]") from exc
    return UnitRegistry(autoconvert_offset_to_baseunit=True)


class Outcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class Constraint(BaseModel):
    attribute: str
    operator: str
    value: Any
    unit: str | None = None
    mandatory: bool = True
    weight: float = Field(default=1, gt=0)
    evidence: str | None = None


class Specification(BaseModel):
    value: Any
    unit: str | None = None
    evidence: str | None = None


class Match(BaseModel):
    constraint: Constraint
    outcome: Outcome
    actual: Specification | None = None
    explanation: str


class MatchReport(BaseModel):
    matches: list[Match]
    overall: Outcome
    optional_score: float | None = None


def _compare(constraint: Constraint, actual: Specification, hierarchy: dict[str, list[str]]) -> bool:
    expected, observed = constraint.value, actual.value
    op = constraint.operator.lower()
    if op in {"in", "not_in", "contains", "not_contains"}:
        if op == "in": return observed in expected
        if op == "not_in": return observed not in expected
        if op == "contains": return expected in observed
        return expected not in observed
    if op in {"eq", "ne", "model"}:
        same = observed == expected
        return same if op != "ne" else not same
    if op == "or_better":
        if observed == expected:
            return True
        if str(expected) not in hierarchy:
            raise ValueError("or_better requires an explicit product hierarchy")
        return observed in hierarchy[str(expected)]
    if op == "bool":
        return observed is expected
    if op in {"gt", "gte", "lt", "lte", "range"}:
        if isinstance(observed, bool) or not isinstance(observed, (int, float)):
            raise ValueError("numeric comparison requires numeric specification")
        if constraint.unit or actual.unit:
            if not constraint.unit or not actual.unit:
                raise ValueError("both values need units")
            units = _unit_registry()
            try:
                observed = (units.Quantity(observed, actual.unit)).to(constraint.unit).magnitude
            except Exception as exc:
                raise ValueError("incompatible or invalid units") from exc
        if op == "range":
            if not isinstance(expected, (list, tuple)) or len(expected) != 2:
                raise ValueError("range requires [minimum, maximum]")
            return float(expected[0]) <= observed <= float(expected[1])
        if isinstance(expected, bool) or not isinstance(expected, (int, float)):
            raise ValueError("numeric comparison requires numeric constraint")
        return {"gt": observed > expected, "gte": observed >= expected,
                "lt": observed < expected, "lte": observed <= expected}[op]
    raise ValueError(f"unknown operator: {op}")


def match_requirements(requirements: list[Constraint], specifications: dict[str, Specification | list[Specification]],
                       *, hierarchy: dict[str, list[str]] | None = None) -> MatchReport:
    matches: list[Match] = []
    for requirement in requirements:
        observed = specifications.get(requirement.attribute)
        if observed is None:
            matches.append(Match(constraint=requirement, outcome=Outcome.UNKNOWN, explanation="No specification supplied"))
            continue
        values = observed if isinstance(observed, list) else [observed]
        try:
            outcomes = [_compare(requirement, value, hierarchy or {}) for value in values]
            if len(set(outcomes)) > 1:
                outcome = Outcome.CONFLICT
                explanation = "Supplied specifications disagree"
            else:
                outcome = Outcome.PASS if outcomes[0] else Outcome.FAIL
                explanation = f"Deterministic {requirement.operator} comparison"
        except (ValueError, TypeError) as exc:
            outcome, explanation = Outcome.UNKNOWN, str(exc)
        matches.append(Match(constraint=requirement, outcome=outcome, actual=values[0], explanation=explanation))
    mandatory = [m for m in matches if m.constraint.mandatory]
    if any(m.outcome == Outcome.CONFLICT for m in mandatory): overall = Outcome.CONFLICT
    elif any(m.outcome == Outcome.FAIL for m in mandatory): overall = Outcome.FAIL
    elif any(m.outcome == Outcome.UNKNOWN for m in mandatory): overall = Outcome.UNKNOWN
    else: overall = Outcome.PASS
    optional = [m for m in matches if not m.constraint.mandatory and m.outcome in {Outcome.PASS, Outcome.FAIL}]
    score = (sum(m.constraint.weight for m in optional if m.outcome == Outcome.PASS) /
             sum(m.constraint.weight for m in optional)) if optional else None
    return MatchReport(matches=matches, overall=overall, optional_score=score)


def normalize_requirement(text: str, attribute: str, *, mandatory: bool = True) -> Constraint:
    """Normalize a small explicit phrase set. Ambiguous language must be reviewed or LLM-normalized."""
    phrase = text.strip()
    number = r"(-?\d+(?:\.\d+)?)"
    unit = r"\s*([A-Za-z°/]+)?"
    match = re.search(rf"between\s+{number}\s+and\s+{number}{unit}", phrase, re.I)
    if match:
        return Constraint(attribute=attribute, operator="range", value=[float(match[1]), float(match[2])],
                          unit=match[3], mandatory=mandatory, evidence=phrase)
    for prefix, operator in (("at least", "gte"), ("no more than", "lte"),
                             ("must not exceed", "lte"), ("at most", "lte"),
                             ("more than", "gt"), ("less than", "lt")):
        match = re.search(rf"{prefix}\s+{number}{unit}", phrase, re.I)
        if match:
            return Constraint(attribute=attribute, operator=operator, value=float(match[1]),
                              unit=match[2], mandatory=mandatory, evidence=phrase)
    match = re.search(r"must not contain\s+(.+?)[.!]?\s*$", phrase, re.I)
    if match:
        return Constraint(attribute=attribute, operator="not_contains", value=match[1],
                          mandatory=mandatory, evidence=phrase)
    match = re.search(r"preferably supports?\s+(.+?)[.!]?\s*$", phrase, re.I)
    if match:
        return Constraint(attribute=attribute, operator="contains", value=match[1],
                          mandatory=False, evidence=phrase)
    match = re.search(r"(?:must include\s+)?(.+?)\s+or better[.!]?\s*$", phrase, re.I)
    if match:
        return Constraint(attribute=attribute, operator="or_better", value=match[1],
                          mandatory=mandatory, evidence=phrase)
    raise ValueError("requirement wording is ambiguous; supply a structured constraint")
