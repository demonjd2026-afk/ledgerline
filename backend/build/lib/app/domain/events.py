"""Normalised ledger event vocabulary and the PayPal -> ledger mapping.

PayPal emits ~40 webhook event names. The reconciler reasons over ~14 stable
types. Keeping the mapping in one place means PayPal adding a variant is a
one-line change here, not a rules rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.domain.money import Money


class EventType(StrEnum):
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_APPROVED = "ORDER_APPROVED"
    ORDER_COMPLETED = "ORDER_COMPLETED"
    AUTHORIZATION_CREATED = "AUTHORIZATION_CREATED"
    AUTHORIZATION_VOIDED = "AUTHORIZATION_VOIDED"
    CAPTURE_COMPLETED = "CAPTURE_COMPLETED"
    CAPTURE_DENIED = "CAPTURE_DENIED"
    CAPTURE_PENDING = "CAPTURE_PENDING"
    CAPTURE_REFUNDED = "CAPTURE_REFUNDED"
    CAPTURE_REVERSED = "CAPTURE_REVERSED"
    REFUND_COMPLETED = "REFUND_COMPLETED"
    REFUND_FAILED = "REFUND_FAILED"
    PAYOUT_BATCH_PROCESSED = "PAYOUT_BATCH_PROCESSED"
    PAYOUT_ITEM_SUCCEEDED = "PAYOUT_ITEM_SUCCEEDED"
    PAYOUT_ITEM_FAILED = "PAYOUT_ITEM_FAILED"
    DISPUTE_CREATED = "DISPUTE_CREATED"
    DISPUTE_UPDATED = "DISPUTE_UPDATED"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    INVOICE_CREATED = "INVOICE_CREATED"
    INVOICE_SENT = "INVOICE_SENT"
    INVOICE_PAID = "INVOICE_PAID"
    INVOICE_CANCELLED = "INVOICE_CANCELLED"
    INVOICE_REFUNDED = "INVOICE_REFUNDED"
    TRANSACTION_OBSERVED = "TRANSACTION_OBSERVED"  # from reporting / transaction search
    LEDGER_CORRECTION = "LEDGER_CORRECTION"  # explicit, audited correction event


class ResourceType(StrEnum):
    ORDER = "order"
    AUTHORIZATION = "authorization"
    CAPTURE = "capture"
    REFUND = "refund"
    PAYOUT_BATCH = "payout_batch"
    PAYOUT_ITEM = "payout_item"
    DISPUTE = "dispute"
    INVOICE = "invoice"
    TRANSACTION = "transaction"


# PayPal webhook event_type -> (ledger EventType, ResourceType)
WEBHOOK_MAP: dict[str, tuple[EventType, ResourceType]] = {
    "CHECKOUT.ORDER.APPROVED": (EventType.ORDER_APPROVED, ResourceType.ORDER),
    "CHECKOUT.ORDER.COMPLETED": (EventType.ORDER_COMPLETED, ResourceType.ORDER),
    "PAYMENT.AUTHORIZATION.CREATED": (EventType.AUTHORIZATION_CREATED, ResourceType.AUTHORIZATION),
    "PAYMENT.AUTHORIZATION.VOIDED": (EventType.AUTHORIZATION_VOIDED, ResourceType.AUTHORIZATION),
    "PAYMENT.CAPTURE.COMPLETED": (EventType.CAPTURE_COMPLETED, ResourceType.CAPTURE),
    "PAYMENT.CAPTURE.DENIED": (EventType.CAPTURE_DENIED, ResourceType.CAPTURE),
    "PAYMENT.CAPTURE.PENDING": (EventType.CAPTURE_PENDING, ResourceType.CAPTURE),
    "PAYMENT.CAPTURE.REFUNDED": (EventType.CAPTURE_REFUNDED, ResourceType.CAPTURE),
    "PAYMENT.CAPTURE.REVERSED": (EventType.CAPTURE_REVERSED, ResourceType.CAPTURE),
    "PAYMENT.PAYOUTSBATCH.PROCESSING": (EventType.PAYOUT_BATCH_PROCESSED, ResourceType.PAYOUT_BATCH),
    "PAYMENT.PAYOUTSBATCH.SUCCESS": (EventType.PAYOUT_BATCH_PROCESSED, ResourceType.PAYOUT_BATCH),
    "PAYMENT.PAYOUTSBATCH.DENIED": (EventType.PAYOUT_BATCH_PROCESSED, ResourceType.PAYOUT_BATCH),
    "PAYMENT.PAYOUTS-ITEM.SUCCEEDED": (EventType.PAYOUT_ITEM_SUCCEEDED, ResourceType.PAYOUT_ITEM),
    "PAYMENT.PAYOUTS-ITEM.FAILED": (EventType.PAYOUT_ITEM_FAILED, ResourceType.PAYOUT_ITEM),
    "PAYMENT.PAYOUTS-ITEM.BLOCKED": (EventType.PAYOUT_ITEM_FAILED, ResourceType.PAYOUT_ITEM),
    "PAYMENT.PAYOUTS-ITEM.RETURNED": (EventType.PAYOUT_ITEM_FAILED, ResourceType.PAYOUT_ITEM),
    "PAYMENT.PAYOUTS-ITEM.UNCLAIMED": (EventType.PAYOUT_ITEM_FAILED, ResourceType.PAYOUT_ITEM),
    "CUSTOMER.DISPUTE.CREATED": (EventType.DISPUTE_CREATED, ResourceType.DISPUTE),
    "CUSTOMER.DISPUTE.UPDATED": (EventType.DISPUTE_UPDATED, ResourceType.DISPUTE),
    "CUSTOMER.DISPUTE.RESOLVED": (EventType.DISPUTE_RESOLVED, ResourceType.DISPUTE),
    "INVOICING.INVOICE.CREATED": (EventType.INVOICE_CREATED, ResourceType.INVOICE),
    "INVOICING.INVOICE.SENT": (EventType.INVOICE_SENT, ResourceType.INVOICE),
    "INVOICING.INVOICE.PAID": (EventType.INVOICE_PAID, ResourceType.INVOICE),
    "INVOICING.INVOICE.CANCELLED": (EventType.INVOICE_CANCELLED, ResourceType.INVOICE),
    "INVOICING.INVOICE.REFUNDED": (EventType.INVOICE_REFUNDED, ResourceType.INVOICE),
}


@dataclass(slots=True)
class LedgerEvent:
    """A normalised event ready to append. ``event_key`` is the idempotency key."""

    event_key: str
    source: str  # webhook | poll | api | sim | correction
    event_type: EventType
    resource_type: ResourceType
    resource_id: str
    occurred_at: datetime
    payload: dict[str, Any]
    amount: Money | None = None
    correlation_id: str | None = None

    @staticmethod
    def key(source: str, external_id: str, event_type: EventType | str) -> str:
        return f"{source}:{external_id}:{event_type}"


def parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=UTC)
    # PayPal uses RFC3339 with Z.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def correlation_from_resource(resource_type: ResourceType, resource: dict[str, Any]) -> str | None:
    """Best-effort order id that ties a chain of events together."""
    if resource_type == ResourceType.ORDER:
        return resource.get("id")
    if resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id"):
        return resource["supplementary_data"]["related_ids"]["order_id"]
    if resource_type == ResourceType.REFUND:
        rel = resource.get("supplementary_data", {}).get("related_ids", {})
        return rel.get("order_id") or rel.get("capture_id")
    if resource_type == ResourceType.DISPUTE:
        txs = resource.get("disputed_transactions") or []
        if txs:
            return txs[0].get("seller_transaction_id")
    for link in resource.get("links", []) or []:
        if link.get("rel") == "up" and "/checkout/orders/" in link.get("href", ""):
            return link["href"].rsplit("/", 1)[-1]
    return None


def normalise_webhook(envelope: dict[str, Any]) -> LedgerEvent | None:
    """Turn a PayPal webhook envelope into a ledger event. Unknown events return None."""
    mapped = WEBHOOK_MAP.get(envelope.get("event_type", ""))
    if not mapped:
        return None
    event_type, resource_type = mapped
    resource = envelope.get("resource") or {}
    resource_id = resource.get("id") or resource.get("dispute_id") or resource.get("batch_header", {}).get(
        "payout_batch_id", ""
    )
    if resource_type == ResourceType.PAYOUT_ITEM:
        resource_id = resource.get("payout_item_id") or resource_id
    if resource_type == ResourceType.PAYOUT_BATCH:
        resource_id = resource.get("batch_header", {}).get("payout_batch_id") or resource_id
    if not resource_id:
        return None

    amount = Money.from_paypal(resource.get("amount")) or Money.from_paypal(
        resource.get("dispute_amount")
    )
    if resource_type == ResourceType.ORDER:
        pu = (resource.get("purchase_units") or [{}])[0]
        amount = Money.from_paypal(pu.get("amount"))
    if resource_type == ResourceType.PAYOUT_ITEM:
        amount = Money.from_paypal((resource.get("payout_item") or {}).get("amount"))
    if resource_type == ResourceType.INVOICE:
        amount = Money.from_paypal(resource.get("amount") or {})

    return LedgerEvent(
        event_key=LedgerEvent.key("webhook", envelope.get("id") or f"{resource_id}", event_type),
        source="webhook",
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        occurred_at=parse_ts(resource.get("update_time") or resource.get("create_time") or envelope.get("create_time")),
        payload=resource,
        amount=amount,
        correlation_id=correlation_from_resource(resource_type, resource),
    )
