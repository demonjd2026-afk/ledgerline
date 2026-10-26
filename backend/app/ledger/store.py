"""Append-only ledger store. The unique ``event_key`` makes every append idempotent."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.domain.events import LedgerEvent
from app.domain.models import LedgerEventRow
from app.ledger.projections import apply_event
from app.logging import get_logger

log = get_logger("ledger")


def append(session: Session, ev: LedgerEvent) -> tuple[LedgerEventRow | None, bool]:
    """Append an event and update projections.

    Returns (row, inserted). A duplicate event_key returns (existing_row, False) and does
    nothing else — safe to call on every redelivery.
    """
    stmt = (
        pg_insert(LedgerEventRow)
        .values(
            event_key=ev.event_key,
            source=ev.source,
            event_type=str(ev.event_type),
            resource_type=str(ev.resource_type),
            resource_id=ev.resource_id,
            correlation_id=ev.correlation_id,
            occurred_at=ev.occurred_at,
            amount_minor=ev.amount.minor if ev.amount else None,
            currency=ev.amount.currency if ev.amount else None,
            payload=ev.payload,
        )
        .on_conflict_do_nothing(index_elements=["event_key"])
        .returning(LedgerEventRow.id)
    )
    new_id = session.execute(stmt).scalar()
    if new_id is None:
        existing = session.execute(
            select(LedgerEventRow).where(LedgerEventRow.event_key == ev.event_key)
        ).scalar_one()
        return existing, False
    row = session.get(LedgerEventRow, new_id)
    assert row is not None
    apply_event(session, row)
    log.info("ledger.append", type=row.event_type, resource=row.resource_id, corr=row.correlation_id)
    return row, True


def chain(session: Session, correlation_id: str) -> list[LedgerEventRow]:
    """All events for an order chain, oldest first."""
    return list(
        session.execute(
            select(LedgerEventRow)
            .where(LedgerEventRow.correlation_id == correlation_id)
            .order_by(LedgerEventRow.occurred_at, LedgerEventRow.id)
        ).scalars()
    )


def events_for_resource(session: Session, resource_type: str, resource_id: str) -> list[LedgerEventRow]:
    return list(
        session.execute(
            select(LedgerEventRow)
            .where(LedgerEventRow.resource_type == resource_type, LedgerEventRow.resource_id == resource_id)
            .order_by(LedgerEventRow.id)
        ).scalars()
    )


def rebuild_projections(session: Session) -> int:
    """Drop projections and replay every event. Returns events replayed."""
    from app.ledger.projections import truncate_projections

    truncate_projections(session)
    n = 0
    for row in session.execute(select(LedgerEventRow).order_by(LedgerEventRow.id)).scalars():
        apply_event(session, row)
        n += 1
    log.info("ledger.rebuild", events=n)
    return n


def latest_recorded_at(session: Session) -> datetime | None:
    return session.execute(select(LedgerEventRow.recorded_at).order_by(LedgerEventRow.id.desc()).limit(1)).scalar()
