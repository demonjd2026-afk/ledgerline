"""Webhook receiver. Does the minimum inline: verify, persist, enqueue, 200.

PayPal retries on non-2xx for up to three days; keeping this endpoint fast and side-effect
free (beyond the inbox row) is what makes at-least-once delivery harmless.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.domain.models import WebhookInbox
from app.logging import get_logger
from app.paypal.client import PayPalClient
from app.worker import queue

log = get_logger("ingest.webhook")
router = APIRouter(tags=["ingest"])

PAYPAL_HEADERS = (
    "paypal-auth-algo",
    "paypal-cert-url",
    "paypal-transmission-id",
    "paypal-transmission-sig",
    "paypal-transmission-time",
)


def _paypal_client() -> PayPalClient:
    return PayPalClient()


@router.post("/webhooks/paypal", status_code=status.HTTP_200_OK)
async def receive_paypal_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    paypal: PayPalClient = Depends(_paypal_client),
) -> Response:
    body: dict[str, Any] = await request.json()
    headers = {k: v for k, v in request.headers.items() if k.lower() in PAYPAL_HEADERS}
    event_id = body.get("id")
    if not event_id or not body.get("event_type"):
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    # Persist first (idempotent on paypal_event_id), verify second.
    stmt = (
        pg_insert(WebhookInbox)
        .values(paypal_event_id=event_id, event_type=body["event_type"], headers=headers, body=body, status="received")
        .on_conflict_do_nothing(index_elements=["paypal_event_id"])
        .returning(WebhookInbox.id)
    )
    inbox_id = db.execute(stmt).scalar()
    if inbox_id is None:
        log.info("webhook.duplicate", event_id=event_id)
        return Response(status_code=status.HTTP_200_OK)

    verified = _verify(paypal, settings, headers, body)
    row = db.get(WebhookInbox, inbox_id)
    if row is None:  # pragma: no cover - same transaction, cannot happen
        return Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    if not verified:
        row.status = "rejected"
        row.error = "signature verification failed"
        log.warning("webhook.rejected", event_id=event_id, event_type=body["event_type"])
        # 200 so PayPal stops retrying; the row is kept for forensics.
        return Response(status_code=status.HTTP_200_OK)

    row.status = "verified"
    queue.enqueue(db, "process_webhook", dedupe_key=event_id, payload={"inbox_id": inbox_id})
    log.info("webhook.accepted", event_id=event_id, event_type=body["event_type"])
    return Response(status_code=status.HTTP_200_OK)


def _verify(paypal: PayPalClient, settings: Settings, headers: dict, body: dict) -> bool:
    if not settings.paypal_webhook_id:
        if settings.app_env == "prod":
            log.error("webhook.rejected", reason="PAYPAL_WEBHOOK_ID not set in prod; refusing unverified webhooks")
            return False
        # Local/dev/test without a registered webhook id: accept, but say so loudly.
        log.warning("webhook.unverified", reason="PAYPAL_WEBHOOK_ID not set")
        return True
    try:
        return paypal.verify_webhook_signature(headers, body, settings.paypal_webhook_id)
    except Exception as exc:  # noqa: BLE001
        log.error("webhook.verify_error", error=str(exc))
        return False
