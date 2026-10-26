"""Pull-side ingestion: the second source of truth.

Transaction Search gives the settled view PayPal's reporting sees; disputes are polled because
dispute webhooks can be enabled late. Anything the poll finds that the ledger lacks is appended
with ``source=poll``; anything that disagrees becomes a break in the reconciler.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.domain.events import EventType, LedgerEvent, ResourceType, correlation_from_resource, parse_ts
from app.domain.money import Money
from app.ingest.pipeline import ingest_event
from app.logging import get_logger
from app.paypal.client import PayPalClient, PayPalError

log = get_logger("poller")


def poll_transactions(session: Session, paypal: PayPalClient, lookback_hours: int = 72) -> int:
    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(hours=lookback_hours)
    fmt = "%Y-%m-%dT%H:%M:%S-0000"
    page, n = 1, 0
    while True:
        try:
            res = paypal.list_transactions(start.strftime(fmt), end.strftime(fmt), page=page)
        except PayPalError as exc:
            # Sandbox accounts without the Transaction Search feature return 403; not fatal.
            log.warning("poll.transactions_unavailable", status=exc.status)
            return n
        for item in res.get("transaction_details") or []:
            info = item.get("transaction_info") or {}
            tx_id = info.get("transaction_id")
            if not tx_id:
                continue
            ev = LedgerEvent(
                event_key=LedgerEvent.key("poll", tx_id, f"TX_{info.get('transaction_status')}_{info.get('transaction_updated_date','')}"),
                source="poll",
                event_type=EventType.TRANSACTION_OBSERVED,
                resource_type=ResourceType.TRANSACTION,
                resource_id=tx_id,
                occurred_at=parse_ts(info.get("transaction_updated_date") or info.get("transaction_initiation_date")),
                payload=item,
                amount=Money.from_paypal(info.get("transaction_amount")),
                correlation_id=None,
            )
            ingest_event(session, ev, paypal)
            n += 1
        if page >= int(res.get("total_pages") or 1):
            break
        page += 1
    log.info("poll.transactions", observed=n)
    return n


def poll_disputes(session: Session, paypal: PayPalClient) -> int:
    n, token = 0, None
    while True:
        try:
            res = paypal.list_disputes(next_page_token=token)
        except PayPalError as exc:
            log.warning("poll.disputes_unavailable", status=exc.status)
            return n
        for d in res.get("items") or []:
            dispute_id = d.get("dispute_id")
            if not dispute_id:
                continue
            try:
                full = paypal.get_dispute(dispute_id)
            except PayPalError:
                full = d
            ev = LedgerEvent(
                event_key=LedgerEvent.key("poll", dispute_id, f"DISPUTE_{full.get('status')}_{full.get('update_time','')}"),
                source="poll",
                event_type=EventType.DISPUTE_UPDATED,
                resource_type=ResourceType.DISPUTE,
                resource_id=dispute_id,
                occurred_at=parse_ts(full.get("update_time") or full.get("create_time")),
                payload=full,
                amount=Money.from_paypal(full.get("dispute_amount")),
                correlation_id=correlation_from_resource(ResourceType.DISPUTE, full),
            )
            ingest_event(session, ev, paypal)
            n += 1
        token = next((l.get("href") for l in res.get("links", []) if l.get("rel") == "next"), None)
        if not token:
            break
        token = token.split("next_page_token=")[-1] if "next_page_token=" in token else None
        if not token:
            break
    log.info("poll.disputes", observed=n)
    return n
