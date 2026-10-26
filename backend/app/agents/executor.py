"""The only code path that mutates PayPal. Everything here is keyed by the approval's idempotency
key, so a retried job cannot refund twice or submit evidence twice."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.events import EventType, LedgerEvent, ResourceType
from app.domain.models import Approval, Break, Capture
from app.domain.money import Money, to_decimal_str
from app.ledger import store
from app.logging import get_logger
from app.paypal.client import PayPalClient, PayPalError

log = get_logger("agent.executor")


def execute_approval(session: Session, paypal: PayPalClient | None, approval_id: int) -> dict[str, Any]:
    ap = session.get(Approval, approval_id)
    if ap is None:
        return {"status": "failed", "error": "approval not found"}
    if ap.status == "executed":
        return {"status": "executed", "note": "already executed (idempotent)", **(ap.execution_result or {})}
    if ap.status not in ("pending", "approved"):
        return {"status": "failed", "error": f"approval in state {ap.status}"}

    p = ap.proposal
    try:
        if get_settings().paypal_dry_run and ap.action in ("refund", "provide_evidence"):
            result = _dry_run(session, ap, p)
        elif ap.action == "refund":
            result = _refund(session, paypal, ap, p)
        elif ap.action == "provide_evidence":
            result = _provide_evidence(session, paypal, ap, p)
        elif ap.action == "ledger_correction":
            result = _ledger_correction(session, ap, p)
        elif ap.action in ("no_action", "escalate"):
            result = _close_only(session, ap, p)
        else:
            raise RuntimeError(f"unknown action {ap.action}")
    except PayPalError as exc:
        ap.status = "failed"
        ap.execution_result = {"status": "failed", "error": str(exc), "paypal": exc.body}
        log.error("execute.paypal_error", approval=ap.id, action=ap.action, error=str(exc))
        return ap.execution_result
    except Exception as exc:  # noqa: BLE001
        ap.status = "failed"
        ap.execution_result = {"status": "failed", "error": str(exc)}
        log.error("execute.error", approval=ap.id, action=ap.action, error=str(exc))
        return ap.execution_result

    ap.status = "executed"
    ap.execution_result = result
    _resolve_break(session, ap.break_id, ap, result)
    log.info("execute.done", approval=ap.id, action=ap.action)
    return result


def _require_paypal(paypal: PayPalClient | None) -> PayPalClient:
    if paypal is None or not get_settings().paypal_configured:
        raise RuntimeError("PayPal is not configured; cannot execute a PayPal action")
    return paypal


def _refund(session: Session, paypal: PayPalClient | None, ap: Approval, p: dict) -> dict:
    pp = _require_paypal(paypal)
    cap = session.get(Capture, p["capture_id"]) if p.get("capture_id") else None
    if cap is None:
        raise RuntimeError("capture not in ledger; refusing to refund an unknown capture")
    amount = Money(int(p["amount_minor"]), p.get("currency") or cap.currency)
    if amount.minor > cap.amount_minor:
        raise RuntimeError("refund exceeds capture amount")
    body = pp.refund_capture(
        cap.id,
        amount.to_paypal() if amount.minor < cap.amount_minor else None,
        p.get("note_to_payer") or "Refund issued after reconciliation review.",
        request_id=ap.idempotency_key,
    )
    # Append our own view immediately; the webhook will arrive later and dedupe on a different key,
    # which the REFUND projection upserts by refund id — so no double counting.
    ev = LedgerEvent(
        event_key=LedgerEvent.key("api", body.get("id", ap.idempotency_key), f"REFUND_{body.get('status')}"),
        source="api",
        event_type=EventType.REFUND_COMPLETED if body.get("status") == "COMPLETED" else EventType.REFUND_FAILED,
        resource_type=ResourceType.REFUND,
        resource_id=body.get("id", ap.idempotency_key),
        occurred_at=datetime.now(tz=UTC),
        payload={**body, "supplementary_data": {"related_ids": {"capture_id": cap.id, "order_id": cap.order_id}}},
        amount=Money.from_paypal(body.get("amount")) or amount,
        correlation_id=cap.order_id,
    )
    store.append(session, ev)
    return {"status": "executed", "refund_id": body.get("id"), "paypal_status": body.get("status"), "amount": str(amount)}


def _provide_evidence(session: Session, paypal: PayPalClient | None, ap: Approval, p: dict) -> dict:
    pp = _require_paypal(paypal)
    dispute_id = p["dispute_id"]
    evidences = [{"evidence_type": e["evidence_type"], "notes": e["notes"][:2000]} for e in p.get("evidences") or []]
    if not evidences:
        raise RuntimeError("no evidence items in proposal")
    res = pp.provide_evidence(dispute_id, evidences, request_id=ap.idempotency_key)
    if p.get("message_to_buyer"):
        try:
            pp.send_dispute_message(dispute_id, p["message_to_buyer"], request_id=ap.idempotency_key + "-msg")
        except PayPalError as exc:  # message is best-effort
            log.warning("execute.dispute_message_failed", dispute=dispute_id, error=str(exc))
    # Record that evidence is submitted so DISPUTE_RESPONSE_DUE stops firing.
    try:
        full = pp.get_dispute(dispute_id)
    except PayPalError:
        full = {"dispute_id": dispute_id, "evidences": evidences, "status": "UNDER_REVIEW"}
    full.setdefault("evidences", evidences)
    ev = LedgerEvent(
        event_key=LedgerEvent.key("api", dispute_id, f"EVIDENCE_{ap.idempotency_key}"),
        source="api",
        event_type=EventType.DISPUTE_UPDATED,
        resource_type=ResourceType.DISPUTE,
        resource_id=dispute_id,
        occurred_at=datetime.now(tz=UTC),
        payload=full,
        amount=Money.from_paypal(full.get("dispute_amount")),
        correlation_id=p.get("order_id"),
    )
    store.append(session, ev)
    return {"status": "executed", "dispute_id": dispute_id, "evidence_count": len(evidences), "paypal": res}


def _ledger_correction(session: Session, ap: Approval, p: dict) -> dict:
    """Corrections are events too: appended, never edited in place."""
    corr = p.get("correction") or {}
    cap_id = p.get("capture_id")
    payload = {"id": cap_id, "correction": corr, "approval_id": ap.id, "reason": p.get("rationale")}
    if cap_id and corr.get("status"):
        payload["status"] = corr["status"]
    if cap_id and corr.get("amount"):
        try:
            value, cur = str(corr["amount"]).split()
            payload["amount"] = {"currency_code": cur, "value": value}
        except ValueError:
            pass
    ev = LedgerEvent(
        event_key=LedgerEvent.key("correction", cap_id or f"break{ap.break_id}", f"CORRECTION_{ap.id}"),
        source="correction",
        event_type=EventType.LEDGER_CORRECTION,
        resource_type=ResourceType.CAPTURE if cap_id else ResourceType.ORDER,
        resource_id=cap_id or (p.get("order_id") or ""),
        occurred_at=datetime.now(tz=UTC),
        payload=payload,
        amount=Money.from_paypal(payload.get("amount")),
        correlation_id=p.get("order_id"),
    )
    store.append(session, ev)
    return {"status": "executed", "correction": corr}


def _dry_run(session: Session, ap: Approval, p: dict) -> dict:
    """PAYPAL_DRY_RUN=true: record the exact call we would have made, mark the break resolved, touch
    nothing at PayPal. Used for fixture-replay demos and tests."""
    if ap.action == "refund":
        cap = session.get(Capture, p.get("capture_id") or "")
        if cap is None:
            raise RuntimeError("capture not in ledger; refusing to refund an unknown capture")
        amount = Money(int(p["amount_minor"]), p.get("currency") or cap.currency)
        if amount.minor > cap.amount_minor:
            raise RuntimeError("refund exceeds capture amount")
        call = {"method": "POST", "path": f"/v2/payments/captures/{cap.id}/refund", "body": {"amount": amount.to_paypal(), "note_to_payer": p.get("note_to_payer")}, "PayPal-Request-Id": ap.idempotency_key}
        # Mirror what the webhook would later tell us so the ledger stays consistent.
        ev = LedgerEvent(
            event_key=LedgerEvent.key("sim", f"dryrun-{ap.id}", "REFUND_COMPLETED"),
            source="sim",
            event_type=EventType.REFUND_COMPLETED,
            resource_type=ResourceType.REFUND,
            resource_id=f"DRYRUN-REF-{ap.id}",
            occurred_at=datetime.now(tz=UTC),
            payload={"id": f"DRYRUN-REF-{ap.id}", "status": "COMPLETED", "amount": amount.to_paypal(), "supplementary_data": {"related_ids": {"capture_id": cap.id, "order_id": cap.order_id}}},
            amount=amount,
            correlation_id=cap.order_id,
        )
        store.append(session, ev)
        return {"status": "executed", "dry_run": True, "would_call": call, "amount": str(amount)}
    if ap.action == "provide_evidence":
        evidences = [{"evidence_type": e["evidence_type"], "notes": e["notes"][:2000]} for e in p.get("evidences") or []]
        call = {"method": "POST", "path": f"/v1/customer/disputes/{p.get('dispute_id')}/provide-evidence", "body": {"evidences": evidences}, "PayPal-Request-Id": ap.idempotency_key}
        ev = LedgerEvent(
            event_key=LedgerEvent.key("sim", p.get("dispute_id") or f"dryrun-{ap.id}", f"EVIDENCE_{ap.idempotency_key}"),
            source="sim",
            event_type=EventType.DISPUTE_UPDATED,
            resource_type=ResourceType.DISPUTE,
            resource_id=p.get("dispute_id") or "",
            occurred_at=datetime.now(tz=UTC),
            payload={"dispute_id": p.get("dispute_id"), "status": "UNDER_REVIEW", "evidences": evidences},
            correlation_id=p.get("order_id"),
        )
        store.append(session, ev)
        return {"status": "executed", "dry_run": True, "would_call": call, "evidence_count": len(evidences)}
    raise RuntimeError("dry run not supported for this action")


def _close_only(session: Session, ap: Approval, p: dict) -> dict:
    return {"status": "executed", "action": ap.action, "summary": p.get("escalation_summary") or p.get("rationale")}


def _resolve_break(session: Session, break_id: int, ap: Approval, result: dict) -> None:
    b = session.get(Break, break_id)
    if b is None:
        return
    if ap.action == "escalate":
        b.status = "in_progress"
        b.resolution = {"kind": "escalated", "approval_id": ap.id, "summary": result.get("summary")}
        return
    b.status = "resolved"
    b.resolved_at = datetime.now(tz=UTC)
    b.resolution = {"kind": ap.action, "approval_id": ap.id, "by": ap.decided_by or "policy:auto", **{k: v for k, v in result.items() if k != "paypal"}}


def fmt(minor: int, cur: str) -> str:
    return f"{to_decimal_str(minor, cur)} {cur}"
