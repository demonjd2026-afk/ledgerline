"""Deterministic policy gate. No LLM in this file by design."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.models import Dispute, Order, Refund


@dataclass(slots=True)
class PolicyDecision:
    decision: str  # auto | requires_human | forbidden
    version: int
    reasons: list[str] = field(default_factory=list)


@lru_cache
def load_policy(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else get_settings().policy_path
    with open(p) as fh:
        return yaml.safe_load(fh)


def evaluate(session: Session, action: str, proposal: dict[str, Any], rule: str) -> PolicyDecision:
    pol = load_policy()
    version = int(pol.get("version", 0))
    reasons: list[str] = []

    if action in (pol.get("never_auto") or []):
        return PolicyDecision("requires_human", version, [f"{action} is in never_auto"])

    if action == "refund":
        amount = int(proposal.get("amount_minor") or 0)
        if amount <= 0:
            return PolicyDecision("forbidden", version, ["refund amount must be positive"])
        if amount > int(pol.get("max_refund_minor", 0)):
            return PolicyDecision("forbidden", version, [f"amount {amount} exceeds max_refund_minor"])
        cfg = (pol.get("auto_approve") or {}).get("refund") or {}
        if amount > int(cfg.get("max_amount_minor", 0)):
            reasons.append("amount above auto-approve threshold")
        order_id = proposal.get("order_id")
        order = session.get(Order, order_id) if order_id else None
        if order is None:
            reasons.append("order not in ledger")
        else:
            age = (datetime.now(tz=timezone.utc) - order.created_at).days
            if age > int(cfg.get("max_order_age_days", 0)):
                reasons.append(f"order is {age}d old")
            if order.payer_email and order.payer_email in (pol.get("payer_blocklist") or []):
                reasons.append("payer_blocklisted")
        conds = set(cfg.get("not_if") or [])
        if "dispute_open_on_order" in conds and order_id:
            open_d = session.execute(
                select(Dispute).where(Dispute.order_id == order_id, Dispute.status != "RESOLVED")
            ).first()
            if open_d:
                reasons.append("dispute_open_on_order")
        if "prior_refund_on_capture" in conds and proposal.get("capture_id"):
            prior = session.execute(select(Refund).where(Refund.capture_id == proposal["capture_id"])).first()
            if prior:
                reasons.append("prior_refund_on_capture")
        return PolicyDecision("requires_human" if reasons else "auto", version, reasons or ["within auto-approve limits"])

    if action in ("ledger_correction", "no_action"):
        cfg = (pol.get("auto_approve") or {}).get(action) or {}
        if rule in (cfg.get("allowed_rules") or []):
            return PolicyDecision("auto", version, [f"{rule} allowed for {action}"])
        return PolicyDecision("requires_human", version, [f"{rule} not in allowed_rules for {action}"])

    return PolicyDecision("requires_human", version, [f"unknown action {action}"])
