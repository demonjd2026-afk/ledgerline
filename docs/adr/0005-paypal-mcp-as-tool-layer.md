# ADR 0005 — PayPal's official MCP server as the agent's PayPal tool layer, read-only

**Status:** accepted · **Date:** 2026-10

## Context

The agent needs to read PayPal state during an investigation: an order, a dispute, shipment
tracking, transactions. Hand-writing a LangChain tool per endpoint works but duplicates
PayPal's own tool definitions and drifts as the API changes.

## Decision

The agent loads PayPal's official MCP server (`@paypal/mcp`, the server behind PayPal's Agent
Toolkit) over stdio, authenticated with a sandbox OAuth token minted by Ledgerline's own
client, and restricted to an explicit read-only tool list:
`orders.get, disputes.get, disputes.list, invoices.get, invoices.list, transactions.list,
shipment.get`. Each MCP tool is wrapped so the synchronous graph can call it, and appears in
the trace with a `paypal_mcp_` prefix so an operator can see which calls went to PayPal.

Writes (refund, provide evidence, send message) are **not** exposed through MCP or any other
tool. The executor makes them through Ledgerline's own PayPal client after the policy gate,
with idempotency keys.

If Node or the package is missing, the graph falls back to Ledgerline's native read tools and
records that in the trace, so the system degrades rather than fails.

## Consequences

* Tool definitions track PayPal's, not ours.
* The read/write split is enforced by configuration the model cannot change, which is the
  property the threat model depends on (T3).
* A Node runtime ships in the Python image, and the server is a subprocess per run. Accepted:
  the cost is ~1 s per run, and the alternative was re-implementing PayPal's tool surface.
