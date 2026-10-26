"""Structured outputs the agents must produce. Prose is not an acceptable output."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _clip(text: str, limit: int) -> str:
    """Trim at a sentence or word boundary rather than rejecting the whole proposal."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "; ", ", ", " "):
        i = cut.rfind(sep)
        if i > limit * 0.5:
            return cut[: i + (1 if sep == ". " else 0)].rstrip() + ("" if sep == ". " else "…")
    return cut.rstrip() + "…"


class Triage(BaseModel):
    specialist: Literal["dispute_defender", "refund_advisor", "drift_explainer"]
    summary: str = Field(description="One sentence, plain language: what is wrong and why it matters")
    missing_evidence: list[str] = Field(default_factory=list, description="Facts you still need before proposing an action")
    confidence: float = Field(ge=0, le=1)

    @field_validator("summary", mode="before")
    @classmethod
    def _clip_summary(cls, v: str) -> str:
        return _clip(v, 240)


class EvidenceItem(BaseModel):
    evidence_type: Literal[
        "PROOF_OF_FULFILLMENT",
        "PROOF_OF_REFUND",
        "PROOF_OF_DELIVERY_SIGNATURE",
        "PROOF_OF_RECEIPT_COPY",
        "RETURN_POLICY",
        "BILLING_AGREEMENT",
        "PROOF_OF_RESHIPMENT",
        "ITEM_DESCRIPTION",
        "POLICE_REPORT",
        "AFFIDAVIT",
        "PAID_WITH_OTHER_METHOD",
        "COPY_OF_CONTRACT",
        "TERMINAL_ATM_RECEIPT",
        "PRICE_DIFFERENCE_REASON",
        "SOURCE_CONVERSION_RATE",
        "BANK_STATEMENT",
        "CREDIT_DUE_REASON",
        "REQUEST_CREDIT_RECEIPT",
        "PROOF_OF_RETURN",
        "CREATE",
        "CHANGE_REASON",
        "PROOF_OF_REFUND_OUTSIDE_PAYPAL",
        "RECEIPT_OF_MERCHANDISE",
        "CUSTOMS_DOCUMENT",
        "CUSTOMS_FEE_RECEIPT",
        "PROOF_OF_RIGHT_TO_RECEIVE",
        "OTHER",
    ]
    notes: str = Field(description="Factual, specific text. Reference order ids, dates and amounts from the ledger.")


class Proposal(BaseModel):
    action: Literal["refund", "provide_evidence", "ledger_correction", "no_action", "escalate"]
    headline: str = Field(description="One short sentence (under 140 characters) an operator reads first: the finding and the action, with the key id and amount")
    rationale: str = Field(description="Two to four sentences (under 600 characters) of supporting facts from the tools, ids and amounts exact. No restating the headline.")
    confidence: float = Field(ge=0, le=1)

    @field_validator("headline", mode="before")
    @classmethod
    def _clip_headline(cls, v: str) -> str:
        return _clip(v, 160)

    @field_validator("rationale", mode="before")
    @classmethod
    def _clip_rationale(cls, v: str) -> str:
        return _clip(v, 700)
    # refund
    capture_id: str | None = None
    order_id: str | None = None
    amount_minor: int | None = Field(default=None, description="Refund amount in minor units, computed from the ledger")
    currency: str | None = None
    note_to_payer: str | None = None
    # provide_evidence
    dispute_id: str | None = None
    evidences: list[EvidenceItem] = Field(default_factory=list)
    message_to_buyer: str | None = None
    # ledger_correction
    correction: dict | None = Field(default=None, description="Fields to set on the ledger projection, with the API value as source")
    # escalate
    escalation_summary: str | None = None
