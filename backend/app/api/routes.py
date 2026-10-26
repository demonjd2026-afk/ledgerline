"""Dashboard + operator API. Read endpoints are plain queries; approval endpoints resume graphs."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.runner import resume_run, start_run
from app.config import get_settings
from app.db import get_db
from app.domain.models import (
    AgentRun,
    Approval,
    Break,
    Capture,
    Dispute,
    Invoice,
    LedgerEventRow,
    Order,
    PayoutItem,
    Refund,
    WebhookInbox,
)
from app.domain.money import to_decimal_str
from app.ledger import store
from app.paypal.client import PayPalClient
from app.recon.engine import reconcile_all
from app.worker import queue

router = APIRouter(prefix="/api", tags=["api"])


def _paypal() -> PayPalClient | None:
    return PayPalClient() if get_settings().paypal_configured else None


def _row(obj: Any) -> dict:
    d = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    cur = d.get("currency")
    for k in list(d):
        if k.endswith("_minor") and d[k] is not None and cur:
            d[k[:-6]] = to_decimal_str(d[k], cur)
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in d.items()}


# ---------------------------------------------------------------- overview


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    def count(model, *conds):
        return db.execute(select(func.count()).select_from(model).where(*conds)).scalar() or 0

    open_breaks = db.execute(
        select(Break.severity, func.count()).where(Break.status.in_(["open", "in_progress", "awaiting_approval"])).group_by(Break.severity)
    ).all()
    exposure = db.execute(
        select(Break.currency, func.sum(func.abs(Break.delta_minor)))
        .where(Break.status.in_(["open", "in_progress", "awaiting_approval"]), Break.delta_minor.is_not(None))
        .group_by(Break.currency)
    ).all()
    return {
        "events": count(LedgerEventRow),
        "orders": count(Order),
        "captures": count(Capture),
        "refunds": count(Refund),
        "disputes_open": count(Dispute, Dispute.status != "RESOLVED"),
        "payout_items": count(PayoutItem),
        "invoices": count(Invoice),
        "breaks_open_by_severity": {sev: n for sev, n in open_breaks},
        "breaks_resolved": count(Break, Break.status == "resolved"),
        "exposure": {cur or "?": to_decimal_str(int(total or 0), cur or "USD") for cur, total in exposure},
        "approvals_pending": count(Approval, Approval.status == "pending"),
        "agent_runs": count(AgentRun),
        "webhooks_received": count(WebhookInbox),
        "webhooks_rejected": count(WebhookInbox, WebhookInbox.status == "rejected"),
        "jobs": queue.stats(db),
        "last_event_at": (store.latest_recorded_at(db) or datetime.now(tz=UTC)).isoformat(),
        "paypal_configured": get_settings().paypal_configured,
        "llm_model": get_settings().llm_model,
    }


# ---------------------------------------------------------------- ledger


@router.get("/ledger/events")
def ledger_events(
    db: Session = Depends(get_db),
    limit: int = Query(200, le=2000),
    correlation_id: str | None = None,
    resource_type: str | None = None,
) -> list[dict]:
    q = select(LedgerEventRow).order_by(LedgerEventRow.id.desc()).limit(limit)
    if correlation_id:
        q = q.where(LedgerEventRow.correlation_id == correlation_id)
    if resource_type:
        q = q.where(LedgerEventRow.resource_type == resource_type)
    return [_row(e) | {"payload": e.payload} for e in db.execute(q).scalars()]


@router.get("/ledger/{table}")
def ledger_table(table: str, db: Session = Depends(get_db), limit: int = Query(500, le=5000)) -> list[dict]:
    model = {
        "orders": Order,
        "captures": Capture,
        "refunds": Refund,
        "disputes": Dispute,
        "payouts": PayoutItem,
        "invoices": Invoice,
    }.get(table)
    if model is None:
        raise HTTPException(404, "unknown table")
    rows = db.execute(select(model).order_by(model.updated_at.desc()).limit(limit)).scalars()
    return [_row(r) for r in rows]


@router.get("/orders/{order_id}/chain")
def order_chain(order_id: str, db: Session = Depends(get_db)) -> dict:
    order = db.get(Order, order_id)
    return {
        "order": _row(order) if order else None,
        "captures": [_row(c) for c in db.execute(select(Capture).where(Capture.order_id == order_id)).scalars()],
        "refunds": [_row(r) for r in db.execute(select(Refund).where(Refund.order_id == order_id)).scalars()],
        "disputes": [_row(d) for d in db.execute(select(Dispute).where(Dispute.order_id == order_id)).scalars()],
        "events": [_row(e) | {"payload": e.payload} for e in store.chain(db, order_id)],
        "breaks": [_row(b) for b in db.execute(select(Break).where(Break.correlation_id == order_id)).scalars()],
    }


# ---------------------------------------------------------------- breaks


@router.get("/breaks")
def list_breaks(db: Session = Depends(get_db), status: str | None = None, limit: int = Query(500, le=5000)) -> list[dict]:
    q = select(Break).order_by(Break.opened_at.desc()).limit(limit)
    if status:
        q = q.where(Break.status.in_(status.split(",")))
    out = []
    for b in db.execute(q).scalars():
        run = db.execute(select(AgentRun).where(AgentRun.break_id == b.id).order_by(AgentRun.id.desc()).limit(1)).scalar_one_or_none()
        out.append(_row(b) | {"agent_run_id": run.id if run else None, "agent_status": run.status if run else None})
    return out


@router.get("/breaks/{break_id}")
def get_break(break_id: int, db: Session = Depends(get_db)) -> dict:
    b = db.get(Break, break_id)
    if b is None:
        raise HTTPException(404)
    runs = db.execute(select(AgentRun).where(AgentRun.break_id == break_id).order_by(AgentRun.id)).scalars()
    approvals = db.execute(select(Approval).where(Approval.break_id == break_id).order_by(Approval.id)).scalars()
    return {"break": _row(b), "runs": [_row(r) for r in runs], "approvals": [_row(a) for a in approvals]}


@router.post("/breaks/{break_id}/run")
def run_break(break_id: int, db: Session = Depends(get_db)) -> dict:
    run = start_run(db, break_id, _paypal())
    return _row(run)


class Dismiss(BaseModel):
    note: str
    by: str = "operator"


@router.post("/breaks/{break_id}/dismiss")
def dismiss_break(break_id: int, body: Dismiss, db: Session = Depends(get_db)) -> dict:
    b = db.get(Break, break_id)
    if b is None:
        raise HTTPException(404)
    b.status, b.resolved_at = "resolved", datetime.now(tz=UTC)
    b.resolution = {"kind": "dismissed", "by": body.by, "note": body.note}
    return _row(b)


@router.post("/reconcile")
def reconcile_now(db: Session = Depends(get_db)) -> dict:
    new = reconcile_all(db)
    for b in new:
        if b.severity in ("critical", "warn"):
            queue.enqueue(db, "run_agent", dedupe_key=f"break:{b.id}", payload={"break_id": b.id})
    return {"new_breaks": len(new)}


# ---------------------------------------------------------------- agent runs + approvals


@router.get("/runs")
def list_runs(db: Session = Depends(get_db), limit: int = Query(200, le=2000)) -> list[dict]:
    return [_row(r) for r in db.execute(select(AgentRun).order_by(AgentRun.id.desc()).limit(limit)).scalars()]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    r = db.get(AgentRun, run_id)
    if r is None:
        raise HTTPException(404)
    b = db.get(Break, r.break_id)
    approvals = db.execute(select(Approval).where(Approval.agent_run_id == run_id).order_by(Approval.id)).scalars()
    return {"run": _row(r), "break": _row(b) if b else None, "approvals": [_row(a) for a in approvals]}


@router.get("/approvals")
def list_approvals(db: Session = Depends(get_db), status: str = "pending") -> list[dict]:
    q = select(Approval).order_by(Approval.id.desc())
    if status != "all":
        q = q.where(Approval.status.in_(status.split(",")))
    out = []
    for a in db.execute(q).scalars():
        b = db.get(Break, a.break_id)
        out.append(_row(a) | {"break": _row(b) if b else None})
    return out


@router.get("/approvals/{approval_id}/sheet")
def approval_sheet(approval_id: int, db: Session = Depends(get_db)) -> dict:
    """Everything an operator needs to decide, in one payload."""
    a = db.get(Approval, approval_id)
    if a is None:
        raise HTTPException(404)
    b = db.get(Break, a.break_id)
    run = db.get(AgentRun, a.agent_run_id)
    chain = order_chain(b.correlation_id, db) if b and b.correlation_id and db.get(Order, b.correlation_id) else None
    return {"approval": _row(a), "break": _row(b) if b else None, "run": _row(run) if run else None, "chain": chain}


class Decision(BaseModel):
    approved: bool
    by: str = "operator"
    note: str | None = None


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: int, body: Decision, db: Session = Depends(get_db)) -> dict:
    try:
        run = resume_run(db, approval_id, body.approved, body.by, body.note, _paypal())
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    ap = db.get(Approval, approval_id)
    return {"run": _row(run), "approval": _row(ap) if ap else None}


# ---------------------------------------------------------------- policy + ops


@router.get("/policy")
def policy() -> dict:
    from app.agents.policy import load_policy

    return load_policy()


@router.get("/webhooks")
def webhooks(db: Session = Depends(get_db), limit: int = Query(200, le=2000)) -> list[dict]:
    return [
        _row(w) | {"headers": None, "body": None, "resource_id": (w.body.get("resource") or {}).get("id")}
        for w in db.execute(select(WebhookInbox).order_by(WebhookInbox.id.desc()).limit(limit)).scalars()
    ]
