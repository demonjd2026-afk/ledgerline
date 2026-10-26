# ADR 0002 — Money as integer minor units

**Status:** accepted · **Date:** 2026-10

## Context

PayPal returns amounts as decimal strings (`"18.50"`). Floats cannot represent most of these
exactly, and reconciliation is precisely the place where `0.1 + 0.2 != 0.3` turns into a
false break or a missed one.

## Decision

Every amount is stored and computed as an integer in the currency's minor unit
(`amount_minor`, with `currency`), converted at the boundary by `domain/money.py`, which
knows the exponent per currency (two for most, none for JPY, HUF and TWD). Decimal
strings exist only at the PayPal boundary and in the UI.

The LLM never produces an amount that is used as-is: proposals carry `amount_minor`, and the
executor re-derives the allowed maximum from the ledger before any call.

## Consequences

* Sums, deltas and comparisons are exact; the rule engine needs no tolerance band.
* Multi-currency works without special cases as long as amounts are never mixed across
  currencies, which the `Money` type enforces.
* Anyone reading the database sees `1850`, not `18.50`. The API and console format for humans.
