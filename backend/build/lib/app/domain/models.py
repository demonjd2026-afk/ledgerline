"""SQLAlchemy models. Postgres-first; JSONB/timestamptz semantics assumed."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- ingestion


class WebhookInbox(Base):
    """Every webhook we ever received, verified or not. Forensics and replay."""

    __tablename__ = "webhook_inbox"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    paypal_event_id: Mapped[str] = mapped_column(String(64), unique=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(16), default="received")  # received|verified|rejected|processed
    headers: Mapped[dict] = mapped_column(JSONB)
    body: Mapped[dict] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Job(Base):
    """Minimal durable queue. Workers claim with FOR UPDATE SKIP LOCKED."""

    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("kind", "dedupe_key", name="uq_jobs_kind_dedupe"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|running|done|failed|dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- ledger


class LedgerEventRow(Base):
    __tablename__ = "ledger_events"
    __table_args__ = (
        Index("ix_ledger_corr", "correlation_id"),
        Index("ix_ledger_resource", "resource_type", "resource_id"),
        Index("ix_ledger_occurred", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(200), unique=True)
    source: Mapped[str] = mapped_column(String(16))
    event_type: Mapped[str] = mapped_column(String(40))
    resource_type: Mapped[str] = mapped_column(String(24))
    resource_id: Mapped[str] = mapped_column(String(80))
    correlation_id: Mapped[str | None] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    payload: Mapped[dict] = mapped_column(JSONB)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(24))
    intent: Mapped[str | None] = mapped_column(String(16))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    payer_email: Mapped[str | None] = mapped_column(String(200))
    payer_id: Mapped[str | None] = mapped_column(String(40))
    custom_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[int] = mapped_column(BigInteger)


class Capture(Base):
    __tablename__ = "captures"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    order_id: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(24))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    fee_minor: Mapped[int | None] = mapped_column(BigInteger)
    net_minor: Mapped[int | None] = mapped_column(BigInteger)
    final_capture: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[int] = mapped_column(BigInteger)
    # Reconciliation helpers
    api_status: Mapped[str | None] = mapped_column(String(24))  # last status seen from a direct API/poll read
    api_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    settled_tx_id: Mapped[str | None] = mapped_column(String(80))


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    capture_id: Mapped[str | None] = mapped_column(String(80), index=True)
    order_id: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(24))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[int] = mapped_column(BigInteger)


class Authorization(Base):
    __tablename__ = "authorizations"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    order_id: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(24))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[int] = mapped_column(BigInteger)


class PayoutItem(Base):
    __tablename__ = "payout_items"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    batch_id: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(24))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    fee_minor: Mapped[int | None] = mapped_column(BigInteger)
    receiver: Mapped[str | None] = mapped_column(String(200))
    sender_item_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[int] = mapped_column(BigInteger)


class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    transaction_id: Mapped[str | None] = mapped_column(String(80), index=True)
    order_id: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(String(60))
    stage: Mapped[str | None] = mapped_column(String(40))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    seller_response_due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[int] = mapped_column(BigInteger)


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    invoice_number: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(24))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    recipient_email: Mapped[str | None] = mapped_column(String(200))
    paid_amount_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[int] = mapped_column(BigInteger)


class Transaction(Base):
    """Rows from the Transaction Search (reporting) API — the second source of truth."""

    __tablename__ = "transactions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)  # transaction_id
    event_code: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str | None] = mapped_column(String(4))  # D|P|S|V
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    fee_minor: Mapped[int | None] = mapped_column(BigInteger)
    paypal_reference_id: Mapped[str | None] = mapped_column(String(80), index=True)
    initiated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[int] = mapped_column(BigInteger)


# ---------------------------------------------------------------- recon + agents


class Break(Base):
    __tablename__ = "breaks"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(200), unique=True)
    rule: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(10))  # info|warn|critical
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)  # open|in_progress|awaiting_approval|resolved|dismissed
    resource_type: Mapped[str] = mapped_column(String(24))
    resource_id: Mapped[str] = mapped_column(String(80))
    correlation_id: Mapped[str | None] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200))
    expected: Mapped[dict] = mapped_column(JSONB, default=dict)
    observed: Mapped[dict] = mapped_column(JSONB, default=dict)
    delta_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[dict | None] = mapped_column(JSONB)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    break_id: Mapped[int] = mapped_column(BigInteger, index=True)
    thread_id: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)  # running|awaiting_approval|executed|declined|failed|closed
    specialist: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(80))
    trace: Mapped[list] = mapped_column(JSONB, default=list)  # ordered steps: node, tool calls, outputs
    proposal: Mapped[dict | None] = mapped_column(JSONB)
    outcome: Mapped[dict | None] = mapped_column(JSONB)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_run_id: Mapped[int] = mapped_column(BigInteger, index=True)
    break_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(40))  # refund|provide_evidence|ledger_correction|escalate|no_action
    proposal: Mapped[dict] = mapped_column(JSONB)
    policy_version: Mapped[int] = mapped_column(Integer)
    policy_decision: Mapped[str] = mapped_column(String(16))  # auto|requires_human|forbidden
    policy_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|approved|declined|executed|failed
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    execution_result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
