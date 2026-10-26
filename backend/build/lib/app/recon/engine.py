"""Turns rule findings into ``breaks`` rows. Idempotent by fingerprint; auto-resolves breaks whose
rule no longer fires. Can run over the whole ledger or a single order chain."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.models import (
    Authorization,
    Break,
    Capture,
    Dispute,
    Invoice,
    Order,
    PayoutItem,
    Refund,
    Transaction,
)
from app.logging import get_logger
from app.recon.rules import RULES, Finding, Scope

log = get_logger("recon")


def load_scope(session: Session, correlation_id: str | None = None, resource: tuple[str, str] | None = None) -> Scope:
    """Load projections. With a correlation id, load just that chain plus anything referencing it."""

    def _all(model):
        return {r.id: r for r in session.execute(select(model)).scalars()}

    if correlation_id is None:
        return Scope(
            now=datetime.now(tz=UTC),
            orders=_all(Order),
            captures=_all(Capture),
            refunds=_all(Refund),
            authorizations=_all(Authorization),
            payout_items=_all(PayoutItem),
            disputes=_all(Dispute),
            invoices=_all(Invoice),
            transactions=_all(Transaction),
        )

    orders = {r.id: r for r in session.execute(select(Order).where(Order.id == correlation_id)).scalars()}
    captures = {r.id: r for r in session.execute(select(Capture).where(Capture.order_id == correlation_id)).scalars()}
    cap_ids = list(captures.keys())
    refunds = {
        r.id: r
        for r in session.execute(
            select(Refund).where(or_(Refund.order_id == correlation_id, Refund.capture_id.in_(cap_ids or [""])))
        ).scalars()
    }
    auths = {r.id: r for r in session.execute(select(Authorization).where(Authorization.order_id == correlation_id)).scalars()}
    disputes = {
        r.id: r
        for r in session.execute(
            select(Dispute).where(or_(Dispute.order_id == correlation_id, Dispute.transaction_id.in_(cap_ids or [""])))
        ).scalars()
    }
    txs = {r.id: r for r in session.execute(select(Transaction).where(Transaction.id.in_(cap_ids or [""]))).scalars()}
    scope = Scope(
        now=datetime.now(tz=UTC),
        orders=orders,
        captures=captures,
        refunds=refunds,
        authorizations=auths,
        payout_items={},
        disputes=disputes,
        invoices={},
        transactions=txs,
    )
    # A resource outside an order chain (payout item, invoice, dispute without order): load it directly.
    if resource:
        rtype, rid = resource
        if rtype == "payout_item" and (p := session.get(PayoutItem, rid)):
            scope.payout_items[rid] = p
        if rtype == "payout_batch":
            for p in session.execute(select(PayoutItem).where(PayoutItem.batch_id == rid)).scalars():
                scope.payout_items[p.id] = p
        if rtype == "invoice" and (i := session.get(Invoice, rid)):
            scope.invoices[rid] = i
        if rtype == "dispute" and (d := session.get(Dispute, rid)):
            scope.disputes[rid] = d
            if d.transaction_id and (c := session.get(Capture, d.transaction_id)):
                scope.captures[c.id] = c
        if rtype == "transaction" and (t := session.get(Transaction, rid)):
            scope.transactions[rid] = t
            if c := session.get(Capture, rid):
                scope.captures[c.id] = c
    # Duplicate-order detection needs the customer's other orders for the same amount.
    for o in list(scope.orders.values()):
        ident_filters = [f for f in (
            Order.payer_id == o.payer_id if o.payer_id else None,
            Order.payer_email == o.payer_email if o.payer_email else None,
            Order.custom_id == o.custom_id if o.custom_id else None,
        ) if f is not None]
        if not ident_filters:
            continue
        for sib in session.execute(
            select(Order).where(or_(*ident_filters), Order.amount_minor == o.amount_minor, Order.id != o.id)
        ).scalars():
            scope.orders[sib.id] = sib
            for c in session.execute(select(Capture).where(Capture.order_id == sib.id)).scalars():
                scope.captures[c.id] = c
            for r in session.execute(select(Refund).where(Refund.order_id == sib.id)).scalars():
                scope.refunds[r.id] = r
    # Every capture in scope brings its order (and that order's other captures/refunds), so
    # order-level rules see the whole chain rather than a fragment.
    for c in list(scope.captures.values()):
        if c.order_id and c.order_id not in scope.orders and (o := session.get(Order, c.order_id)):
            scope.orders[o.id] = o
            for sib in session.execute(select(Capture).where(Capture.order_id == o.id)).scalars():
                scope.captures[sib.id] = sib
            for r in session.execute(select(Refund).where(Refund.order_id == o.id)).scalars():
                scope.refunds[r.id] = r
    return scope


def run_rules(scope: Scope, only: set[str] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for name, fn in RULES:
        if only and name not in only:
            continue
        try:
            findings.extend(fn(scope))
        except Exception as exc:  # noqa: BLE001 - one bad rule must not stop the pass
            log.error("recon.rule_error", rule=name, error=str(exc))
    return findings


def persist(session: Session, findings: list[Finding], scoped_resources: set[tuple[str, str]] | None) -> list[Break]:
    """Upsert findings as breaks; auto-resolve open breaks in scope that no longer fire.

    Returns the breaks that are *new* this pass (so callers can dispatch agents once).
    """
    now = datetime.now(tz=UTC)
    seen = {f.fingerprint for f in findings}
    new: list[Break] = []
    for f in findings:
        row = session.execute(select(Break).where(Break.fingerprint == f.fingerprint)).scalar_one_or_none()
        if row is None:
            row = Break(
                fingerprint=f.fingerprint,
                rule=f.rule,
                severity=f.severity,
                resource_type=f.resource_type,
                resource_id=f.resource_id,
                correlation_id=f.correlation_id,
                title=f.title,
                expected=f.expected,
                observed=f.observed,
                delta_minor=f.delta_minor,
                currency=f.currency,
            )
            session.add(row)
            session.flush()
            new.append(row)
            log.info("recon.break_opened", rule=f.rule, resource=f.resource_id, severity=f.severity)
        else:
            row.title, row.expected, row.observed = f.title, f.expected, f.observed
            row.delta_minor, row.last_seen_at = f.delta_minor, now
            sticky = {"dismissed", "no_action", "escalated"}  # a human/agent judged it; don't nag
            if row.status == "resolved" and row.resolution and row.resolution.get("kind") not in sticky:
                # It came back: reopen.
                row.status, row.resolved_at, row.resolution = "open", None, None
                new.append(row)
                log.info("recon.break_reopened", rule=f.rule, resource=f.resource_id)

    # Auto-resolve: open breaks in scope whose fingerprint did not fire this pass.
    q = select(Break).where(Break.status.in_(["open", "in_progress", "awaiting_approval"]))
    for row in session.execute(q).scalars():
        in_scope = scoped_resources is None or (row.resource_type, row.resource_id) in scoped_resources
        if in_scope and row.fingerprint not in seen:
            row.status, row.resolved_at = "resolved", now
            row.resolution = {"kind": "auto", "note": "rule no longer fires after new events"}
            log.info("recon.break_resolved", rule=row.rule, resource=row.resource_id)
    return new


def reconcile(session: Session, correlation_id: str | None, resource: tuple[str, str] | None = None) -> list[Break]:
    scope = load_scope(session, correlation_id, resource)
    findings = run_rules(scope)
    scoped: set[tuple[str, str]] = set()
    for model_dict, rtype in (
        (scope.orders, "order"),
        (scope.captures, "capture"),
        (scope.refunds, "refund"),
        (scope.authorizations, "authorization"),
        (scope.payout_items, "payout_item"),
        (scope.disputes, "dispute"),
        (scope.invoices, "invoice"),
    ):
        scoped.update((rtype, rid) for rid in model_dict)
    return persist(session, findings, scoped if correlation_id or resource else None)


def reconcile_all(session: Session) -> list[Break]:
    return reconcile(session, correlation_id=None, resource=None)
