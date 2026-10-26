# ADR 0004 — LangGraph checkpointed interrupt for human-in-the-loop

**Status:** accepted · **Date:** 2026-10

## Context

Most proposals must wait for a person, for minutes or days. A naive agent loop would hold a
process (and a model context) open, or would end the run and require a second, separate
"execution" flow that re-derives everything.

## Decision

The agent is a LangGraph state graph (`load_context → triage → specialist → policy_gate →
wait_for_human | execute → close`) checkpointed in Postgres (`langgraph-checkpoint-postgres`).
When the policy gate says "requires human", the graph calls `interrupt()` and the run is
persisted at that exact node. An approval or decline from the console resumes the same
thread with the decision as input; the execute node runs with the proposal the human saw,
not a regenerated one.

The pause is a real graph interrupt, so it survives worker restarts and deploys.

## Consequences

* "What the human approved" and "what gets executed" are the same object, by construction.
* Runs are resumable and inspectable: the trace the operator sees is the checkpoint history.
* LangGraph is a dependency with a moving API. Accepted: the graph is small (seven nodes),
  and the alternative — a hand-rolled state machine with the same persistence — is more code
  with the same risk.
