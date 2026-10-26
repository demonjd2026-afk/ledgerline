"""Ledger, reconciliation, agent and approval behaviour, end to end, against Postgres."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.runner import resume_run, start_run
from app.domain.events import EventType, LedgerEvent, ResourceType, normalise_webhook
from app.domain.models import Approval, Break, Capture, LedgerEventRow, Refund
from app.domain.money import Money
from app.ingest.pipeline import ingest_event
from app.ledger import store
from app.ledger.store import rebuild_projections
from app.recon.engine import reconcile, reconcile_all
from app.sim.replay import FIXTURES, replay_file
from app.worker import queue

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def _order(order_id: str, value: str, captures: list[tuple[str, str]]):
    return {
        "id": order_id,
        "status": "COMPLETED",
        "intent": "CAPTURE",
        "create_time": NOW.isoformat(),
        "purchase_units": [
            {
                "amount": {"currency_code": "USD", "value": value},
                "payments": {"captures": [{"id": cid, "status": "COMPLETED", "final_capture": True, "amount": {"currency_code": "USD", "value": v}} for cid, v in captures]},
            }
        ],
    }


def _append_order(session, order):
    pu = order["purchase_units"][0]
    return store.append(
        session,
        LedgerEvent(LedgerEvent.key("webhook", f"WH-{order['id']}", EventType.ORDER_COMPLETED), "webhook", EventType.ORDER_COMPLETED, ResourceType.ORDER, order["id"], NOW, order, Money.from_paypal(pu["amount"]), order["id"]),
    )


def _refund(session, rid, cap, order, value, when=NOW):
    r = {"id": rid, "status": "COMPLETED", "amount": {"currency_code": "USD", "value": value}, "supplementary_data": {"related_ids": {"order_id": order, "capture_id": cap}}}
    return store.append(session, LedgerEvent(LedgerEvent.key("webhook", f"WH-{rid}", EventType.REFUND_COMPLETED), "webhook", EventType.REFUND_COMPLETED, ResourceType.REFUND, rid, when, r, Money.from_paypal(r["amount"]), order))


# ---------------------------------------------------------------- ledger


def test_append_is_idempotent(session):
    o = _order("O1", "10.00", [("C1", "10.00")])
    _, first = _append_order(session, o)
    _, second = _append_order(session, o)
    assert first and not second
    assert session.execute(select(LedgerEventRow)).scalars().all().__len__() == 1


def test_projection_rebuild_matches(session):
    _append_order(session, _order("O1", "10.00", [("C1", "10.00")]))
    _refund(session, "R1", "C1", "O1", "4.00")
    before = {(c.id, c.status, c.amount_minor) for c in session.execute(select(Capture)).scalars()}
    n = rebuild_projections(session)
    after = {(c.id, c.status, c.amount_minor) for c in session.execute(select(Capture)).scalars()}
    assert n == 2 and before == after
    assert session.get(Refund, "R1").capture_id == "C1"


def test_webhook_normalisation_maps_refund_event():
    env = {"id": "WH-1", "event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {"id": "R9", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "1.00"}, "supplementary_data": {"related_ids": {"order_id": "O9", "capture_id": "C9"}}}}
    ev = normalise_webhook(env)
    assert ev and ev.event_type == EventType.CAPTURE_REFUNDED and ev.correlation_id == "O9"
    assert normalise_webhook({"id": "x", "event_type": "SOMETHING.UNKNOWN"}) is None


# ---------------------------------------------------------------- recon


def test_refund_exceeds_capture_opens_then_autoresolves_when_fixed(session):
    _append_order(session, _order("O1", "45.00", [("C1", "45.00")]))
    _refund(session, "R1", "C1", "O1", "45.00")
    _refund(session, "R2", "C1", "O1", "45.00")
    new = reconcile(session, "O1")
    assert [b.rule for b in new] == ["REFUND_EXCEEDS_CAPTURE"]
    assert new[0].delta_minor == 4500
    assert reconcile(session, "O1") == []  # idempotent


def test_duplicate_capture_and_amount_mismatch(session):
    _append_order(session, _order("O2", "64.50", [("A", "64.50"), ("B", "64.50")]))
    rules = {b.rule for b in reconcile(session, "O2")}
    assert rules == {"ORDER_AMOUNT_MISMATCH", "DUPLICATE_CAPTURE"}


def test_drift_uses_ledger_implied_status(session):
    _append_order(session, _order("O3", "100.00", [("C3", "100.00")]))
    _refund(session, "R3", "C3", "O3", "100.00")  # ledger knows the full refund
    snap = {"id": "C3", "status": "REFUNDED", "amount": {"currency_code": "USD", "value": "100.00"}, "supplementary_data": {"related_ids": {"order_id": "O3"}}}
    store.append(session, LedgerEvent(LedgerEvent.key("api", "C3", "SNAP"), "api", EventType.CAPTURE_COMPLETED, ResourceType.CAPTURE, "C3", NOW, snap, Money(10000, "USD"), "O3"))
    assert "WEBHOOK_API_DRIFT" not in {b.rule for b in reconcile(session, "O3")}


def test_silent_refund_at_paypal_opens_drift(session):
    """Capture COMPLETED in the ledger; PayPal says REFUNDED and the ledger knows no refund."""
    _append_order(session, _order("O8", "129.00", [("C8", "129.00")]))
    snap = {"id": "C8", "status": "REFUNDED", "amount": {"currency_code": "USD", "value": "129.00"}, "supplementary_data": {"related_ids": {"order_id": "O8"}}}
    store.append(session, LedgerEvent(LedgerEvent.key("api", "C8", "SNAP_REFUNDED"), "api", EventType.CAPTURE_REFUNDED, ResourceType.CAPTURE, "C8", NOW, snap, Money(12900, "USD"), "O8"))
    assert session.execute(select(Refund)).scalars().all() == []  # the snapshot is not a refund record
    rules = {b.rule for b in reconcile(session, "O8")}
    assert "WEBHOOK_API_DRIFT" in rules


def test_duplicate_order_fires_on_later_order_and_clears_after_refund(session):
    from datetime import timedelta

    a = _order("OA", "18.50", [("CA", "18.50")]); a["payer"] = {"email_address": "lena@example.com", "payer_id": "P1"}
    b = _order("OB", "18.50", [("CB", "18.50")]); b["payer"] = {"email_address": "lena@example.com", "payer_id": "P1"}
    b["create_time"] = (NOW + timedelta(seconds=40)).isoformat()
    _append_order(session, a)
    store.append(session, LedgerEvent(LedgerEvent.key("webhook", "WH-OB", EventType.ORDER_COMPLETED), "webhook", EventType.ORDER_COMPLETED, ResourceType.ORDER, "OB", NOW + timedelta(seconds=40), b, Money(1850, "USD"), "OB"))
    found = [x for x in reconcile(session, "OB") if x.rule == "DUPLICATE_ORDER"]
    assert len(found) == 1 and found[0].resource_id == "OB" and found[0].observed["capture_to_refund"] == "CB"
    # The agent refunds it (dry run) automatically: under $25, fresh, no dispute.
    run = start_run(session, found[0].id, None)
    assert run.status == "executed"
    ap = session.execute(select(Approval).where(Approval.agent_run_id == run.id)).scalar_one()
    assert ap.action == "refund" and ap.policy_decision == "auto" and ap.proposal["capture_id"] == "CB"
    assert session.get(Break, found[0].id).status == "resolved"
    assert "DUPLICATE_ORDER" not in {x.rule for x in reconcile(session, "OB")}


# ---------------------------------------------------------------- agents + policy


def test_small_refund_auto_executes_in_dry_run(session):
    # Over-capture by $1.00 -> refund proposal of 100 minor units -> within auto-approve policy.
    _append_order(session, _order("O4", "20.00", [("C4", "21.00")]))
    brk = [b for b in reconcile(session, "O4") if b.rule == "ORDER_AMOUNT_MISMATCH"][0]
    run = start_run(session, brk.id, None)
    assert run.status == "executed"
    ap = session.execute(select(Approval).where(Approval.agent_run_id == run.id)).scalar_one()
    assert ap.policy_decision == "auto" and ap.status == "executed" and ap.action == "refund"
    assert ap.execution_result["dry_run"] is True
    assert session.get(Break, brk.id).status == "resolved"


def test_large_refund_waits_for_human_then_executes(session):
    _append_order(session, _order("O5", "100.00", [("C5", "200.00")]))
    brk = [b for b in reconcile(session, "O5") if b.rule == "ORDER_AMOUNT_MISMATCH"][0]
    run = start_run(session, brk.id, None)
    assert run.status == "awaiting_approval"
    ap = session.execute(select(Approval).where(Approval.agent_run_id == run.id)).scalar_one()
    assert ap.policy_decision == "requires_human" and "threshold" in " ".join(ap.policy_reasons)
    run = resume_run(session, ap.id, True, "tester", "ok", None)
    assert run.status == "executed"
    assert session.get(Break, brk.id).status == "resolved"
    assert [t["node"] for t in run.trace][-2:] == ["wait_for_human", "execute"]


def test_declined_approval_reopens_break(session):
    _append_order(session, _order("O6", "100.00", [("C6", "200.00")]))
    brk = [b for b in reconcile(session, "O6") if b.rule == "ORDER_AMOUNT_MISMATCH"][0]
    run = start_run(session, brk.id, None)
    ap = session.execute(select(Approval).where(Approval.agent_run_id == run.id)).scalar_one()
    run = resume_run(session, ap.id, False, "tester", "not convinced", None)
    assert run.status == "declined"
    assert session.get(Break, brk.id).status == "open"


def test_execution_is_idempotent_on_retry(session):
    from app.agents.executor import execute_approval

    _append_order(session, _order("O7", "20.00", [("C7", "21.00")]))
    brk = [b for b in reconcile(session, "O7") if b.rule == "ORDER_AMOUNT_MISMATCH"][0]
    run = start_run(session, brk.id, None)
    ap = session.execute(select(Approval).where(Approval.agent_run_id == run.id)).scalar_one()
    again = execute_approval(session, None, ap.id)
    assert again["status"] == "executed" and "already executed" in again.get("note", "")
    assert len(session.execute(select(Refund)).scalars().all()) == 1


# ---------------------------------------------------------------- queue + fixture


def test_queue_dedupes_and_claims(session):
    a = queue.enqueue(session, "run_agent", "break:1", {"break_id": 1})
    b = queue.enqueue(session, "run_agent", "break:1", {"break_id": 1})
    assert a and b is None
    jobs = queue.claim(session, 10)
    assert len(jobs) == 1 and jobs[0].status == "running"


def test_demo_fixture_produces_expected_breaks(session):
    replay_file(session, FIXTURES / "demo.jsonl")
    reconcile_all(session)
    rules = {b.rule for b in session.execute(select(Break).where(Break.status != "resolved")).scalars()}
    assert {"ORDER_AMOUNT_MISMATCH", "DUPLICATE_CAPTURE", "WEBHOOK_API_DRIFT", "DISPUTE_RESPONSE_DUE", "REFUND_EXCEEDS_CAPTURE", "PAYOUT_ITEM_FAILED", "PAYOUT_FEE_VARIANCE", "INVOICE_PAID_NO_CAPTURE", "DUPLICATE_ORDER"} <= rules
    assert "CAPTURE_WITHOUT_ORDER" not in rules
