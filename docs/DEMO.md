# Demo video script (under 3 minutes)

Judges are not required to watch past 3:00. Target 2:40. Record at 1440×900, console in
light mode, PayPal sandbox dashboard in a second tab. No music. Talk slowly.

## 0:00–0:20 — the problem (sandbox dashboard on screen)

"This is a PayPal merchant dashboard. Somewhere in here a capture doesn't match its order,
a refund got recorded twice, and a dispute is three days from its deadline. Nobody knows,
because nothing is checking. Ledgerline is the thing that checks — and then acts."

## 0:20–0:50 — the ledger and the breaks (Overview)

Switch to the console Overview.

"Ledgerline keeps its own copy of the truth: an append-only ledger built from verified
webhooks, plus PayPal's Transaction Search and Disputes API as a second witness. Twelve
rules run on every event. Each line here is a break: what we expected, what we observed,
the money at stake."

Point at `Ledger disagrees with PayPal` and `Dispute response due`.

## 0:50–1:40 — the agent (Break detail → Approvals)

Click **Ledger disagrees with PayPal**.

"An agent picked this up. It loaded the order chain, called PayPal's Payments API, and
found the capture was partially refunded at PayPal but our ledger never saw it. It proposes
a correction, with the exact fields and its reasoning. It cannot execute: policy says
corrections for this rule need a person."

Click **Approve and execute**. Show the break flip to resolved and the correction event in
the chain.

Go to **Approvals**. Open **Dispute response due**.

"For the dispute, the dispute-defender assembled an evidence packet — fulfilment,
return policy — in the exact shape PayPal's provide-evidence endpoint expects, plus a
message to the buyer. Disputes are never automatic. I approve, and Ledgerline submits it
with an idempotency key, so a retry can never double-submit."

## 1:40–2:10 — the policy and the trace (Agent runs)

Open **Agent runs**, select the executed one.

"Every run is a checkpointed LangGraph: triage, specialist, bounded tool calls, structured
proposal, policy gate. The agent only has read tools. The one code path that touches
PayPal runs after the gate. And here's a refund that ran without me — $1.00 over-charge,
fresh order, no dispute, under the threshold in policy.yaml — executed and logged."

## 2:10–2:40 — what's underneath (Ledger tab, then README)

"Underneath: idempotent ledger, deterministic projections you can rebuild from scratch,
Postgres queue, Render deployment with a worker and a web service. Twenty-three tests
against a real database. And a fixture replay so anyone can run this demo in five minutes
with no keys at all."

Close on the README's five-minute section.

## Recording checklist

- `ledgerline reset --yes && LLM_MODEL=stub PAYPAL_DRY_RUN=true ledgerline sim replay` before recording, so the state matches this script.
- For the live-agent take, run with a real `LLM_MODEL` and show a tool call in the trace.
- Approve `WEBHOOK_API_DRIFT` first (it resolves visibly), then the dispute.
- Keep the terminal out of the video except for the single replay command.
- Upload to YouTube as Public, under 3:00, no third-party music or logos.
