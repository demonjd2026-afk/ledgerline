"""Reconciliation rules. Each rule is a pure function over a loaded ``Scope``.

A rule returns ``Finding``s; the engine turns findings into ``breaks`` rows keyed by
fingerprint, so re-running never duplicates and a fixed break resolves automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.config import get_settings
from app.domain.models import Authorization, Capture, Dispute, Invoice, Order, PayoutItem, Refund, Transaction
from app.domain.money import to_decimal_str

Severity = str  # info | warn | critical


@dataclass(slots=True)
class Finding:
    rule: str
    severity: Severity
    resource_type: str
    resource_id: str
    title: str
    expected: dict[str, Any] = field(default_factory=dict)
    observed: dict[str, Any] = field(default_factory=dict)
    delta_minor: int | None = None
    currency: str | None = None
    correlation_id: str | None = None

    @property
    def fingerprint(self) -> str:
        return f"{self.rule}:{self.resource_type}:{self.resource_id}"


@dataclass(slots=True)
class Scope:
    """Everything a rule may look at. Loaded once per reconcile pass."""

    now: datetime
    orders: dict[str, Order]
    captures: dict[str, Capture]
    refunds: dict[str, Refund]
    authorizations: dict[str, Authorization]
    payout_items: dict[str, PayoutItem]
    disputes: dict[str, Dispute]
    invoices: dict[str, Invoice]
    transactions: dict[str, Transaction]

    def captures_for(self, order_id: str) -> list[Capture]:
        return [c for c in self.captures.values() if c.order_id == order_id]

    def refunds_for_capture(self, capture_id: str) -> list[Refund]:
        return [r for r in self.refunds.values() if r.capture_id == capture_id]

    def refunds_for_order(self, order_id: str) -> list[Refund]:
        return [r for r in self.refunds.values() if r.order_id == order_id]

    def disputes_for_capture(self, capture_id: str) -> list[Dispute]:
        return [d for d in self.disputes.values() if d.transaction_id == capture_id]


Rule = Callable[[Scope], list[Finding]]
RULES: list[tuple[str, Rule]] = []


def rule(name: str):
    def deco(fn: Rule):
        RULES.append((name, fn))
        return fn

    return deco


def _fmt(minor: int, cur: str) -> str:
    return f"{to_decimal_str(minor, cur)} {cur}"


# ------------------------------------------------------------------ order / capture


@rule("ORDER_AMOUNT_MISMATCH")
def order_amount_mismatch(s: Scope) -> list[Finding]:
    out = []
    for o in s.orders.values():
        if o.status != "COMPLETED":
            continue
        caps = [c for c in s.captures_for(o.id) if c.status in ("COMPLETED", "PENDING", "PARTIALLY_REFUNDED", "REFUNDED")]
        if not caps:
            continue
        total = sum(c.amount_minor for c in caps)
        if total != o.amount_minor:
            out.append(
                Finding(
                    rule="ORDER_AMOUNT_MISMATCH",
                    severity="critical",
                    resource_type="order",
                    resource_id=o.id,
                    correlation_id=o.id,
                    title=f"Order {o.id}: captured {_fmt(total, o.currency)} vs order {_fmt(o.amount_minor, o.currency)}",
                    expected={"order_amount": _fmt(o.amount_minor, o.currency)},
                    observed={"captured_total": _fmt(total, o.currency), "captures": [c.id for c in caps]},
                    delta_minor=total - o.amount_minor,
                    currency=o.currency,
                )
            )
    return out


@rule("DUPLICATE_CAPTURE")
def duplicate_capture(s: Scope) -> list[Finding]:
    out = []
    for o in s.orders.values():
        caps = [c for c in s.captures_for(o.id) if c.status in ("COMPLETED", "PENDING") and c.final_capture]
        if len(caps) > 1:
            total = sum(c.amount_minor for c in caps)
            out.append(
                Finding(
                    rule="DUPLICATE_CAPTURE",
                    severity="critical",
                    resource_type="order",
                    resource_id=o.id,
                    correlation_id=o.id,
                    title=f"Order {o.id} has {len(caps)} final captures",
                    expected={"final_captures": 1},
                    observed={"final_captures": len(caps), "captures": [c.id for c in caps]},
                    delta_minor=total - o.amount_minor,
                    currency=o.currency,
                )
            )
    return out


@rule("CAPTURE_WITHOUT_ORDER")
def capture_without_order(s: Scope) -> list[Finding]:
    out = []
    for c in s.captures.values():
        if c.order_id and c.order_id not in s.orders:
            out.append(
                Finding(
                    rule="CAPTURE_WITHOUT_ORDER",
                    severity="warn",
                    resource_type="capture",
                    resource_id=c.id,
                    correlation_id=c.order_id,
                    title=f"Capture {c.id} references unknown order {c.order_id}",
                    expected={"order_in_ledger": True},
                    observed={"order_id": c.order_id, "amount": _fmt(c.amount_minor, c.currency)},
                    currency=c.currency,
                )
            )
    return out


@rule("REFUND_EXCEEDS_CAPTURE")
def refund_exceeds_capture(s: Scope) -> list[Finding]:
    out = []
    for c in s.captures.values():
        refs = [r for r in s.refunds_for_capture(c.id) if r.status in ("COMPLETED", "PENDING")]
        total = sum(r.amount_minor for r in refs)
        if total > c.amount_minor:
            out.append(
                Finding(
                    rule="REFUND_EXCEEDS_CAPTURE",
                    severity="critical",
                    resource_type="capture",
                    resource_id=c.id,
                    correlation_id=c.order_id,
                    title=f"Refunds {_fmt(total, c.currency)} exceed capture {_fmt(c.amount_minor, c.currency)}",
                    expected={"max_refundable": _fmt(c.amount_minor, c.currency)},
                    observed={"refunded_total": _fmt(total, c.currency), "refunds": [r.id for r in refs]},
                    delta_minor=total - c.amount_minor,
                    currency=c.currency,
                )
            )
    return out


@rule("WEBHOOK_API_DRIFT")
def webhook_api_drift(s: Scope) -> list[Finding]:
    """Ledger (webhook-derived) status/amount disagrees with what the API/poll last said."""
    out = []
    for c in s.captures.values():
        if not c.api_status:
            continue
        # What the ledger *implies* the capture status is, given the refunds it knows about.
        refunded = sum(r.amount_minor for r in s.refunds_for_capture(c.id) if r.status in ("COMPLETED", "PENDING"))
        implied = c.status
        if c.status == "COMPLETED" and refunded >= c.amount_minor > 0:
            implied = "REFUNDED"
        elif c.status == "COMPLETED" and refunded > 0:
            implied = "PARTIALLY_REFUNDED"
        status_ok = implied == c.api_status
        amount_ok = c.api_amount_minor is None or c.api_amount_minor == c.amount_minor
        if status_ok and amount_ok:
            continue
        out.append(
            Finding(
                rule="WEBHOOK_API_DRIFT",
                severity="critical",
                resource_type="capture",
                resource_id=c.id,
                correlation_id=c.order_id,
                title=f"Capture {c.id}: ledger implies {implied}/{_fmt(c.amount_minor, c.currency)}, PayPal says {c.api_status}/{_fmt(c.api_amount_minor or c.amount_minor, c.currency)}",
                expected={"status": c.api_status, "amount": _fmt(c.api_amount_minor or c.amount_minor, c.currency), "source": "paypal_api"},
                observed={"status": implied, "raw_status": c.status, "amount": _fmt(c.amount_minor, c.currency), "refunded": _fmt(refunded, c.currency), "source": "ledger"},
                delta_minor=(c.amount_minor - (c.api_amount_minor or c.amount_minor)),
                currency=c.currency,
            )
        )
    return out


@rule("STALE_AUTHORIZATION")
def stale_authorization(s: Scope) -> list[Finding]:
    days = get_settings().stale_auth_days
    out = []
    for a in s.authorizations.values():
        if a.status not in ("CREATED", "PENDING"):
            continue
        age = s.now - a.created_at
        if age > timedelta(days=days):
            out.append(
                Finding(
                    rule="STALE_AUTHORIZATION",
                    severity="warn",
                    resource_type="authorization",
                    resource_id=a.id,
                    correlation_id=a.order_id,
                    title=f"Authorization {a.id} is {age.days}d old with no capture or void",
                    expected={"captured_or_voided_within_days": days},
                    observed={"age_days": age.days, "amount": _fmt(a.amount_minor, a.currency)},
                    currency=a.currency,
                )
            )
    return out


# ------------------------------------------------------------------ disputes


@rule("DISPUTE_RESPONSE_DUE")
def dispute_response_due(s: Scope) -> list[Finding]:
    sla = timedelta(hours=get_settings().dispute_sla_hours)
    out = []
    for d in s.disputes.values():
        if d.status not in ("WAITING_FOR_SELLER_RESPONSE", "OPEN", "UNDER_REVIEW"):
            continue
        if d.evidence_submitted:
            continue
        due = d.seller_response_due
        overdue = due is not None and due < s.now
        inside_sla = due is not None and due - s.now <= sla
        if due is None or inside_sla or overdue:
            out.append(
                Finding(
                    rule="DISPUTE_RESPONSE_DUE",
                    severity="critical",
                    resource_type="dispute",
                    resource_id=d.id,
                    correlation_id=d.order_id or d.transaction_id,
                    title=f"Dispute {d.id} ({d.reason}) needs a seller response"
                    + (f" by {due.isoformat()}" if due else ""),
                    expected={"evidence_submitted": True},
                    observed={
                        "status": d.status,
                        "reason": d.reason,
                        "stage": d.stage,
                        "due": due.isoformat() if due else None,
                        "overdue": overdue,
                        "amount": _fmt(d.amount_minor, d.currency),
                    },
                    delta_minor=-d.amount_minor,
                    currency=d.currency,
                )
            )
    return out


@rule("DISPUTE_UNRECONCILED_HOLD")
def dispute_unreconciled_hold(s: Scope) -> list[Finding]:
    out = []
    for d in s.disputes.values():
        if d.status in ("RESOLVED",) or not d.transaction_id:
            continue
        cap = s.captures.get(d.transaction_id)
        if cap is None:
            out.append(
                Finding(
                    rule="DISPUTE_UNRECONCILED_HOLD",
                    severity="warn",
                    resource_type="dispute",
                    resource_id=d.id,
                    correlation_id=d.order_id,
                    title=f"Dispute {d.id} references transaction {d.transaction_id} not in ledger",
                    expected={"capture_in_ledger": True},
                    observed={"transaction_id": d.transaction_id, "amount": _fmt(d.amount_minor, d.currency)},
                    currency=d.currency,
                )
            )
        elif d.amount_minor > cap.amount_minor:
            out.append(
                Finding(
                    rule="DISPUTE_UNRECONCILED_HOLD",
                    severity="warn",
                    resource_type="dispute",
                    resource_id=d.id,
                    correlation_id=cap.order_id,
                    title=f"Dispute {d.id} amount exceeds captured amount",
                    expected={"max": _fmt(cap.amount_minor, cap.currency)},
                    observed={"disputed": _fmt(d.amount_minor, d.currency)},
                    delta_minor=d.amount_minor - cap.amount_minor,
                    currency=d.currency,
                )
            )
    return out


# ------------------------------------------------------------------ payouts


@rule("PAYOUT_ITEM_FAILED")
def payout_item_failed(s: Scope) -> list[Finding]:
    out = []
    for p in s.payout_items.values():
        if p.status in ("FAILED", "BLOCKED", "RETURNED", "UNCLAIMED", "REFUNDED", "REVERSED", "DENIED"):
            out.append(
                Finding(
                    rule="PAYOUT_ITEM_FAILED",
                    severity="warn",
                    resource_type="payout_item",
                    resource_id=p.id,
                    correlation_id=p.batch_id,
                    title=f"Payout item {p.id} to {p.receiver or '?'} is {p.status}",
                    expected={"status": "SUCCESS"},
                    observed={"status": p.status, "amount": _fmt(p.amount_minor, p.currency), "receiver": p.receiver},
                    delta_minor=p.amount_minor,
                    currency=p.currency,
                )
            )
    return out


@rule("PAYOUT_FEE_VARIANCE")
def payout_fee_variance(s: Scope) -> list[Finding]:
    band = get_settings().payout_fee_band_bps
    out = []
    for p in s.payout_items.values():
        if p.fee_minor is None or p.status != "SUCCESS":
            continue
        # PayPal Payouts fee: 2% capped at a currency-specific max; we check the ratio band only.
        expected = min(round(p.amount_minor * 0.02), 2000 if p.currency == "USD" else p.amount_minor)
        tolerance = max(1, round(expected * band / 10_000))
        if abs(p.fee_minor - expected) > tolerance:
            out.append(
                Finding(
                    rule="PAYOUT_FEE_VARIANCE",
                    severity="info",
                    resource_type="payout_item",
                    resource_id=p.id,
                    correlation_id=p.batch_id,
                    title=f"Payout fee {_fmt(p.fee_minor, p.currency)} outside expected band around {_fmt(expected, p.currency)}",
                    expected={"fee": _fmt(expected, p.currency), "tolerance": _fmt(tolerance, p.currency)},
                    observed={"fee": _fmt(p.fee_minor, p.currency)},
                    delta_minor=p.fee_minor - expected,
                    currency=p.currency,
                )
            )
    return out


# ------------------------------------------------------------------ invoices


@rule("INVOICE_PAID_NO_CAPTURE")
def invoice_paid_no_capture(s: Scope) -> list[Finding]:
    out = []
    for inv in s.invoices.values():
        if inv.status not in ("PAID", "MARKED_AS_PAID", "PARTIALLY_PAID"):
            continue
        paid = inv.paid_amount_minor or 0
        if inv.status == "MARKED_AS_PAID":
            # Externally recorded payment; no PayPal capture expected. Surface as info for audit.
            out.append(
                Finding(
                    rule="INVOICE_PAID_NO_CAPTURE",
                    severity="info",
                    resource_type="invoice",
                    resource_id=inv.id,
                    title=f"Invoice {inv.invoice_number or inv.id} marked paid outside PayPal ({_fmt(paid or inv.amount_minor, inv.currency)})",
                    expected={"paid_via": "paypal"},
                    observed={"status": inv.status, "paid": _fmt(paid or inv.amount_minor, inv.currency)},
                    currency=inv.currency,
                )
            )
            continue
        matched = any(t.amount_minor == (paid or inv.amount_minor) and t.event_code and t.event_code.startswith("T00") for t in s.transactions.values())
        if not matched and not any(c.amount_minor == (paid or inv.amount_minor) for c in s.captures.values()):
            out.append(
                Finding(
                    rule="INVOICE_PAID_NO_CAPTURE",
                    severity="warn",
                    resource_type="invoice",
                    resource_id=inv.id,
                    title=f"Invoice {inv.invoice_number or inv.id} is {inv.status} but no matching PayPal payment found",
                    expected={"matching_payment": _fmt(paid or inv.amount_minor, inv.currency)},
                    observed={"status": inv.status},
                    delta_minor=paid or inv.amount_minor,
                    currency=inv.currency,
                )
            )
    return out


# ------------------------------------------------------------------ settlement


@rule("SETTLEMENT_LAG")
def settlement_lag(s: Scope) -> list[Finding]:
    hours = get_settings().settlement_lag_hours
    if not s.transactions:
        return []  # no reporting data at all: not a lag, an absent source
    # Reporting is only "caught up" to the newest transaction it has shown us. A capture newer
    # than that is simply not covered yet; a capture older than coverage minus the lag is missing.
    coverage = max(t.initiated_at for t in s.transactions.values())
    out = []
    for c in s.captures.values():
        if c.status != "COMPLETED" or c.settled_tx_id:
            continue
        age = s.now - c.created_at
        if age > timedelta(hours=hours) and c.created_at + timedelta(hours=hours) <= coverage:
            out.append(
                Finding(
                    rule="SETTLEMENT_LAG",
                    severity="info",
                    resource_type="capture",
                    resource_id=c.id,
                    correlation_id=c.order_id,
                    title=f"Capture {c.id} completed {int(age.total_seconds() // 3600)}h ago but not visible in Transaction Search",
                    expected={"visible_in_reporting_within_hours": hours},
                    observed={"age_hours": int(age.total_seconds() // 3600)},
                    currency=c.currency,
                )
            )
    return out


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)
