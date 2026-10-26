"""Replay recorded PayPal inputs through the production pipeline. No network."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.domain.events import EventType, LedgerEvent, ResourceType, correlation_from_resource, normalise_webhook, parse_ts
from app.domain.money import Money
from app.ingest.pipeline import ingest_event
from app.logging import get_logger

log = get_logger("sim.replay")
FIXTURES = Path(__file__).parent / "fixtures"


def replay_file(session: Session, path: Path, source_override: str | None = None) -> dict[str, int]:
    counts = {"webhook": 0, "api_capture": 0, "api_order": 0, "transaction": 0, "skipped": 0}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rec = json.loads(line)
        if "_comment" in rec:
            continue
        kind = rec.get("kind", "webhook")
        ev = _to_event(rec, kind)
        if ev is None:
            counts["skipped"] += 1
            continue
        if source_override:
            ev.source = source_override
        ingest_event(session, ev, None)
        counts[kind] = counts.get(kind, 0) + 1
    log.info("replay.done", file=str(path), **counts)
    return counts


def _to_event(rec: dict, kind: str) -> LedgerEvent | None:
    if kind == "webhook":
        return normalise_webhook(rec)
    if kind == "api_capture":
        r = rec["resource"]
        return LedgerEvent(
            event_key=LedgerEvent.key("api", r["id"], f"CAPTURE_SNAPSHOT_{r.get('status')}_{r.get('update_time','')}"),
            source="api",
            event_type=EventType.CAPTURE_COMPLETED,
            resource_type=ResourceType.CAPTURE,
            resource_id=r["id"],
            occurred_at=parse_ts(r.get("update_time") or r.get("create_time")),
            payload=r,
            amount=Money.from_paypal(r.get("amount")),
            correlation_id=correlation_from_resource(ResourceType.CAPTURE, r),
        )
    if kind == "api_order":
        r = rec["resource"]
        pu = (r.get("purchase_units") or [{}])[0]
        return LedgerEvent(
            event_key=LedgerEvent.key("api", r["id"], f"ORDER_SNAPSHOT_{r.get('status')}"),
            source="api",
            event_type=EventType.ORDER_COMPLETED if r.get("status") == "COMPLETED" else EventType.ORDER_CREATED,
            resource_type=ResourceType.ORDER,
            resource_id=r["id"],
            occurred_at=parse_ts(r.get("update_time") or r.get("create_time")),
            payload=r,
            amount=Money.from_paypal(pu.get("amount")),
            correlation_id=r["id"],
        )
    if kind == "transaction":
        info = rec["transaction_info"]
        return LedgerEvent(
            event_key=LedgerEvent.key("poll", info["transaction_id"], f"TX_{info.get('transaction_status')}_{info.get('transaction_updated_date','')}"),
            source="poll",
            event_type=EventType.TRANSACTION_OBSERVED,
            resource_type=ResourceType.TRANSACTION,
            resource_id=info["transaction_id"],
            occurred_at=parse_ts(info.get("transaction_updated_date") or info.get("transaction_initiation_date")),
            payload=rec,
            amount=Money.from_paypal(info.get("transaction_amount")),
        )
    return None
