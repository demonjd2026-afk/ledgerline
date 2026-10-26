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

from app.agents import prompts
from app.agents.llm import get_llm
from app.agents.policy import evaluate
from app.agents.schemas import Proposal, Triage
from app.agents.tools import build_tools
from app.config import get_settings
from app.domain.models import Break
from app.logging import get_logger
from app.paypal.client import PayPalClient

log = get_logger("agent.graph")


class AgentState(TypedDict, total=False):
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


def build_graph(deps: GraphDeps, checkpointer):
    s = get_settings()

    def load_context(state: AgentState) -> AgentState:
        b = deps.session.get(Break, state["break_id"])
        if b is None:
            raise RuntimeError(f"break {state['break_id']} not found")
        return {"break_json": _break_json(b), "trace": [{"node": "load_context", "break": b.fingerprint}]}

    def triage(state: AgentState) -> AgentState:
        msgs = [SystemMessage(prompts.SYSTEM), HumanMessage(prompts.TRIAGE.format(break_json=json.dumps(state["break_json"], default=str)))]
        out: Triage = deps.llm.with_structured_output(Triage).invoke(msgs)
        return {"triage": out.model_dump(), "trace": state["trace"] + [{"node": "triage", **out.model_dump()}]}

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
        llm_tools = deps.llm.bind_tools(deps.tools)
        calls = 0
        while calls < s.agent_max_tool_calls:
            ai: AIMessage = llm_tools.invoke(msgs)
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
                trace.append({"node": spec, "tool": tc["name"], "args": tc["args"], "result_preview": str(result)[:600]})
                msgs.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        proposal: Proposal = deps.llm.with_structured_output(Proposal).invoke(
            msgs + [HumanMessage("Now produce the Proposal.")]
        )
        trace.append({"node": spec, "proposal": proposal.model_dump()})
        return {"proposal": proposal.model_dump(), "trace": trace}

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
