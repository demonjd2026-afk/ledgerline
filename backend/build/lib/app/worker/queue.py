"""Durable job queue on Postgres. No broker to run, exactly what a one-merchant deployment needs.

Claim semantics: ``SELECT ... FOR UPDATE SKIP LOCKED`` so N workers never collide.
Dedupe: ``(kind, dedupe_key)`` is unique, so enqueuing the same work twice is a no-op
while it is queued or running.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import Job


def enqueue(session: Session, kind: str, dedupe_key: str, payload: dict | None = None, delay_seconds: int = 0) -> int | None:
    """Returns job id, or None if an identical queued/running job already exists."""
    run_after = datetime.now(tz=UTC) + timedelta(seconds=delay_seconds)
    stmt = (
        pg_insert(Job)
        .values(kind=kind, dedupe_key=dedupe_key, payload=payload or {}, run_after=run_after)
        .on_conflict_do_update(
            constraint="uq_jobs_kind_dedupe",
            set_={"run_after": run_after, "status": "queued", "attempts": 0, "last_error": None},
            where=Job.status.in_(["done", "failed", "dead"]),
        )
        .returning(Job.id)
    )
    return session.execute(stmt).scalar()


def claim(session: Session, batch: int) -> list[Job]:
    rows = session.execute(
        text(
            """
            UPDATE jobs SET status='running', attempts=attempts+1
            WHERE id IN (
                SELECT id FROM jobs
                WHERE status='queued' AND run_after <= now()
                ORDER BY run_after, id
                FOR UPDATE SKIP LOCKED
                LIMIT :batch
            )
            RETURNING id
            """
        ),
        {"batch": batch},
    ).scalars().all()
    if not rows:
        return []
    return list(session.execute(select(Job).where(Job.id.in_(rows)).order_by(Job.id)).scalars())


def complete(session: Session, job_id: int) -> None:
    session.execute(update(Job).where(Job.id == job_id).values(status="done", finished_at=datetime.now(tz=UTC)))


def fail(session: Session, job: Job, error: str) -> None:
    s = get_settings()
    if job.attempts >= s.job_max_attempts:
        status, run_after = "dead", job.run_after
    else:
        status = "queued"
        run_after = datetime.now(tz=UTC) + timedelta(seconds=min(2 ** job.attempts * 5, 900))
    session.execute(
        update(Job).where(Job.id == job.id).values(status=status, run_after=run_after, last_error=error[:4000])
    )


def stats(session: Session) -> dict[str, int]:
    rows = session.execute(text("SELECT status, count(*) FROM jobs GROUP BY status")).all()
    return {r[0]: r[1] for r in rows}
