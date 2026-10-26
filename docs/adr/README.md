# Architecture decision records

Short records of the decisions that shaped Ledgerline, in the order they were made. Each one
states the context, the decision, and what it cost. They are kept with the code so a reviewer
can check the decision against what was actually built.

| # | Decision | Status |
|---|---|---|
| [0001](0001-event-sourced-ledger.md) | Event-sourced ledger with rebuildable projections | accepted |
| [0002](0002-integer-money.md) | Money as integer minor units, never floats | accepted |
| [0003](0003-postgres-job-queue.md) | Postgres `FOR UPDATE SKIP LOCKED` job queue instead of a broker | accepted |
| [0004](0004-langgraph-interrupt-for-human-approval.md) | LangGraph checkpointed interrupt for human-in-the-loop | accepted |
| [0005](0005-paypal-mcp-as-tool-layer.md) | PayPal's official MCP server as the agent's PayPal tool layer, read-only | accepted |
| [0006](0006-yaml-policy-gate.md) | Deterministic YAML policy between proposal and execution | accepted |
