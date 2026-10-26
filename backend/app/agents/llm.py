"""LLM factory. ``LLM_MODEL=stub`` returns a deterministic fake so the whole pipeline — including
approvals and execution — runs with no API key. Used by tests, fixture replay and judges without keys."""
from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.config import get_settings


class StubChatModel(BaseChatModel):
    """Answers triage and proposals from the break itself using the same heuristics a careful
    analyst would start with. Calls no tools."""

    @property
    def _llm_type(self) -> str:
        return "stub"

    def bind_tools(self, tools, **kwargs):  # noqa: D401 - no tool use in stub
        return self

    def with_structured_output(self, schema, **kwargs):
        model = self

        class _Runner:
            def invoke(self, messages, **kw):
                return model._structured(schema, messages)

        return _Runner()

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="stub"))])

    def _structured(self, schema, messages) -> Any:
        from app.agents.schemas import Proposal, Triage

        text = "\n".join(str(getattr(m, "content", "")) for m in messages)
        brk = _extract_json(text, "BREAK:")
        rule = brk.get("rule", "")
        if schema is Triage:
            if rule.startswith("DISPUTE"):
                spec = "dispute_defender"
            elif rule in ("ORDER_AMOUNT_MISMATCH", "DUPLICATE_CAPTURE"):
                spec = "refund_advisor"
            else:
                spec = "drift_explainer"
            return Triage(specialist=spec, summary=brk.get("title", rule), missing_evidence=[], confidence=0.6)
        if schema is Proposal:
            return _stub_proposal(brk)
        raise TypeError(f"stub cannot produce {schema}")


def _extract_json(text: str, marker: str) -> dict:
    i = text.find(marker)
    if i < 0:
        return {}
    start = text.find("{", i)
    depth = 0
    for j in range(start, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : j + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def _stub_proposal(brk: dict):
    from app.agents.schemas import EvidenceItem, Proposal

    rule = brk.get("rule", "")
    obs, exp = brk.get("observed", {}), brk.get("expected", {})
    cur = brk.get("currency") or "USD"
    delta = int(brk.get("delta_minor") or 0)
    rid, corr = brk.get("resource_id"), brk.get("correlation_id")
    if rule in ("ORDER_AMOUNT_MISMATCH", "DUPLICATE_CAPTURE") and delta > 0:
        caps = obs.get("captures") or []
        return Proposal(
            action="refund",
            rationale=f"Ledger shows {obs.get('captured_total') or obs.get('final_captures')} captured against order amount {exp.get('order_amount','?')}. Customer was over-charged by the delta; refund exactly that amount from the last capture.",
            confidence=0.7,
            capture_id=caps[-1] if caps else None,
            order_id=corr or rid,
            amount_minor=delta,
            currency=cur,
            note_to_payer="Refund of duplicate/over-charge identified during reconciliation.",
        )
    if rule == "DISPUTE_RESPONSE_DUE":
        return Proposal(
            action="provide_evidence",
            rationale=f"Dispute {rid} ({obs.get('reason')}) is {obs.get('status')} and due {obs.get('due')}. Submitting fulfilment evidence from the order chain before the deadline.",
            confidence=0.55,
            dispute_id=rid,
            order_id=corr,
            evidences=[
                EvidenceItem(evidence_type="PROOF_OF_FULFILLMENT", notes=f"Order {corr or 'n/a'} was captured and fulfilled; see ledger chain for capture id and timestamps."),
                EvidenceItem(evidence_type="RETURN_POLICY", notes="Merchant return policy was presented at checkout and accepted."),
            ],
            message_to_buyer="We have submitted our records for this transaction and are happy to resolve this directly.",
        )
    if rule in ("WEBHOOK_API_DRIFT",):
        return Proposal(
            action="ledger_correction",
            rationale=f"PayPal's API reports {exp.get('status')}/{exp.get('amount')} while the ledger holds {obs.get('status')}/{obs.get('amount')}. PayPal is authoritative for capture state; correct the ledger projection.",
            confidence=0.8,
            capture_id=rid,
            order_id=corr,
            correction={"status": exp.get("status"), "amount": exp.get("amount"), "source": "paypal_api"},
        )
    if rule == "REFUND_EXCEEDS_CAPTURE":
        return Proposal(
            action="escalate",
            rationale=f"Refunds {obs.get('refunded_total')} exceed capture {exp.get('max_refundable')}. Likely a duplicate refund record; needs a human to confirm with PayPal before any correction.",
            confidence=0.6,
            capture_id=rid,
            order_id=corr,
            escalation_summary="Verify refund ids against PayPal; if duplicate record, correct ledger; if real double refund, recover from payer.",
        )
    return Proposal(
        action="no_action",
        rationale=f"{rule}: informational; no money movement warranted. {brk.get('title','')}",
        confidence=0.5,
        order_id=corr,
    )


def get_llm() -> BaseChatModel:
    s = get_settings()
    if s.llm_model.lower() in ("stub", "none", ""):
        return StubChatModel()
    from langchain.chat_models import init_chat_model

    return init_chat_model(s.llm_model, temperature=s.llm_temperature)
