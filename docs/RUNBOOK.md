# Runbook

Operating Ledgerline in a hosted deployment (Render Blueprint: `ledgerline` web, `ledgerline-worker`,
`ledgerline-db`). Commands run in the web service's shell (Render → service → Shell) or any host with
`DATABASE_URL` set; all of them are the `ledgerline` CLI.

## Health

| Check | Where | Healthy |
|---|---|---|
| API + DB + PayPal auth | `GET /healthz` | `{"ok":true,"db":true,"paypal":true}` |
| Queue depth, breaks, last event | `GET /api/overview` (operator token) | `jobs.done` growing, `last_event_at` recent |
| Metrics | `GET /metrics` (Prometheus text) | `ledgerline_http_requests_total`, `ledgerline_http_request_seconds` |
| Worker alive | Render → ledgerline-worker → Logs | `job.done` lines; `poll.*` every `POLL_INTERVAL_SECONDS` |

The console's footer shows the same three signals: PayPal connected, model, worker queue depth.

## Scenarios

### Webhooks rejected (`webhooks_rejected` climbing, `webhook.rejected` in logs)

Cause is almost always `PAYPAL_WEBHOOK_ID` not matching the webhook registered for the app
whose credentials are configured, or the webhook registered on a different app/account.

1. developer.paypal.com → the app whose `PAYPAL_CLIENT_ID` is deployed → Webhooks → copy the ID.
2. Set `PAYPAL_WEBHOOK_ID` on **both** services; Render redeploys.
3. Rejected payloads are kept in `webhook_inbox` with `status=rejected`; nothing was ingested.
   The poller and the enricher will have caught the underlying events anyway, later.

### A break has no agent run, or the run is stuck in `queued`

The worker is down or behind.

1. Render → ledgerline-worker → Events. A crash loop shows as repeated restarts.
2. `GET /api/overview` → `jobs`: a large `queued` or `failed` count.
3. Failed jobs retried `JOB_MAX_ATTEMPTS` times then parked. After fixing the cause, requeue from
   the console (break → *Run agent*) or `POST /api/breaks/{id}/run`.

### An agent run ended as `escalate` with an error in the trace

By design: a model error, timeout, or an invalid proposal never fails a break; it escalates it
with the error attached. Open the run in **Agent runs**, read the last trace entry.

* `LLMCallFailed` / provider 4xx–5xx → check `LLM_API_KEY` and provider status; re-run the break.
* `proposal validation` → the model returned an out-of-schema proposal; re-run (temperature is 0,
  so a repeat usually succeeds) and keep the trace for the eval set.
* `tool budget exhausted` → raise `AGENT_MAX_TOOL_CALLS` only if the traces show real progress.

### PayPal returns 429 / 5xx

The client retries 429 / 5xx / transport errors with exponential backoff. Sustained 429 on
`/v1/reporting/transactions` means the app lacks the **Transaction Search** feature
(developer.paypal.com → app → Features). A 403 there is logged as `poll.transactions_unavailable`
and is non-fatal: the `SETTLEMENT_LAG` rule simply has no data.

### An approval was executed twice? (it cannot — how to prove it)

Every PayPal mutation carries `PayPal-Request-Id = <idempotency_key>` from the approval row.
Compare `approvals.idempotency_key` with the `PayPal-Request-Id` in `execution_result`; PayPal
returns the original response for a repeated id. Ledger-side, the correction event's `event_key`
is unique.

### Rotate the operator token

1. Render → `ledgerline` → Environment → `OPERATOR_TOKEN` → new value (32+ random bytes) → Save.
2. Operators sign in again (`/?token=…` link or the prompt). Old sessions get 401 immediately.
   The worker does not use the token.

### Rotate PayPal credentials

Set `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` on both services. The client caches OAuth tokens
in memory only; a redeploy picks up the new pair. Re-register the webhook if the app changed.

### Projections look wrong but the event log is right

```
ledgerline rebuild        # drop projections, replay ledger_events (then `ledgerline reconcile` to recompute breaks)
ledgerline reconcile      # re-run every rule without rebuilding
```

Both are safe to run while the worker is up; they are idempotent.

### Reset the hosted demo

```
ledgerline reset --yes    # truncates ledger, breaks, runs, approvals, jobs, checkpoints
```

Then restart `ledgerline-worker` (Render → Manual Deploy → *Restart*). With
`DEMO_SEED_ON_START=true` it replays the bundled fixture into the empty ledger and the agents
re-run. Allow ~4 minutes for eight runs with a real model.

### Switch the hosted instance from fixture demo to real sandbox data

1. `PAYPAL_DRY_RUN=false` on both services (Render → Environment, or `render.yaml`).
2. `DEMO_SEED_ON_START=false` on the worker.
3. `ledgerline reset --yes`, then from a machine with the same sandbox credentials:
   `ledgerline sim seed && ledgerline sim inject && ledgerline sim wallet-order`.
4. Register the webhook (above) so PayPal pushes events to the hosted URL.

## Deploy

* Push to `main` deploys both services (Auto-Deploy). `render.yaml` changes sync as a Blueprint
  and ask for approval in the Render dashboard.
* Migrations run as the web service's pre-deploy command (`alembic upgrade head`). A failed
  migration stops the deploy; the previous version keeps serving.
* Roll back: Render → service → Deploys → *Rollback* on the last good deploy. Migrations are
  forward-only; write a new migration rather than downgrading.
