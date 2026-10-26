"""The remediation graph.

load_context -> triage -> specialist -> policy_gate -> (execute | wait_for_human) -> close

State is checkpointed in Postgres so a run waiting for approval survives restarts and can be
resumed from the API with ``Command(resume=...)``.
"""
from __future__ import annotations

import json
from typing import Any, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.agents import prompts
from app.agents.llm import get_llm
from app.agents.policy import evaluate
from app.agents.schemas import Proposal, Triage
from app.agents.tools import build_tools, fence_untrusted
from app.config import get_settings
from app.domain.models import Break
from app.logging import get_logger
from app.paypal.client import PayPalClient

log = get_logger("agent.graph")


class AgentState(TypedDict, total=False):
    usage: dict  # {"input_tokens": n, "output_tokens": n, "llm_calls": n}
    break_id: int
    break_json: dict
    triage: dict
    proposal: dict
    policy: dict
    trace: list[dict]
    approval_id: int | None
    decision: dict | None  # human decision when resumed
    outcome: dict | None


class GraphDeps:
    """Per-run dependencies. The graph is built once per run with a live session."""

    def __init__(self, session: Session, paypal: PayPalClient | None, agent_run_id: int):
        self.session = session
        self.paypal = paypal
        self.agent_run_id = agent_run_id
        self.llm = get_llm()
        self.tools = build_tools(session, paypal)
        self.mcp_tool_names: list[str] = []
        if paypal is not None:
            from app.agents.paypal_mcp import load_paypal_mcp_tools

            mcp_tools = load_paypal_mcp_tools(paypal)
            self.mcp_tool_names = [t.name for t in mcp_tools]
            self.tools = mcp_tools + self.tools
        self.tools_by_name = {t.name: t for t in self.tools}


def _break_json(b: Break) -> dict:
    return {
        "id": b.id,
        "rule": b.rule,
        "severity": b.severity,
        "title": b.title,
        "resource_type": b.resource_type,
        "resource_id": b.resource_id,
        "correlation_id": b.correlation_id,
        "expected": b.expected,
        "observed": b.observed,
        "delta_minor": b.delta_minor,
        "currency": b.currency,
        "opened_at": b.opened_at.isoformat() if b.opened_at else None,
    }


class LLMCallFailed(RuntimeError):
    pass


def _usage_of(msg: Any) -> dict:
    u = getattr(msg, "usage_metadata", None) or {}
    return {"input_tokens": int(u.get("input_tokens") or 0), "output_tokens": int(u.get("output_tokens") or 0), "llm_calls": 1}


def _add_usage(state: AgentState, *parts: dict) -> dict:
    tot = dict(state.get("usage") or {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0})
    for p in parts:
        for k in tot:
            tot[k] += int(p.get(k) or 0)
    return tot


@retry(retry=retry_if_exception_type(LLMCallFailed), wait=wait_exponential(multiplier=1, max=8), stop=stop_after_attempt(3), reraise=True)
def _structured(llm, schema, msgs):
    """Structured call with usage. Transport/5xx/parse errors retry; the final failure propagates."""
    try:
        out = llm.with_structured_output(schema, include_raw=True).invoke(msgs)
    except Exception as exc:  # noqa: BLE001 - provider errors are heterogeneous
        raise LLMCallFailed(str(exc)) from exc
    if isinstance(out, dict):
        parsed, raw = out.get("parsed"), out.get("raw")
        if parsed is None:
            raise LLMCallFailed(f"model returned no {schema.__name__}: {out.get('parsing_error')}")
        return parsed, _usage_of(raw)
    return out, {"input_tokens": 0, "output_tokens": 0, "llm_calls": 1}


@retry(retry=retry_if_exception_type(LLMCallFailed), wait=wait_exponential(multiplier=1, max=8), stop=stop_after_attempt(3), reraise=True)
def _invoke(llm, msgs):
    try:
        return llm.invoke(msgs)
    except Exception as exc:  # noqa: BLE001
        raise LLMCallFailed(str(exc)) from exc


