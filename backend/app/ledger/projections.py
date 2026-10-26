"""Deterministic projections from ledger events to read tables.

Each handler is a pure function of (current row, event). Replaying the same events
in order always yields the same tables, which is what makes ``rebuild`` safe.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.domain.events import EventType, ResourceType, parse_ts
from app.domain.models import (
    Authorization,
    Capture,
    Dispute,
    Invoice,
    LedgerEventRow,
    Order,
    PayoutItem,
    Refund,
    Transaction,
)
from app.domain.money import Money

PROJECTION_TABLES = [Order, Capture, Refund, Authorization, PayoutItem, Dispute, Invoice, Transaction]


def truncate_projections(session: Session) -> None:
    for model in PROJECTION_TABLES:
        session.execute(delete(model))


def _money(obj: dict | None) -> Money | None:
    return Money.from_paypal(obj) if obj else None


def _upsert(session: Session, model, pk: str, defaults: dict[str, Any], updates: dict[str, Any], ev: LedgerEventRow):
    row = session.get(model, pk)
    if row is None:
        init = {**defaults, **{k: v for k, v in updates.items() if v is not None}}
        row = model(id=pk, **init)
        row.created_at = ev.occurred_at
        row.updated_at = ev.occurred_at
        row.last_event_id = ev.id
        session.add(row)
        return row
    # Ignore out-of-order older events for status, but never lose a newer event id.
    if ev.occurred_at >= (row.updated_at or datetime.min.replace(tzinfo=timezone.utc)):
        for k, v in updates.items():
            if v is not None:
                setattr(row, k, v)
        row.updated_at = ev.occurred_at
    row.last_event_id = max(row.last_event_id or 0, ev.id)
    return row


def apply_event(session: Session, ev: LedgerEventRow) -> None:
    handler = _HANDLERS.get(ev.resource_type)
    if handler:
        handler(session, ev)


# ---------------------------------------------------------------- handlers


def _order(session: Session, ev: LedgerEventRow) -> None:
    p = ev.payload
    pu = (p.get("purchase_units") or [{}])[0]
    amt = _money(pu.get("amount")) or Money(ev.amount_minor or 0, ev.currency or "USD")
    payer = p.get("payer") or {}
    _upsert(
        session,
        Order,
        ev.resource_id,
        defaults={"amount_minor": amt.minor, "currency": amt.currency},
        updates={
            "status": p.get("status") or _status_from_event(ev.event_type),
            "intent": p.get("intent"),
            "amount_minor": amt.minor,
            "currency": amt.currency,
            "payer_email": payer.get("email_address"),
            "payer_id": payer.get("payer_id"),
            "custom_id": pu.get("custom_id"),
        },
        ev=ev,
    )
    # Orders embed captures/authorizations in payments; project those too.
    payments = pu.get("payments") or {}
    for cap in payments.get("captures") or []:
        _capture_from(session, ev, cap, order_id=ev.resource_id)
    for auth in payments.get("authorizations") or []:
        _auth_from(session, ev, auth, order_id=ev.resource_id)
    for ref in payments.get("refunds") or []:
        _refund_from(session, ev, ref, order_id=ev.resource_id)


def _capture_from(session: Session, ev: LedgerEventRow, cap: dict, order_id: str | None) -> None:
    amt = _money(cap.get("amount"))
    if amt is None:
        return
    sb = cap.get("seller_receivable_breakdown") or {}
    fee = _money(sb.get("paypal_fee"))
    net = _money(sb.get("net_amount"))
    updates: dict[str, Any] = {
        "order_id": order_id,
        "status": cap.get("status"),
        "amount_minor": amt.minor,
        "currency": amt.currency,
        "fee_minor": fee.minor if fee else None,
        "net_minor": net.minor if net else None,
        "final_capture": cap.get("final_capture", True),
    }
    if ev.source in ("api", "poll"):
        # PayPal's direct view lives in api_* columns. It does not overwrite the webhook-derived
        # status/amount of an existing row — the gap between the two is what WEBHOOK_API_DRIFT reports.
        updates["api_status"] = cap.get("status")
        updates["api_amount_minor"] = amt.minor
        if session.get(Capture, cap["id"]) is not None:
            updates.pop("status")
            updates.pop("amount_minor")
    elif ev.source == "correction":
        # A correction aligns the ledger with the API view it cites.
        updates["api_status"] = cap.get("status")
    _upsert(session, Capture, cap["id"], {"amount_minor": amt.minor, "currency": amt.currency, "status": cap.get("status") or "UNKNOWN"}, updates, ev)


def _capture(session: Session, ev: LedgerEventRow) -> None:
    p = ev.payload
    order_id = ev.correlation_id
    if ev.event_type == EventType.CAPTURE_REFUNDED and ev.source == "webhook" and p.get("id") and p.get("amount"):
        # The PAYMENT.CAPTURE.REFUNDED webhook carries the *refund* resource, not the capture.
        # An API/poll snapshot with the same label carries the capture itself (status REFUNDED).
        _refund_from(session, ev, p, order_id=order_id)
        return
    _capture_from(session, ev, p, order_id=order_id)


def _auth_from(session: Session, ev: LedgerEventRow, auth: dict, order_id: str | None) -> None:
    amt = _money(auth.get("amount"))
    if amt is None:
        return
    _upsert(
        session,
        Authorization,
        auth["id"],
        {"amount_minor": amt.minor, "currency": amt.currency, "status": auth.get("status") or "CREATED"},
        {"order_id": order_id, "status": auth.get("status"), "amount_minor": amt.minor, "currency": amt.currency},
        ev,
    )


def _authorization(session: Session, ev: LedgerEventRow) -> None:
    _auth_from(session, ev, ev.payload, order_id=ev.correlation_id)


def _refund_from(session: Session, ev: LedgerEventRow, ref: dict, order_id: str | None) -> None:
    amt = _money(ref.get("amount"))
    if amt is None or not ref.get("id"):
        return
    rel = (ref.get("supplementary_data") or {}).get("related_ids") or {}
    capture_id = rel.get("capture_id")
    if not capture_id:
        for link in ref.get("links") or []:
            if link.get("rel") == "up" and "/captures/" in link.get("href", ""):
                capture_id = link["href"].rsplit("/", 1)[-1]
    _upsert(
        session,
        Refund,
        ref["id"],
        {"amount_minor": amt.minor, "currency": amt.currency, "status": ref.get("status") or "PENDING"},
        {
            "capture_id": capture_id,
            "order_id": order_id or rel.get("order_id"),
            "status": ref.get("status"),
            "amount_minor": amt.minor,
            "currency": amt.currency,
        },
        ev,
    )


def _refund(session: Session, ev: LedgerEventRow) -> None:
    _refund_from(session, ev, ev.payload, order_id=ev.correlation_id)


def _payout_item(session: Session, ev: LedgerEventRow) -> None:
    p = ev.payload
    item = p.get("payout_item") or {}
    amt = _money(item.get("amount")) or Money(ev.amount_minor or 0, ev.currency or "USD")
    fee = _money(p.get("payout_item_fee"))
    _upsert(
        session,
        PayoutItem,
        ev.resource_id,
        {"amount_minor": amt.minor, "currency": amt.currency, "status": p.get("transaction_status") or "PENDING"},
        {
            "batch_id": p.get("payout_batch_id"),
            "status": p.get("transaction_status"),
            "amount_minor": amt.minor,
            "currency": amt.currency,
            "fee_minor": fee.minor if fee else None,
            "receiver": item.get("receiver"),
            "sender_item_id": item.get("sender_item_id"),
        },
        ev,
    )


def _payout_batch(session: Session, ev: LedgerEventRow) -> None:
    for it in ev.payload.get("items") or []:
        sub = LedgerEventRow(
            id=ev.id,
            event_key=ev.event_key,
            source=ev.source,
            event_type=ev.event_type,
            resource_type=ResourceType.PAYOUT_ITEM,
            resource_id=it.get("payout_item_id", ""),
            correlation_id=ev.correlation_id,
            occurred_at=ev.occurred_at,
            payload=it,
        )
        if sub.resource_id:
            _payout_item(session, sub)


def _dispute(session: Session, ev: LedgerEventRow) -> None:
    p = ev.payload
    amt = _money(p.get("dispute_amount"))
    fallback = Money(ev.amount_minor or 0, ev.currency or "USD")
    txs = p.get("disputed_transactions") or []
    tx_id = txs[0].get("seller_transaction_id") if txs else None
    due = p.get("seller_response_due_date")
    outcome = (p.get("dispute_outcome") or {}).get("outcome_code")
    _upsert(
        session,
        Dispute,
        ev.resource_id,
        {"amount_minor": (amt or fallback).minor, "currency": (amt or fallback).currency, "status": p.get("status") or "OPEN"},
        {
            "transaction_id": tx_id,
            "order_id": ev.correlation_id,
            "status": p.get("status"),
            "reason": p.get("reason"),
            "stage": p.get("dispute_life_cycle_stage"),
            "amount_minor": amt.minor if amt else None,
            "currency": amt.currency if amt else None,
            "seller_response_due": parse_ts(due) if due else None,
            "evidence_submitted": bool(p.get("evidences")) or None,
            "outcome": outcome,
        },
        ev,
    )


def _invoice(session: Session, ev: LedgerEventRow) -> None:
    p = ev.payload
    detail = p.get("detail") or {}
    amt = _money(p.get("amount")) or Money(ev.amount_minor or 0, ev.currency or "USD")
    paid = _money((p.get("payments") or {}).get("paid_amount"))
    recipients = p.get("primary_recipients") or []
    email = ((recipients[0].get("billing_info") or {}).get("email_address")) if recipients else None
    _upsert(
        session,
        Invoice,
        ev.resource_id,
        {"amount_minor": amt.minor, "currency": amt.currency, "status": p.get("status") or "DRAFT"},
        {
            "invoice_number": detail.get("invoice_number"),
            "status": p.get("status"),
            "amount_minor": amt.minor,
            "currency": amt.currency,
            "recipient_email": email,
            "paid_amount_minor": paid.minor if paid else None,
        },
        ev,
    )


def _transaction(session: Session, ev: LedgerEventRow) -> None:
    p = ev.payload
    info = p.get("transaction_info") or p
    amt = _money(info.get("transaction_amount")) or Money(ev.amount_minor or 0, ev.currency or "USD")
    fee = _money(info.get("fee_amount"))
    _upsert(
        session,
        Transaction,
        ev.resource_id,
        {"amount_minor": amt.minor, "currency": amt.currency, "initiated_at": ev.occurred_at},
        {
            "event_code": info.get("transaction_event_code"),
            "status": info.get("transaction_status"),
            "amount_minor": amt.minor,
            "currency": amt.currency,
            "fee_minor": fee.minor if fee else None,
            "paypal_reference_id": info.get("paypal_reference_id"),
            "initiated_at": parse_ts(info.get("transaction_initiation_date")) if info.get("transaction_initiation_date") else ev.occurred_at,
        },
        ev,
    )
    # Link the capture to its settled transaction if the ids match (PayPal reuses capture id as tx id).
    cap = session.get(Capture, ev.resource_id)
    if cap is not None:
        cap.settled_tx_id = ev.resource_id
        cap.api_status = cap.api_status or _tx_status_to_capture(info.get("transaction_status"))


def _tx_status_to_capture(code: str | None) -> str | None:
    return {"S": "COMPLETED", "P": "PENDING", "D": "DECLINED", "V": "REFUNDED"}.get(code or "")


def _status_from_event(event_type: str) -> str:
    return {
        EventType.ORDER_CREATED: "CREATED",
        EventType.ORDER_APPROVED: "APPROVED",
        EventType.ORDER_COMPLETED: "COMPLETED",
    }.get(event_type, "UNKNOWN")


_HANDLERS = {
    ResourceType.ORDER: _order,
    ResourceType.CAPTURE: _capture,
    ResourceType.AUTHORIZATION: _authorization,
    ResourceType.REFUND: _refund,
    ResourceType.PAYOUT_ITEM: _payout_item,
    ResourceType.PAYOUT_BATCH: _payout_batch,
    ResourceType.DISPUTE: _dispute,
    ResourceType.INVOICE: _invoice,
    ResourceType.TRANSACTION: _transaction,
}
