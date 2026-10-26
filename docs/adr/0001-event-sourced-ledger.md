# ADR 0001 — Event-sourced ledger with rebuildable projections

**Status:** accepted · **Date:** 2026-10

## Context

Ledgerline's job is to say, with evidence, when the merchant's record and PayPal's record
disagree. A CRUD model that updates an `orders` row in place loses the history that makes
that claim defensible: once a webhook and an API poll have both written the row, nobody can
say which one set which field, or replay what the system knew at the time a decision was made.

## Decision

Every fact from PayPal — webhook, API snapshot, poll result — is appended as an immutable
`ledger_events` row keyed by a deterministic `event_key`. Orders, captures, refunds, payouts,
disputes and invoices are *projections* computed from the log. Corrections the operator
approves are themselves events (`source=correction`, `event_type=LEDGER_CORRECTION`), never edits.

`ledgerline rebuild` drops the projections and replays the log; the result must be identical.
Breaks are recomputed from projections, so a rule change re-evaluates history.

## Consequences

* The agent and the operator can always answer "why?" with an event id.
* Duplicate deliveries and replays are harmless by construction (`event_key` is unique).
* Projections are more code than a CRUD model, and every new PayPal resource type needs a
  projector. Accepted: the resource set (seven types) is bounded and stable.
* Storage grows monotonically. Accepted for this scale; archival of old events with a
  snapshot is the known next step.
