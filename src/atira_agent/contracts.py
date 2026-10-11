"""Validated runtime, navigation and evidence contracts (no scenario defaults)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SiteAccess(BaseModel):
    siteId: str
    url: str
    credentials: dict[str, str] = Field(default_factory=dict, repr=False)


class SubmissionTarget(BaseModel):
    kind: Literal["site", "api"]
    url: str
    siteId: str | None = None


class RunContext(BaseModel):
    run_id: str = "local-scouting"
    challenge_id: str
    brief: str = Field(repr=False)
    access: list[SiteAccess]
    submission: SubmissionTarget
    answer_schema: dict[str, Any]
    started_at: int | None = None
    expires_at: int | None = None
    kind: str = "scouting"
    llm_proxy_url: str | None = Field(default=None, repr=False)
    llm_providers: list[str] = Field(default_factory=list)
    spent_micro_usd: int = 0


class Observation(StrictModel):
    id: str
    action_id: int
    tab: int
    url: str
    title: str
    text: str
    controls: list[dict[str, Any]] = Field(default_factory=list)
    frames: list[dict[str, Any]] = Field(default_factory=list)
    tabs: list[dict[str, Any]] = Field(default_factory=list)
    dialog: dict[str, Any] | None = None
    documents: list[dict[str, Any]] = Field(default_factory=list)
    screenshot: str | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InspectionCitation(StrictModel):
    """An exact, durable excerpt made available after a transient UI inspection."""

    observation: str
    excerpt: str = Field(min_length=3, max_length=1200)


class InspectionResult(StrictModel):
    """Evidence preserved for one model-selected disclosure or tooltip control.

    The browser reports what changed and where it was visibly observed.  It
    deliberately does not interpret the row as a particular tender fact.
    """

    clicked_ref: str
    control_label: str
    control_context: str | None = None
    before_observation: str
    after_observation: str
    revealed_text: str = ""
    citation_candidates: list[InspectionCitation] = Field(default_factory=list)
    dialog: dict[str, Any] | None = None


class AgentAction(StrictModel):
    action: Literal[
        "navigate", "click", "fill", "select", "check", "press", "scroll", "tab", "frame",
        "observe", "wait", "screenshot", "pixel_click", "drag", "dialog", "document", "cite", "record",
        "schema", "calculate", "prepare_submission", "fill_answer", "request_tan", "capture_tan",
        "review_submission", "sign", "receipt", "api_submit", "stage", "inspect_evidence", "inspect_controls", "read_links",
    ]
    summary: str = Field(max_length=500, description="Brief observable purpose; no private reasoning.")
    args: dict[str, Any] = Field(default_factory=dict)


class EvidenceFact(StrictModel):
    id: str
    observation_id: str
    website: str
    url: str
    title: str
    excerpt: str
    action_id: int
    observed_at: datetime
    scope: dict[str, str] = Field(default_factory=dict)
    confidence: Literal["observed", "verified"] = "observed"


class Sourced(StrictModel):
    id: str
    evidence: list[str] = Field(min_length=1)


NonNegative = Annotated[Decimal, Field(ge=0)]
Positive = Annotated[Decimal, Field(gt=0)]


class Tender(Sourced):
    reference: str
    scenario_date: datetime
    mailbox_domain: str
    position_ids: list[str] = Field(min_length=1)
    quantities_complete: bool
    qa_complete: bool
    # Completeness is an explicit extraction claim, never an inferred empty list.
    approvals_complete: bool
    commercial_rules_complete: bool
    bonus_rules_complete: bool

    @field_validator("scenario_date")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("scenario_date must include its documented timezone")
        return value


class Position(Sourced):
    position: str
    requirement_id: str
    quantity: int = Field(gt=0)
    unit: Literal["pieces", "set"]
    commercial_key: str | None = None
    packaging_key: str | None = None
    commitment_key: str | None = None
    pool_keys: list[str] = Field(default_factory=list)
    ordinary_setup_eur: NonNegative | None = None
    bonus_plan: str | None = None


class Revision(Sourced):
    revision: str
    current: bool
    full: bool


class Engineering(StrictModel):
    bore_mm: Positive
    stroke_mm: Positive
    pressure_bar: Positive
    mounting: str
    certification: str


class Requirement(Sourced):
    requirement_id: str
    revision: str
    catalogue_group: str
    attributes: Engineering
    stroke_mode: Literal["nominal", "usable"]
    pieces_per_set: int | None = Field(default=None, gt=0)


class QA(Sourced):
    issued_at: datetime
    withdraws: list[str] = Field(default_factory=list, description="IDs of Q&A answers withdrawn")
    position: str | None = None
    quantity: int | None = Field(default=None, gt=0)
    unit: Literal["pieces", "set"] | None = None
    revision: str | None = None
    requirement_id: str | None = None
    amendments: dict[str, Any] = Field(default_factory=dict)
    commercial_key: str | None = None
    packaging_key: str | None = None
    commitment_key: str | None = None
    pool_keys: list[str] | None = None
    ordinary_setup_eur: NonNegative | None = None
    bonus_plan: str | None = None


class Material(Sourced):
    material_number: str
    catalogue_group: str
    active: bool
    attributes: Engineering
    stock: int = Field(ge=0)
    stock_weeks: int = Field(ge=0)
    production_weeks: int = Field(ge=0)
    carton_size: int | None = Field(default=None, gt=0)
    surcharge_kind: Literal["none", "fixed_per_kg", "index"]
    mass_kg: NonNegative | None = None
    fixed_rate_eur_per_kg: NonNegative | None = None
    metal_index_key: str | None = None
    ordinary_setup_eur: NonNegative | None = None
    allocation_mass_kg: NonNegative | None = None


class SearchConclusion(Sourced):
    requirement_id: str
    revision: str
    catalogue_group: str
    complete: bool
    candidate_materials: list[str]


class Scale(StrictModel):
    min_quantity: int = Field(ge=0)
    amount: NonNegative


class PriceCondition(Sourced):
    material_number: str
    valid_from: datetime
    valid_to: datetime
    currency: str
    price_unit: Positive
    fx_key: str | None = None
    scales: list[Scale] = Field(min_length=1)


class MailRule(Sourced):
    reference: str
    sender: str
    sent_at: datetime
    subject: str


class Discount(MailRule):
    percent: Decimal = Field(ge=0, le=100)
    minimum_base_goods_eur: NonNegative | None = None


class Technical(MailRule):
    revision: str
    requirement_id: str
    reserve_per_end_mm: NonNegative


class Commercial(MailRule):
    key: str
    discount_scope: Literal["base", "base_and_mass", "neither"]


class FX(MailRule):
    key: str
    currency: str
    eur_per_unit: Positive
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class Packaging(MailRule):
    key: str
    carton_fee_eur: NonNegative


class Commitment(MailRule):
    key: str
    material_number: str
    maximum_quantity: int = Field(ge=0)
    lead_time_weeks: int = Field(ge=0)


class Pool(MailRule):
    key: str
    fee_eur: NonNegative
    allocation: Literal["largest_remainder", "half_up_adjust_last", "floor_remainder_last"]
    tie_order: Literal["position_ascending"]


class Band(StrictModel):
    upper_eur: Positive | None
    percent: Decimal = Field(ge=0, le=100)


class Bonus(MailRule):
    key: str | None = None
    eligible_positions: list[str] = Field(default_factory=list)
    bands: list[Band] = Field(min_length=1)


class IndexRate(StrictModel):
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    eur_per_kg: NonNegative


class MetalIndex(MailRule):
    key: str
    rates: list[IndexRate] = Field(min_length=1)


RECORD_TYPES: dict[str, type[Sourced]] = {
    "tender": Tender, "position": Position, "revision": Revision, "requirement": Requirement,
    "qa": QA, "material": Material, "search": SearchConclusion, "price": PriceCondition,
    "discount": Discount, "technical": Technical, "commercial": Commercial, "fx": FX,
    "packaging": Packaging, "commitment": Commitment, "pool": Pool, "bonus": Bonus,
    "metal_index": MetalIndex,
}


class ResolvedTender(StrictModel):
    reference: str
    decision: Literal["bid", "no_bid", "unresolved"]
    lines: list[dict[str, Any]] = Field(default_factory=list)
    unresolved: dict[str, list[str]] = Field(default_factory=dict)
    missing_materials: list[str] = Field(default_factory=list)


class PricingResult(StrictModel):
    answer: dict[str, Any] | None
    omitted: list[str] = Field(default_factory=list)
    unresolved: dict[str, list[str]] = Field(default_factory=dict)
    audit: list[dict[str, Any]] = Field(default_factory=list)


class SubmissionState(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    TAN_REQUESTED = "tan_requested"
    SIGNING_ATTEMPTED = "signing_attempted"
    SCOUTING_ACKNOWLEDGED = "scouting_acknowledged"
    ACCEPTED = "accepted"
    FAILED = "failed"
