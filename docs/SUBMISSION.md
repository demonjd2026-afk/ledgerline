# Devpost submission — Ledgerline

Copy-ready text for the submission form. Keep the headings Devpost asks for; trim to taste.

## Project name

Ledgerline

## Video demo link

https://youtu.be/cKiMP7jMIPw

## Tagline

An autonomous revenue-operations agent for PayPal merchants: an independent ledger, continuous reconciliation against PayPal, and policy-gated AI agents that fix what breaks.

## Inspiration

Merchants find out about money problems late and from the wrong place. A capture that never matched its order, a refund webhook delivered twice, a dispute quietly reaching its deadline, a creator payout that silently failed. Every fact needed to catch these exists in PayPal — webhooks, Orders, Payments, Transaction Search, Disputes, Payouts, Invoicing — but nobody joins them, and nobody acts on them at 2 a.m. I wanted the thing a finance team actually asks for: not another dashboard, but a system that keeps its own books, notices the moment PayPal and the books disagree, and resolves it under rules the merchant wrote.

## What it does

1. **Ingests** every PayPal webhook (signature-verified) and polls Transaction Search, Disputes and Payouts as a second source of truth.
2. **Records** each fact as an immutable, idempotent ledger event and projects orders, captures, refunds, payouts, disputes and invoices from it. Replay is deterministic; the projections can be rebuilt from the log.
3. **Reconciles** with thirteen rules that emit typed *breaks* — expected, observed, delta, severity — covering amount mismatches, duplicate checkouts and captures, refunds exceeding captures, webhook/API drift, stale authorizations, dispute deadlines, failed payouts, fee variance, invoices paid without a payment, and settlement lag.
4. **Investigates** each break with a LangGraph agent: triage, then a specialist (dispute defender, refund advisor, drift explainer) that uses PayPal's official MCP server plus ledger tools, and must return a structured proposal — never prose.
5. **Gates** the proposal through a versioned YAML policy. Refunding an $18.50 duplicate checkout runs itself; anything touching a dispute, above threshold, or below a confidence floor pauses the graph for a person.
6. **Executes** through one audited path with one idempotency key per approval, so a retry can never refund twice or submit evidence twice.
7. **Shows** everything in an operator console: breaks as ledger lines, proposals with the policy's reasons, one-click approve/decline, the agent's full tool trace and token cost.

## How I built it

- **PayPal:** Webhooks + `verify-webhook-signature`, Orders v2 (card `payment_source` for headless sandbox seeding), Payments v2 captures/refunds, Transaction Search, Customer Disputes v1 (`provide-evidence`, `send-message`), Payouts v1, Invoicing v2, and the official **PayPal MCP server (`@paypal/mcp`)** as the agent's tool layer — the agentic-commerce surface PayPal publishes at docs.paypal.ai.
- **AI:** LangGraph state machine with a Postgres checkpointer (the human-in-the-loop pause is a real graph interrupt that survives restarts), Claude Sonnet by default, any tool-calling LLM via LangChain, and a deterministic stub so the whole demo runs with no keys.
- **Backend:** FastAPI, SQLAlchemy 2, Alembic, a `FOR UPDATE SKIP LOCKED` job queue, integer money (no floats), structured logging, Prometheus metrics.
- **Console:** React 19, AG Grid (Theming API, custom cell renderers, quick filter, CSV export), light/dark.
- **Deployment:** Render Blueprint — web + worker + managed Postgres — with the fixture seeded on first boot so judges land on live data.
- **Quality:** 32 tests against a real Postgres, an agent evaluation harness (`ledgerline eval`) that checks every proposal against expected actions, ruff, bandit, pip-audit, npm audit, CodeQL.

## Challenges I ran into

- Making an AI agent safe to put near money: the model never holds a write tool, proposals are schema-validated and bounded by the ledger, customer-written text is fenced as untrusted data, a confidence floor and a YAML policy decide what runs unattended, and a dead model ends in an escalation rather than a crash.
- Detecting webhook/API drift honestly: API snapshots must never overwrite webhook-derived state, so the ledger keeps both views and the rule compares the ledger-implied status against PayPal's.
- Driving the PayPal sandbox without a browser: card `payment_source` orders, payout batches and invoices are created by the simulator so a reviewer can reproduce every scenario from the command line.

## Accomplishments I'm proud of

A fresh clone runs end to end in five minutes with no keys, opens nine breaks across six scenarios, auto-refunds the one the policy allows, and parks seven proposals for a person with evidence attached. Against a real sandbox it did the same with real money movement.

## What I learned

Event-sourcing the merchant's side turns "the AI said so" into "the ledger says so, and here is the event". Judges, auditors and merchants all ask the same question: *why?* The structured proposal + policy reasons + tool trace answers it every time.

## What's next

SSO (OIDC) with viewer/operator/admin roles in place of the demo's shared operator token, with the approver's identity on every approval row; attachments on dispute evidence; Braintree and Venmo sources; per-merchant policy editing in the console; a nightly reconciliation report.

## Built with

python, fastapi, langgraph, langchain, postgresql, sqlalchemy, react, typescript, vite, ag-grid, paypal-rest-api, paypal-mcp, anthropic-claude, docker, render

## Testing instructions (for judges)

**Hosted (no setup):** https://ledgerline-wcpx.onrender.com/?token=<OPERATOR_TOKEN> — the link signs you in (or paste the token `<OPERATOR_TOKEN>` when prompted). The ledger is pre-seeded from the recorded PayPal fixture and the agents have already run against it with Claude: click **Breaks**, open *Ledger disagrees with PayPal*, then **Approvals** → approve or decline a proposal, then **Agent runs** for the full tool trace. The hosted instance runs the PayPal executor in dry-run mode, so an approval records the exact PayPal call it would make rather than sending it.

**Local, no keys:**
```bash
git clone https://github.com/demonjd2026-afk/ledgerline && cd ledgerline
docker compose up -d db && cd backend && pip install -e . && ledgerline migrate
LLM_MODEL=stub PAYPAL_DRY_RUN=true ledgerline sim replay
ledgerline api   # http://127.0.0.1:8000
```

**Against your own sandbox:** see README → "Run against your PayPal sandbox".
