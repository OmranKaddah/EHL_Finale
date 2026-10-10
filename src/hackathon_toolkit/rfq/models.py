"""Normalized, evidence-backed calculator inputs. Monetary values use decimal strings."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
Percent = Annotated[Decimal, Field(ge=0, le=100, allow_inf_nan=False)]
Pieces = Annotated[int, Field(gt=0, le=9007199254740991, strict=True)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Attributes(Model):
    bore_mm: Positive
    stroke_mm: Positive
    pressure_bar: Positive
    mounting: str = Field(min_length=1)
    certification: str = Field(min_length=1)


class Scale(Model):
    minimum_pieces: int = Field(ge=0, strict=True)
    price: Money


class PriceCondition(Model):
    valid_from: date
    valid_until: date
    currency: str = Field(min_length=3, max_length=3)
    price_unit_pieces: Pieces
    eur_per_currency: Positive
    scales: list[Scale] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent(self):
        if self.valid_from > self.valid_until:
            raise ValueError("Reversed price validity window")
        if len({s.minimum_pieces for s in self.scales}) != len(self.scales):
            raise ValueError("Duplicate price scale thresholds")
        if self.currency == "EUR" and self.eur_per_currency != 1:
            raise ValueError("EUR conversion rate must be 1")
        return self


class Material(Model):
    number: str = Field(min_length=1, max_length=50)
    active: bool
    attributes: Attributes
    stock_pieces: int = Field(ge=0, strict=True)
    stock_weeks: int = Field(ge=0, strict=True)
    production_weeks: int = Field(ge=0, strict=True)
    carton_pieces: Pieces
    surcharge_mass_kg: Money
    allocation_mass_kg: Positive
    conditions: list[PriceCondition] = Field(min_length=1)


class Commitment(Model):
    material_number: str
    ceiling_pieces: int = Field(ge=0, strict=True)
    weeks: int = Field(ge=0, strict=True)


class Position(Model):
    position: str = Field(min_length=1, max_length=20)
    quantity: Pieces  # Final pieces after clarification, withdrawal and set conversion.
    requirement: Attributes  # Current revision + scoped amendments + stroke reserve.
    catalogue_complete: bool  # False is unresolved, NEVER evidence for no_bid.
    candidates: list[Material]
    discount_scope: Literal["base", "base_and_mass", "none"]
    metal_eur_per_kg: Money
    ordinary_setup_eur: Money
    carton_eur: Money
    commitment: Commitment | None
    evidence_ids: list[str] = Field(min_length=1)


class Discount(Model):
    percent: Percent
    minimum_goods_eur: Money | None
    evidence_ids: list[str] = Field(min_length=1)


class SetupPool(Model):
    key: str
    positions: list[str] = Field(min_length=1)
    fee_eur: Money
    # Must be read from the mail, not assumed from the project-bonus rule.
    allocation: Literal["largest_remainder"]
    evidence_ids: list[str] = Field(min_length=1)


class BonusBand(Model):
    up_to_eur: Positive | None  # Cumulative upper bound; None is unbounded.
    percent: Percent


class ProjectBonus(Model):
    positions: list[str] = Field(min_length=1)
    bands: list[BonusBand] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self):
        previous = Decimal(0)
        for i, band in enumerate(self.bands):
            if band.up_to_eur is None:
                if i != len(self.bands) - 1:
                    raise ValueError("Unbounded bonus band must be last")
            elif band.up_to_eur <= previous:
                raise ValueError("Bonus bounds must strictly increase")
            else:
                previous = band.up_to_eur
        return self


class BidInput(Model):
    tender_reference: str = Field(min_length=1, max_length=100)
    scenario_date: date
    positions: list[Position] = Field(min_length=1, max_length=100)
    discount: Discount
    setup_pools: list[SetupPool]
    bonus: ProjectBonus | None
    evidence_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_members(self):
        ids = [p.position for p in self.positions]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate position identifiers")
        if len({p.key for p in self.setup_pools}) != len(self.setup_pools):
            raise ValueError("Duplicate setup pool keys")
        for group in [*self.setup_pools, *([self.bonus] if self.bonus else [])]:
            if len(set(group.positions)) != len(group.positions) or not set(group.positions) <= set(ids):
                raise ValueError("Duplicate or unknown allocation member")
        return self
