# Security

Ledgerline moves money on a merchant's behalf, so the controls below are part of the design,
not an afterthought.

## Boundaries

- **Live mode is off.** `PAYPAL_ENV=live` refuses to start unless `ALLOW_LIVE=true`, and the
  PayPal client refuses mutating calls in live without it.
- **The LLM has no write tools.** Agents get read-only PayPal (via PayPal's MCP server) and
  ledger tools. The one code path that mutates PayPal is `agents/executor.py`, which runs only
  after the deterministic policy gate and, where policy says so, a human decision.
- **Amounts come from the ledger, never the model.** Refunds are bounded by the capture amount
  and `policy.yaml`'s `max_refund_minor`.
- **Every mutation is idempotent.** `PayPal-Request-Id` is derived from the approval id, so a
  retried job cannot refund twice.
- **Webhooks are verified** with PayPal's `verify-webhook-signature`. In `APP_ENV=prod`,
  unverified webhooks are rejected; in dev they are accepted with a logged warning.
- **Operator API token.** Set `OPERATOR_TOKEN` and every `/api/*` request must carry
  `X-Operator-Token` (constant-time compared). The console prompts for it on 401.
- Security headers (`nosniff`, `DENY` framing, no referrer) on every response; request ids are
  server-generated.

## Secrets

Credentials live only in environment variables (`backend/.env` locally, dashboard secrets on
Render). `.env` is git-ignored. The MCP subprocess receives a short-lived sandbox OAuth token,
never the client secret.

## Scanning

CI runs `pytest`, `ruff`, `bandit -ll`, `pip-audit`, `npm audit` (frontend, high+) and CodeQL
(Python + TypeScript, security-and-quality queries) on every push.

### Known, accepted advisories

`backend/node_modules/@paypal/mcp` (PayPal's official MCP server) pins older versions of
`@langchain/core`, `ai`, `mathjs`, `openai` and `zod` with open advisories. These are inside
PayPal's package, not ours. Mitigation: the server runs as a local subprocess with a sandbox
token, restricted to read-only tools, and only ever sees PayPal API responses. `npm audit` for
the backend is therefore informational in CI; we will bump the package when PayPal releases a
fix.

## Reporting

Open a private security advisory on GitHub, or email the maintainer via the profile on the
repository.
