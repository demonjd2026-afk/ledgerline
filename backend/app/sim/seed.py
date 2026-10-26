"""Seed a real PayPal sandbox with activity, then inject faults so reconciliation has work to do.

Everything created here is recorded in the ledger as if the webhook had arrived (``source=webhook``,
synthesised from the API response), which is what a merchant's ledger would hold. ``inject`` then
makes the two views diverge in realistic ways.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domain.events import EventType, LedgerEvent, ResourceType, parse_ts
from app.domain.money import Money, to_decimal_str
from app.ingest.pipeline import fetch_capture, ingest_event
from app.logging import get_logger
from app.paypal.client import PayPalClient, PayPalError
from app.recon.engine import reconcile
from app.worker import queue

log = get_logger("sim.seed")

TEST_CARD = {"number": "4111111111111111", "expiry": "2030-12", "name": "Sim Buyer", "security_code": "123",
             "billing_address": {"address_line_1": "1 Market St", "admin_area_2": "San Jose", "admin_area_1": "CA", "postal_code": "95131", "country_code": "US"}}
SKUS = [("Trail runner 42", 12900), ("Desk lamp", 6450), ("Headphones", 19900), ("Espresso machine", 34900), ("Yoga mat", 4500), ("Notebook set", 1850)]


def _rid() -> str:
    return str(uuid.uuid4())


def create_card_order(pp: PayPalClient, amount_minor: int, custom_id: str, currency: str = "USD") -> dict:
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{"custom_id": custom_id, "amount": {"currency_code": currency, "value": to_decimal_str(amount_minor, currency)}}],
        "payment_source": {"card": TEST_CARD},
    }
    order = pp.create_order(body, request_id=_rid())
    if order.get("status") != "COMPLETED":
        # Some sandbox apps require an explicit capture step for card orders.
        order = pp.capture_order(order["id"], request_id=_rid())
    return order


def record_order_as_webhook(session: Session, order: dict) -> None:
    """Synthesise the webhooks PayPal would have sent for this order."""
    pu = (order.get("purchase_units") or [{}])[0]
    ingest_event(
        session,
        LedgerEvent(
            event_key=LedgerEvent.key("webhook", f"SIM-{order['id']}", EventType.ORDER_COMPLETED),
            source="webhook",
            event_type=EventType.ORDER_COMPLETED if order.get("status") == "COMPLETED" else EventType.ORDER_CREATED,
            resource_type=ResourceType.ORDER,
            resource_id=order["id"],
            occurred_at=parse_ts(order.get("update_time") or order.get("create_time")),
            payload=order,
            amount=Money.from_paypal(pu.get("amount")),
            correlation_id=order["id"],
        ),
        None,
    )
    for cap in (pu.get("payments") or {}).get("captures") or []:
        cap = {**cap, "supplementary_data": {"related_ids": {"order_id": order["id"]}}}
        ingest_event(
            session,
            LedgerEvent(
                event_key=LedgerEvent.key("webhook", f"SIM-{cap['id']}", EventType.CAPTURE_COMPLETED),
                source="webhook",
                event_type=EventType.CAPTURE_COMPLETED,
                resource_type=ResourceType.CAPTURE,
                resource_id=cap["id"],
                occurred_at=parse_ts(cap.get("update_time") or cap.get("create_time")),
                payload=cap,
                amount=Money.from_paypal(cap.get("amount")),
                correlation_id=order["id"],
            ),
            None,
        )


def seed(session: Session, pp: PayPalClient, n_orders: int = 6, seed_value: int = 7) -> dict:
    rnd = random.Random(seed_value)
    created: list[dict] = []
    for i in range(n_orders):
        name, amount = SKUS[i % len(SKUS)]
        try:
            order = create_card_order(pp, amount, f"LL-SIM-{i+1}-{name.replace(' ', '-').upper()}")
        except PayPalError as exc:
            log.error("seed.order_failed", i=i, error=str(exc), body=exc.body)
            continue
        record_order_as_webhook(session, order)
        created.append(order)
        log.info("seed.order", id=order["id"], status=order.get("status"), amount=amount)

    # A legitimate partial refund on one order, recorded correctly.
    if created:
        o = rnd.choice(created)
        cap = _first_capture(o)
        if cap:
            ref = pp.refund_capture(cap["id"], {"currency_code": "USD", "value": "5.00"}, "Goodwill partial refund", request_id=_rid())
            _record_refund(session, ref, cap["id"], o["id"])

    # A payout batch with one bad receiver.
    try:
        batch = pp.create_payout(
            {
                "sender_batch_header": {"sender_batch_id": f"LL-SIM-{uuid.uuid4().hex[:8]}", "email_subject": "Creator split"},
                "items": [
                    {"recipient_type": "EMAIL", "amount": {"value": "25.00", "currency": "USD"}, "receiver": "creator-one@example.com", "sender_item_id": "SPLIT-1"},
                    {"recipient_type": "EMAIL", "amount": {"value": "80.00", "currency": "USD"}, "receiver": "creator-two@example.com", "sender_item_id": "SPLIT-2"},
                ],
            },
            request_id=_rid(),
        )
        log.info("seed.payout", batch=batch.get("batch_header", {}).get("payout_batch_id"))
    except PayPalError as exc:
        log.warning("seed.payout_failed", error=str(exc))

    # An invoice, sent.
    try:
        inv = pp.create_invoice(
            {
                "detail": {"currency_code": "USD", "invoice_number": f"LL-{uuid.uuid4().hex[:6].upper()}", "note": "Consulting retainer"},
                "primary_recipients": [{"billing_info": {"email_address": "acme-finance@example.com"}}],
                "items": [{"name": "October retainer", "quantity": "1", "unit_amount": {"currency_code": "USD", "value": "600.00"}}],
            },
            request_id=_rid(),
        )
        inv_id = inv.get("id") or inv.get("href", "").rsplit("/", 1)[-1]
        if inv_id:
            pp.send_invoice(inv_id, request_id=_rid())
            full = pp.get_invoice(inv_id)
            ingest_event(
                session,
                LedgerEvent(
                    event_key=LedgerEvent.key("webhook", f"SIM-{inv_id}", EventType.INVOICE_SENT),
                    source="webhook",
                    event_type=EventType.INVOICE_SENT,
                    resource_type=ResourceType.INVOICE,
                    resource_id=inv_id,
                    occurred_at=datetime.now(tz=timezone.utc),
                    payload=full,
                    amount=Money.from_paypal(full.get("amount")),
                ),
                None,
            )
            log.info("seed.invoice", id=inv_id)
    except PayPalError as exc:
        log.warning("seed.invoice_failed", error=str(exc))

    return {"orders": [o["id"] for o in created]}


def inject(session: Session, pp: PayPalClient, order_ids: list[str]) -> dict:
    """Create realistic divergence between ledger and PayPal."""
    if len(order_ids) < 3:
        raise RuntimeError("need at least 3 seeded orders to inject faults")
    results = {}

    # 1. Silent refund: refund at PayPal, never recorded in the ledger -> WEBHOOK_API_DRIFT after fetch.
    o1 = order_ids[0]
    cap1 = _capture_id(session, o1)
    pp.refund_capture(cap1, None, "Full refund issued from PayPal dashboard", request_id=_rid())
    fetch_capture(session, cap1, pp)  # the poller/enricher would do this; we do it now
    _dispatch(session, reconcile(session, o1))
    results["silent_refund"] = {"order": o1, "capture": cap1}

    # 2. Duplicate refund webhook: PayPal refunded once, our ledger recorded it twice -> REFUND_EXCEEDS_CAPTURE.
    o2 = order_ids[1]
    cap2 = _capture_id(session, o2)
    ref = pp.refund_capture(cap2, None, "Full refund", request_id=_rid())  # full refund, once, at PayPal
    _record_refund(session, ref, cap2, o2)
    dup = {**ref, "id": ref["id"] + "-DUP"}  # the same refund recorded a second time under another id
    _record_refund(session, dup, cap2, o2)  # ledger now believes 2x the capture was refunded
    results["duplicate_refund_record"] = {"order": o2, "capture": cap2, "refund": ref["id"]}

    # 3. Over-capture: ledger believes a second capture happened (replayed webhook) -> DUPLICATE_CAPTURE.
    o3 = order_ids[2]
    cap3 = _capture_id(session, o3)
    ghost = {"id": cap3 + "-REPLAY", "status": "COMPLETED", "final_capture": True, "amount": _capture_amount(session, cap3),
             "supplementary_data": {"related_ids": {"order_id": o3}}, "create_time": datetime.now(tz=timezone.utc).isoformat()}
    ingest_event(
        session,
        LedgerEvent(
            event_key=LedgerEvent.key("webhook", f"SIM-{ghost['id']}", EventType.CAPTURE_COMPLETED),
            source="webhook",
            event_type=EventType.CAPTURE_COMPLETED,
            resource_type=ResourceType.CAPTURE,
            resource_id=ghost["id"],
            occurred_at=datetime.now(tz=timezone.utc),
            payload=ghost,
            amount=Money.from_paypal(ghost["amount"]),
            correlation_id=o3,
        ),
        None,
    )
    results["ghost_capture"] = {"order": o3, "capture": ghost["id"]}
    return results


# ---------------------------------------------------------------- helpers


def _dispatch(session: Session, breaks) -> None:
    for b in breaks:
        if b.severity in ("critical", "warn"):
            queue.enqueue(session, "run_agent", dedupe_key=f"break:{b.id}", payload={"break_id": b.id})


def _first_capture(order: dict) -> dict | None:
    pu = (order.get("purchase_units") or [{}])[0]
    caps = (pu.get("payments") or {}).get("captures") or []
    return caps[0] if caps else None


def _capture_id(session: Session, order_id: str) -> str:
    from app.domain.models import Capture

    cap = session.query(Capture).filter(Capture.order_id == order_id).order_by(Capture.created_at).first()
    if cap is None:
        raise RuntimeError(f"no capture for order {order_id}")
    return cap.id


def _capture_amount(session: Session, capture_id: str) -> dict:
    from app.domain.models import Capture

    cap = session.get(Capture, capture_id)
    return Money(cap.amount_minor, cap.currency).to_paypal()


def _record_refund(session: Session, ref: dict, capture_id: str, order_id: str) -> None:
    payload = {**ref, "supplementary_data": {"related_ids": {"order_id": order_id, "capture_id": capture_id}}}
    ingest_event(
        session,
        LedgerEvent(
            event_key=LedgerEvent.key("webhook", f"SIM-{ref['id']}", EventType.REFUND_COMPLETED),
            source="webhook",
            event_type=EventType.REFUND_COMPLETED,
            resource_type=ResourceType.REFUND,
            resource_id=ref["id"],
            occurred_at=parse_ts(ref.get("update_time") or ref.get("create_time")),
            payload=payload,
            amount=Money.from_paypal(ref.get("amount")),
            correlation_id=order_id,
        ),
        None,
    )
