"""Runs and resumes agent graphs; owns the agent_runs / approvals bookkeeping."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.graph import GraphDeps, as_jsonable, build_graph, resume_command
from app.agents.policy import PolicyDecision
from app.config import get_settings
from app.domain.models import AgentRun, Approval, Break
from app.logging import get_logger
from app.paypal.client import PayPalClient

log = get_logger("agent.runner")


@lru_cache
def _checkpointer() -> PostgresSaver:
    import atexit

    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    pool = ConnectionPool(conninfo=url, max_size=4, open=True, kwargs={"autocommit": True, "prepare_threshold": 0})
    atexit.register(pool.close)
    return PostgresSaver(pool)


def ensure_checkpointer() -> None:
    """Create LangGraph's checkpoint tables. Must run OUTSIDE any open transaction: setup() uses
    CREATE INDEX CONCURRENTLY, which waits for every in-flight transaction. Call at process start."""
    _checkpointer().setup()


def record_approval(session: Session, agent_run_id: int, break_id: int, proposal: dict, decision: PolicyDecision) -> int:
    key = hashlib.sha256(f"{agent_run_id}:{break_id}:{proposal.get('action')}".encode()).hexdigest()[:32]
    ap = Approval(
        agent_run_id=agent_run_id,
        break_id=break_id,
        action=proposal["action"],
        proposal=as_jsonable(proposal),
        policy_version=decision.version,
        policy_decision=decision.decision,
        policy_reasons=decision.reasons,
        status="approved" if decision.decision == "auto" else ("declined" if decision.decision == "forbidden" else "pending"),
        decided_by="policy:auto" if decision.decision == "auto" else None,
        decided_at=datetime.now(tz=timezone.utc) if decision.decision == "auto" else None,
        idempotency_key=key,
    )
    session.add(ap)
    session.flush()
    run = session.get(AgentRun, agent_run_id)
    if run is not None:
        run.proposal = as_jsonable(proposal)
        run.status = "awaiting_approval" if decision.decision == "requires_human" else run.status
    b = session.get(Break, break_id)
    if b is not None and decision.decision == "requires_human":
        b.status = "awaiting_approval"
    return ap.id


def close_run(session: Session, agent_run_id: int, state: dict, outcome: dict) -> None:
    run = session.get(AgentRun, agent_run_id)
    if run is None:
        return
    run.trace = as_jsonable(state.get("trace") or [])
    run.outcome = as_jsonable(outcome)
    run.specialist = (state.get("triage") or {}).get("specialist")
    run.status = {"executed": "executed", "declined": "declined", "failed": "failed"}.get(outcome.get("status", ""), "closed")
    run.finished_at = datetime.now(tz=timezone.utc)
    b = session.get(Break, state["break_id"])
    if b is not None and run.status == "declined":
        b.status = "open"
        b.resolution = {"kind": "declined", "agent_run_id": run.id}


def run_agent_job(session: Session, payload: dict[str, Any], paypal: PayPalClient | None) -> None:
    start_run(session, int(payload["break_id"]), paypal)


def start_run(session: Session, break_id: int, paypal: PayPalClient | None) -> AgentRun:
    b = session.get(Break, break_id)
    if b is None:
        raise RuntimeError(f"break {break_id} not found")
    existing = session.execute(
        select(AgentRun).where(AgentRun.break_id == break_id, AgentRun.status.in_(["running", "awaiting_approval"]))
    ).scalar_one_or_none()
    if existing:
        log.info("agent.run_exists", break_id=break_id, run=existing.id)
        return existing

    run = AgentRun(break_id=break_id, thread_id=str(uuid.uuid4()), model=get_settings().llm_model, status="running")
    session.add(run)
    session.flush()
    b.status = "in_progress"

    deps = GraphDeps(session, paypal, run.id)
    graph = build_graph(deps, _checkpointer())
    config = {"configurable": {"thread_id": run.thread_id}}
    try:
        final = graph.invoke({"break_id": break_id, "trace": []}, config=config)
    except Exception as exc:  # noqa: BLE001
        run.status, run.error, run.finished_at = "failed", str(exc), datetime.now(tz=timezone.utc)
        b.status = "open"
        log.error("agent.run_failed", run=run.id, error=str(exc))
        raise
    _sync_trace(session, run, graph, config, final)
    log.info("agent.run_done", run=run.id, status=run.status)
    return run


def resume_run(session: Session, approval_id: int, approved: bool, by: str, note: str | None, paypal: PayPalClient | None) -> AgentRun:
    ap = session.get(Approval, approval_id)
    if ap is None:
        raise RuntimeError("approval not found")
    if ap.status != "pending":
        raise RuntimeError(f"approval already {ap.status}")
    run = session.get(AgentRun, ap.agent_run_id)
    if run is None:
        raise RuntimeError("agent run not found")
    ap.status = "approved" if approved else "declined"
    ap.decided_by, ap.decided_at, ap.decision_note = by, datetime.now(tz=timezone.utc), note
    session.flush()

    deps = GraphDeps(session, paypal, run.id)
    graph = build_graph(deps, _checkpointer())
    config = {"configurable": {"thread_id": run.thread_id}}
    final = graph.invoke(resume_command(approved, by, note), config=config)
    _sync_trace(session, run, graph, config, final)
    return run


def _sync_trace(session: Session, run: AgentRun, graph, config, final: dict | None) -> None:
    snapshot = graph.get_state(config)
    values = snapshot.values or final or {}
    run.trace = as_jsonable(values.get("trace") or [])
    if values.get("proposal"):
        run.proposal = as_jsonable(values["proposal"])
    if values.get("triage"):
        run.specialist = values["triage"].get("specialist")
    if snapshot.next and "wait_for_human" in snapshot.next:
        run.status = "awaiting_approval"
    elif values.get("outcome"):
        run.outcome = as_jsonable(values["outcome"])
        run.status = {"executed": "executed", "declined": "declined", "failed": "failed"}.get(values["outcome"].get("status", ""), "closed")
        run.finished_at = run.finished_at or datetime.now(tz=timezone.utc)
    if snapshot.tasks:
        for t in snapshot.tasks:
            if t.interrupts:
                run.status = "awaiting_approval"
