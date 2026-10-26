"""Tools the LLM may call. All read-only. Mutations happen in the executor after the policy gate.

Ledger tools answer from our own tables; PayPal tools hit the live sandbox so the agent can
see the counterparty's view. Every call is recorded in the run trace by the graph.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.domain.models import Capture, Dispute, Order, Refund, Transaction
from app.domain.money import to_decimal_str
from app.ledger import store
from app.paypal.client import PayPalClient, PayPalError


def _money(minor: int | None, cur: str | None) -> str | None:
    return f"{to_decimal_str(minor, cur)} {cur}" if minor is not None and cur else None


def _row(obj: Any) -> dict:
    d = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    for k in ("amount_minor", "fee_minor", "net_minor", "paid_amount_minor", "api_amount_minor"):
        if k in d and d[k] is not None:
            d[k.replace("_minor", "")] = _money(d[k], d.get("currency"))
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()}


def build_tools(session: Session, paypal: PayPalClient | None) -> list:
    @tool
    def ledger_order_chain(order_id: str) -> str:
        """Return the order, its captures, refunds and disputes from Ledgerline's own ledger, plus the
        ordered event history. Use this first; it is the merchant's record."""
        order = session.get(Order, order_id)
        caps = session.query(Capture).filter(Capture.order_id == order_id).all()
        refs = session.query(Refund).filter(Refund.order_id == order_id).all()
        disputes = session.query(Dispute).filter(Dispute.order_id == order_id).all()
        events = store.chain(session, order_id)
        return json.dumps(
            {
                "order": _row(order) if order else None,
                "captures": [_row(c) for c in caps],
                "refunds": [_row(r) for r in refs],
                "disputes": [_row(d) for d in disputes],
                "events": [
                    {"at": e.occurred_at.isoformat(), "type": e.event_type, "source": e.source, "resource": e.resource_id}
                    for e in events
                ],
            },
            default=str,
        )

    @tool
    def ledger_capture(capture_id: str) -> str:
        """Return a capture and its refunds from the ledger, including the last status PayPal's API reported."""
        cap = session.get(Capture, capture_id)
        refs = session.query(Refund).filter(Refund.capture_id == capture_id).all()
        tx = session.get(Transaction, capture_id)
        return json.dumps({"capture": _row(cap) if cap else None, "refunds": [_row(r) for r in refs], "settled_transaction": _row(tx) if tx else None}, default=str)

    @tool
    def ledger_dispute(dispute_id: str) -> str:
        """Return a dispute from the ledger with the raw PayPal dispute payload from the latest event."""
        d = session.get(Dispute, dispute_id)
        events = store.events_for_resource(session, "dispute", dispute_id)
        raw = events[-1].payload if events else None
        return json.dumps({"dispute": _row(d) if d else None, "raw": raw}, default=str)

    @tool
    def paypal_get_order(order_id: str) -> str:
        """Fetch the order from PayPal's Orders API — PayPal's current view, to compare against the ledger."""
        return _pp(lambda: paypal.get_order(order_id))

    @tool
    def paypal_get_capture(capture_id: str) -> str:
        """Fetch a capture from PayPal's Payments API, including seller_receivable_breakdown and status."""
        return _pp(lambda: paypal.get_capture(capture_id))

    @tool
    def paypal_get_dispute(dispute_id: str) -> str:
        """Fetch a dispute from PayPal's Disputes API: reason, stage, due date, evidence requested, messages."""
        return _pp(lambda: paypal.get_dispute(dispute_id))

    @tool
    def paypal_get_refund(refund_id: str) -> str:
        """Fetch a refund from PayPal's Payments API."""
        return _pp(lambda: paypal.get_refund(refund_id))

    def _pp(fn) -> str:
        if paypal is None:
            return json.dumps({"error": "PayPal client not configured in this environment"})
        try:
            return json.dumps(fn(), default=str)
        except PayPalError as exc:
            return json.dumps({"error": str(exc), "status": exc.status, "body": exc.body}, default=str)

    return [ledger_order_chain, ledger_capture, ledger_dispute, paypal_get_order, paypal_get_capture, paypal_get_dispute, paypal_get_refund]
