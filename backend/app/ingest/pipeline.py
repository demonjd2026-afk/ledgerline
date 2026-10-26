"""The processing pipeline every job runs: normalise -> append -> enrich -> reconcile -> dispatch."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.events import EventType, LedgerEvent, ResourceType, correlation_from_resource, normalise_webhook, parse_ts
from app.domain.models import Capture, Dispute, Order, WebhookInbox
from app.domain.money import Money
from app.ledger import store
from app.logging import get_logger
from app.paypal.client import PayPalClient, PayPalError
from app.recon.engine import reconcile
from app.worker import queue

log = get_logger("pipeline")


def process_webhook(session: Session, payload: dict[str, Any], paypal: PayPalClient | None) -> None:
    inbox = session.get(WebhookInbox, payload["inbox_id"])
    if inbox is None or inbox.status == "processed":
        return
    ev = normalise_webhook(inbox.body)
    if ev is None:
        inbox.status = "processed"
        inbox.error = "unmapped event type"
        return
    ingest_event(session, ev, paypal)
    inbox.status = "processed"


def ingest_event(session: Session, ev: LedgerEvent, paypal: PayPalClient | None) -> None:
    """Append one event, then make the chain consistent and reconcile it."""
    row, inserted = store.append(session, ev)
    if row is None:
        return
    if inserted:
        _enrich(session, ev, paypal)
    corr = ev.correlation_id or (ev.resource_id if ev.resource_type == ResourceType.ORDER else None)
    if ev.resource_type == ResourceType.DISPUTE and corr:
        # A dispute correlates by transaction (capture) id; resolve it to the order when we can.
        cap = session.get(Capture, corr)
        if cap and cap.order_id:
            corr = cap.order_id
            d = session.get(Dispute, ev.resource_id)
            if d is not None:
                d.order_id = corr
    new_breaks = reconcile(session, correlation_id=corr, resource=(str(ev.resource_type), ev.resource_id))
    for b in new_breaks:
        if b.severity in ("critical", "warn"):
            queue.enqueue(session, "run_agent", dedupe_key=f"break:{b.id}", payload={"break_id": b.id})


def _enrich(session: Session, ev: LedgerEvent, paypal: PayPalClient | None) -> None:
    """Fetch the parent order when a capture/refund arrives for an order we have never seen."""
    if paypal is None or not get_settings().paypal_configured:
        return
    if ev.resource_type in (ResourceType.CAPTURE, ResourceType.REFUND, ResourceType.AUTHORIZATION) and ev.correlation_id:
        if session.get(Order, ev.correlation_id) is None:
            fetch_order(session, ev.correlation_id, paypal)
    if ev.resource_type == ResourceType.REFUND:
        cap_id = (ev.payload.get("supplementary_data") or {}).get("related_ids", {}).get("capture_id")
        if cap_id and session.get(Capture, cap_id) is None:
            fetch_capture(session, cap_id, paypal)


def fetch_order(session: Session, order_id: str, paypal: PayPalClient) -> bool:
    try:
        order = paypal.get_order(order_id)
    except PayPalError as exc:
        log.warning("enrich.order_missing", order_id=order_id, status=exc.status)
        return False
    pu = (order.get("purchase_units") or [{}])[0]
    ev = LedgerEvent(
        event_key=LedgerEvent.key("api", order_id, f"ORDER_SNAPSHOT_{order.get('status')}"),
        source="api",
        event_type=_order_status_event(order.get("status")),
        resource_type=ResourceType.ORDER,
        resource_id=order_id,
        occurred_at=parse_ts(order.get("update_time") or order.get("create_time")),
        payload=order,
        amount=Money.from_paypal(pu.get("amount")),
        correlation_id=order_id,
    )
    store.append(session, ev)
    return True


def fetch_capture(session: Session, capture_id: str, paypal: PayPalClient) -> bool:
    try:
        cap = paypal.get_capture(capture_id)
    except PayPalError as exc:
        log.warning("enrich.capture_missing", capture_id=capture_id, status=exc.status)
        return False
    ev = LedgerEvent(
        event_key=LedgerEvent.key("api", capture_id, f"CAPTURE_SNAPSHOT_{cap.get('status')}_{cap.get('update_time','')}"),
        source="api",
        event_type={
            "COMPLETED": EventType.CAPTURE_COMPLETED,
            "REFUNDED": EventType.CAPTURE_REFUNDED,
            "PARTIALLY_REFUNDED": EventType.CAPTURE_REFUNDED,
            "DECLINED": EventType.CAPTURE_DENIED,
        }.get(cap.get("status"), EventType.CAPTURE_PENDING),
        resource_type=ResourceType.CAPTURE,
        resource_id=capture_id,
        occurred_at=parse_ts(cap.get("update_time") or cap.get("create_time")),
        payload=cap,
        amount=Money.from_paypal(cap.get("amount")),
        correlation_id=correlation_from_resource(ResourceType.CAPTURE, cap),
    )
    store.append(session, ev)
    return True


def _order_status_event(status: str | None) -> EventType:
    return {
        "CREATED": EventType.ORDER_CREATED,
        "SAVED": EventType.ORDER_CREATED,
        "APPROVED": EventType.ORDER_APPROVED,
        "PAYER_ACTION_REQUIRED": EventType.ORDER_CREATED,
        "COMPLETED": EventType.ORDER_COMPLETED,
    }.get(status or "", EventType.ORDER_CREATED)


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)
