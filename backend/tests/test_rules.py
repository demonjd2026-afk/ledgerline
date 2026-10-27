"""Rules that the demo fixture does not exercise, tested as pure functions over a Scope."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.domain.models import Authorization, Capture, Dispute, Order, Transaction
from app.recon.rules import (
    Scope,
    capture_without_order,
    dispute_unreconciled_hold,
    settlement_lag,
    stale_authorization,
)

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _scope(**kw) -> Scope:
    base = dict(orders={}, captures={}, refunds={}, authorizations={}, payout_items={}, disputes={}, invoices={}, transactions={})
    base.update(kw)
    return Scope(now=NOW, **base)


def _order(oid: str, minor: int) -> Order:
    return Order(id=oid, status="COMPLETED", intent="CAPTURE", amount_minor=minor, currency="USD", created_at=NOW, updated_at=NOW, last_event_id=1)


def _capture(cid: str, oid: str | None, minor: int, *, created_at=NOW, settled_tx_id=None) -> Capture:
    return Capture(id=cid, order_id=oid, status="COMPLETED", amount_minor=minor, currency="USD", final_capture=True, created_at=created_at, updated_at=created_at, last_event_id=1, settled_tx_id=settled_tx_id)


def test_capture_without_order_only_when_order_is_missing():
    s = _scope(orders={"O1": _order("O1", 4500)}, captures={"C1": _capture("C1", "O1", 4500), "C2": _capture("C2", "O-GHOST", 1200)})
    found = capture_without_order(s)
    assert [f.resource_id for f in found] == ["C2"]
    assert found[0].severity == "warn"
    assert found[0].correlation_id == "O-GHOST"
    assert found[0].fingerprint == "CAPTURE_WITHOUT_ORDER:capture:C2"


def test_stale_authorization_respects_age_and_status():
    days = get_settings().stale_auth_days
    old = NOW - timedelta(days=days + 1)
    fresh = NOW - timedelta(days=max(days - 1, 0))

    def auth(aid, status, created):
        return Authorization(id=aid, order_id=f"O-{aid}", status=status, amount_minor=9900, currency="USD", created_at=created, updated_at=created, last_event_id=1)

    s = _scope(authorizations={
        "A-old": auth("A-old", "CREATED", old),
        "A-fresh": auth("A-fresh", "CREATED", fresh),
        "A-captured": auth("A-captured", "CAPTURED", old),
        "A-voided": auth("A-voided", "VOIDED", old),
    })
    found = stale_authorization(s)
    assert [f.resource_id for f in found] == ["A-old"]
    assert found[0].expected == {"captured_or_voided_within_days": days}
    assert found[0].observed["age_days"] == days + 1


def test_dispute_unreconciled_hold_missing_capture_and_over_amount():
    def dispute(did, tx, minor, status="OPEN"):
        return Dispute(id=did, transaction_id=tx, order_id=None, status=status, amount_minor=minor, currency="USD", created_at=NOW, updated_at=NOW)

    s = _scope(
        captures={"C1": _capture("C1", "O1", 34900)},
        disputes={
            "D-ok": dispute("D-ok", "C1", 34900),            # matches the capture: no finding
            "D-over": dispute("D-over", "C1", 40000),        # disputes more than was captured
            "D-ghost": dispute("D-ghost", "C-NOPE", 1000),   # capture never seen in the ledger
            "D-resolved": dispute("D-resolved", "C-NOPE", 1000, status="RESOLVED"),
            "D-notx": dispute("D-notx", None, 1000),
        },
    )
    found = {f.resource_id: f for f in dispute_unreconciled_hold(s)}
    assert set(found) == {"D-over", "D-ghost"}
    assert found["D-over"].delta_minor == 40000 - 34900
    assert found["D-over"].correlation_id == "O1"
    assert found["D-ghost"].expected == {"capture_in_ledger": True}


def test_settlement_lag_only_within_reporting_coverage():
    hours = get_settings().settlement_lag_hours
    lag = timedelta(hours=hours)
    coverage = NOW - timedelta(hours=1)

    def tx(tid, when):
        return Transaction(id=tid, event_code="T0006", status="S", amount_minor=1000, currency="USD", paypal_reference_id=None, initiated_at=when, updated_at=when, last_event_id=1)

    captures = {
        "C-missing": _capture("C-missing", "O1", 1000, created_at=coverage - lag - timedelta(hours=2)),   # old enough, and reporting has passed it
        "C-recent": _capture("C-recent", "O2", 1000, created_at=NOW - timedelta(minutes=5)),              # too new to expect
        "C-uncovered": _capture("C-uncovered", "O3", 1000, created_at=coverage - lag + timedelta(hours=1)),  # older than the lag, but reporting is not there yet
        "C-settled": _capture("C-settled", "O4", 1000, created_at=coverage - lag - timedelta(hours=2), settled_tx_id="T1"),
    }
    assert settlement_lag(_scope(captures=captures)) == []  # no reporting data at all: not a lag
    found = settlement_lag(_scope(captures=captures, transactions={"T1": tx("T1", coverage)}))
    assert [f.resource_id for f in found] == ["C-missing"]
    assert found[0].severity == "info"
    assert found[0].expected == {"visible_in_reporting_within_hours": hours}
