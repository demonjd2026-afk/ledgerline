# Ledgerline

**Autonomous revenue-operations agent for PayPal merchants.**
An event-sourced ledger of everything that happens on a PayPal account, continuous
reconciliation against PayPal's own APIs, and policy-gated AI agents that resolve the
breaks — drafting dispute evidence, computing refunds, explaining drift — with a human
in the loop wherever money or a dispute is involved.

> Built for the PayPal AI Hackathon 2026. Sandbox only.

## Why

Merchants find out about problems from PayPal's dashboard, days late: a capture that
never matched its order, a refund recorded twice, a dispute that quietly hit its
response deadline. Ledgerline keeps its own copy of the truth, notices the moment the
two diverge, and puts a worked, evidence-backed proposal in front of an operator — or
executes it when policy says it is safe.

## What it does

| Layer | What |
|---|---|
| **Ingest** | Verified PayPal webhooks + Transaction Search / Disputes polling as a second source of truth |
| **Ledger** | Append-only, idempotent event log; deterministic projections; rebuildable |
| **Reconcile** | 12 rules producing typed breaks with `expected`, `observed`, `delta` |
| **Agents** | LangGraph triage → specialist (dispute defender, refund advisor, drift explainer) → structured proposal |
| **Policy** | Deterministic YAML gate: auto-execute within limits, otherwise pause for approval |
| **Execute** | The only code that mutates PayPal; idempotency keys derived from the approval id |
| **Console** | React + AG Grid: ledger explorer, breaks queue, agent traces, approvals inbox |

Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Status

Work in progress — see commit history. Setup, demo and deployment instructions land with the first release.

## Licence

MIT