def build_graph(deps: GraphDeps, checkpointer):
    s = get_settings()

    def load_context(state: AgentState) -> AgentState:
        b = deps.session.get(Break, state["break_id"])
        if b is None:
            raise RuntimeError(f"break {state['break_id']} not found")
        return {
            "break_json": _break_json(b),
            "trace": [{"node": "load_context", "break": b.fingerprint, "paypal_mcp_tools": deps.mcp_tool_names, "native_tools": [t.name for t in deps.tools if t.name not in deps.mcp_tool_names]}],
        }

    def triage(state: AgentState) -> AgentState:
        msgs = [SystemMessage(prompts.SYSTEM), HumanMessage(prompts.TRIAGE.format(break_json=json.dumps(state["break_json"], default=str)))]
        out, usage = _structured(deps.llm, Triage, msgs)
        return {"triage": out.model_dump(), "usage": _add_usage(state, usage), "trace": state["trace"] + [{"node": "triage", **out.model_dump()}]}

    def specialist(state: AgentState) -> AgentState:
        spec = state["triage"]["specialist"]
        msgs: list = [
            SystemMessage(prompts.SYSTEM),
            HumanMessage(
                prompts.SPECIALIST.format(
                    specialist=spec,
                    max_calls=s.agent_max_tool_calls,
                    break_json=json.dumps(state["break_json"], default=str),
                    triage_json=json.dumps(state["triage"], default=str),
                )
            ),
        ]
        trace = list(state["trace"])
        usage = dict(state.get("usage") or {})
        llm_tools = deps.llm.bind_tools(deps.tools)
        calls = 0
        while calls < s.agent_max_tool_calls:
            ai: AIMessage = _invoke(llm_tools, msgs)
            usage = _add_usage({"usage": usage}, _usage_of(ai))
            msgs.append(ai)
            tool_calls = getattr(ai, "tool_calls", None) or []
            if not tool_calls:
                break
            for tc in tool_calls:
                calls += 1
                tool = deps.tools_by_name.get(tc["name"])
                try:
                    result = tool.invoke(tc["args"]) if tool else json.dumps({"error": f"unknown tool {tc['name']}"})
                except Exception as exc:  # noqa: BLE001
                    result = json.dumps({"error": str(exc)})
                result = fence_untrusted(result)
                trace.append({"node": spec, "tool": tc["name"], "args": tc["args"], "result_preview": str(result)[:600]})
                msgs.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        try:
            proposal, pu = _structured(deps.llm, Proposal, msgs + [HumanMessage("Now produce the Proposal.")])
        except LLMCallFailed as exc:
            # The model could not produce a valid proposal after retries: never fail the break, escalate it.
            proposal = Proposal(
                action="escalate",
                headline="The agent could not reach a valid proposal; a person should review this break.",
                rationale=f"Model error after retries: {str(exc)[:300]}",
                confidence=0.0,
                order_id=state["break_json"].get("correlation_id"),
                escalation_summary="Automated analysis failed; review the evidence and order chain manually.",
            )
            pu = {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0}
            trace.append({"node": spec, "error": str(exc)[:300]})
        usage = _add_usage({"usage": usage}, pu)
        trace.append({"node": spec, "proposal": proposal.model_dump(), "tool_calls": calls})
        return {"proposal": proposal.model_dump(), "usage": usage, "trace": trace}

    def policy_gate(state: AgentState) -> AgentState:
        from app.agents.runner import record_approval

        p = state["proposal"]
        decision = evaluate(deps.session, p["action"], p, state["break_json"]["rule"])
        approval_id = record_approval(deps.session, deps.agent_run_id, state["break_id"], p, decision)
        pol = {"decision": decision.decision, "version": decision.version, "reasons": decision.reasons}
        return {"policy": pol, "approval_id": approval_id, "trace": state["trace"] + [{"node": "policy_gate", **pol}]}

    def route(state: AgentState) -> Literal["execute", "wait_for_human", "close"]:
        d = state["policy"]["decision"]
        if d == "auto":
            return "execute"
        if d == "requires_human":
            return "wait_for_human"
        return "close"

    def wait_for_human(state: AgentState) -> AgentState:
        # Pauses the graph. The API resumes it with Command(resume={"approved": bool, "by": ..., "note": ...}).
        decision = interrupt({"approval_id": state["approval_id"], "proposal": state["proposal"], "policy": state["policy"]})
        return {"decision": decision, "trace": state["trace"] + [{"node": "wait_for_human", "decision": decision}]}

    def after_human(state: AgentState) -> Literal["execute", "close"]:
        return "execute" if (state.get("decision") or {}).get("approved") else "close"

    def execute(state: AgentState) -> AgentState:
        from app.agents.executor import execute_approval

        outcome = execute_approval(deps.session, deps.paypal, state["approval_id"])
        return {"outcome": outcome, "trace": state["trace"] + [{"node": "execute", **outcome}]}

    def close(state: AgentState) -> AgentState:
        from app.agents.runner import close_run

        outcome = state.get("outcome") or {
            "status": "declined" if state.get("decision") else ("forbidden" if state["policy"]["decision"] == "forbidden" else "closed")
        }
        close_run(deps.session, deps.agent_run_id, state, outcome)
        return {"outcome": outcome}

    g = StateGraph(AgentState)
    g.add_node("load_context", load_context)
    g.add_node("triage", triage)
    g.add_node("specialist", specialist)
    g.add_node("policy_gate", policy_gate)
    g.add_node("wait_for_human", wait_for_human)
    g.add_node("execute", execute)
    g.add_node("close", close)
    g.set_entry_point("load_context")
    g.add_edge("load_context", "triage")
    g.add_edge("triage", "specialist")
    g.add_edge("specialist", "policy_gate")
    g.add_conditional_edges("policy_gate", route)
    g.add_conditional_edges("wait_for_human", after_human)
    g.add_edge("execute", "close")
    g.add_edge("close", END)
    return g.compile(checkpointer=checkpointer)


def resume_command(approved: bool, by: str, note: str | None) -> Command:
    return Command(resume={"approved": approved, "by": by, "note": note})


def as_jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))
