# ADR 0003 — Postgres job queue instead of a message broker

**Status:** accepted · **Date:** 2026-10

## Context

Ingestion, reconciliation and agent runs must be asynchronous: a webhook has to be acked in
milliseconds, an agent run takes 30–60 seconds. The obvious choice is Redis + Celery or a
hosted queue. That adds a second stateful service, a second failure mode, and a consistency
gap between "the event is in Postgres" and "the job is in Redis".

## Decision

Jobs live in a `jobs` table in the same Postgres database as the ledger. The worker claims
with `SELECT … FOR UPDATE SKIP LOCKED`, which lets any number of workers drain the same
table without double-claiming. Jobs are idempotent by `(kind, dedupe_key)`; failures retry
with exponential backoff up to `JOB_MAX_ATTEMPTS`, then park for a human.

Enqueueing a job and writing the ledger event happen in one transaction, so there is no
window where one exists without the other.

## Consequences

* One stateful dependency. Backups, migrations and local development cover the queue for free.
* Horizontal scale is "run more workers"; `SKIP LOCKED` handles contention. Render's
  Workflows product is the natural next step for fanning agent runs out across many
  instances, and the queue semantics map onto it directly.
* Throughput is bounded by Postgres row locking, which is far above what a merchant's
  PayPal event rate needs. A broker would be the right call at many thousands of jobs per
  second; this system is not that.
