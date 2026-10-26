/* One screen with everything an operator needs to decide: what's at stake, what the agent
   proposes, why, what policy says, the evidence on both sides, the order chain, and how the
   agent got there. */
import { useState } from "react";
import { Link } from "react-router-dom";
import { ACTION_LABEL, AgentRun, Approval, Break, RULE_LABEL, ago, fmtDelta } from "../lib/api";

type Chain = {
  order: Record<string, any> | null;
  captures: Record<string, any>[];
  refunds: Record<string, any>[];
  disputes: Record<string, any>[];
  events: Record<string, any>[];
} | null;

export type Sheet = { approval: Approval | null; break: Break | null; run: AgentRun | null; chain: Chain };

function KV({ obj }: { obj: Record<string, unknown> }) {
  return (
    <dl>
      {Object.entries(obj).map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k.replace(/_/g, " ")}</dt>
          <dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function money(minor: number | null | undefined, cur: string | null | undefined) {
  if (minor == null || !cur) return "—";
  return `${(Math.abs(minor) / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })} ${cur}`;
}

function Concrete({ p }: { p: Record<string, any> }) {
  switch (p.action) {
    case "refund":
      return (
        <p>
          Refund <b>{money(p.amount_minor, p.currency)}</b> to the customer on capture <code>{p.capture_id}</code>
          {p.note_to_payer ? <> with the note “{p.note_to_payer}”</> : null}.
        </p>
      );
    case "provide_evidence":
      return (
        <>
          <p>
            Submit {p.evidences?.length ?? 0} evidence item{p.evidences?.length === 1 ? "" : "s"} on dispute <code>{p.dispute_id}</code>
            {p.message_to_buyer ? " and message the buyer" : ""}.
          </p>
          <ol className="evidence">
            {(p.evidences ?? []).map((e: any, i: number) => (
              <li key={i}>
                <b>{String(e.evidence_type).replace(/_/g, " ").toLowerCase()}</b> — {e.notes}
              </li>
            ))}
          </ol>
          {p.message_to_buyer && <p className="muted">Message: “{p.message_to_buyer}”</p>}
        </>
      );
    case "ledger_correction":
      return (
        <p>
          Set the ledger to match PayPal on <code>{p.capture_id ?? p.order_id}</code>:{" "}
          {Object.entries(p.correction ?? {}).filter(([k]) => k !== "source").map(([k, v]) => `${k} → ${v}`).join(", ")}. No money moves.
        </p>
      );
    case "escalate":
      return <p>{p.escalation_summary ?? "Hand this to a person; the agent could not resolve it safely."}</p>;
    default:
      return <p>Close the break with no change. {p.rationale ? "" : ""}</p>;
  }
}

function Policy({ a }: { a: Approval }) {
  const auto = a.policy_decision === "auto";
  return (
    <div className={"policy-strip " + (auto ? "auto" : a.policy_decision === "forbidden" ? "" : "human")}>
      <span>
        <b>{auto ? "Policy let this run on its own" : a.policy_decision === "forbidden" ? "Policy forbids this action" : "Policy requires a person"}</b>
        {" · v"}{a.policy_version}{" · "}{a.policy_reasons.join("; ")}
      </span>
    </div>
  );
}

function Investigation({ run }: { run: AgentRun }) {
  const steps = run.trace ?? [];
  const tools = steps.filter((t) => t.tool);
  const triage = steps.find((t) => t.node === "triage");
  const ctx = steps.find((t) => t.node === "load_context");
  return (
    <>
      {triage && (
        <p style={{ margin: "0 0 10px" }}>
          <b>{String(triage.specialist).replace(/_/g, " ")}</b> took it ({Math.round((triage.confidence ?? 0) * 100)}% confident). {triage.summary}
          {triage.missing_evidence?.length ? <span className="muted"> Missing: {triage.missing_evidence.join(", ")}.</span> : null}
        </p>
      )}
      {tools.length > 0 ? (
        <div className="tools">
          {tools.map((t, i) => (
            <details key={i}>
              <summary>
                {t.tool.replace(/^paypal_mcp_/, "PayPal MCP · ").replace(/^paypal_get_/, "PayPal · ").replace(/^ledger_/, "Ledger · ")}
                {t.args?.id || t.args?.order_id || t.args?.capture_id || t.args?.dispute_id ? ` ${t.args.id ?? t.args.order_id ?? t.args.capture_id ?? t.args.dispute_id}` : ""}
              </summary>
              <pre>{t.result_preview}</pre>
            </details>
          ))}
        </div>
      ) : (
        <p className="muted" style={{ margin: 0 }}>
          No tool calls — {run.model === "stub" ? "deterministic stub agent" : "the agent answered from the break alone"}.
        </p>
      )}
      {ctx?.paypal_mcp_tools?.length ? (
        <p className="muted" style={{ margin: "10px 0 0", fontSize: 12.5 }}>
          Tools available: {ctx.paypal_mcp_tools.length} from PayPal's MCP server, {ctx.native_tools?.length ?? 0} ledger/REST.
        </p>
      ) : null}
    </>
  );
}

export function Decide({ a, busy, onDecide }: { a: Approval; busy: boolean; onDecide: (ok: boolean, note: string) => void }) {
  const [note, setNote] = useState("");
  if (a.status !== "pending") {
    const r = a.execution_result;
    return (
      <div className="decided">
        <b>{a.status === "executed" ? "Executed" : a.status === "declined" ? "Declined" : a.status === "failed" ? "Failed" : a.status}</b>
        {a.decided_by ? ` by ${a.decided_by}` : ""}{a.decided_at ? ` ${ago(a.decided_at)}` : ""}
        {a.decision_note ? ` — “${a.decision_note}”` : ""}
        {r?.dry_run ? " · dry run, PayPal was not called" : ""}
        {r?.refund_id ? ` · PayPal refund ${r.refund_id} ${r.paypal_status ?? ""}` : ""}
        {r?.error ? <div className="err">{r.error}</div> : null}
      </div>
    );
  }
  return (
    <div className="decide">
      <textarea className="note" placeholder="Note for the audit trail (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row" style={{ flexDirection: "column", alignItems: "stretch", minWidth: 190 }}>
        <button className="btn green" disabled={busy} onClick={() => onDecide(true, note)}>
          {busy ? "Working…" : "Approve and execute"}
        </button>
        <button className="btn danger" disabled={busy} onClick={() => onDecide(false, note)}>
          Decline
        </button>
      </div>
    </div>
  );
}

export function DecisionSheet({ s, busy, onDecide, error }: { s: Sheet; busy: boolean; onDecide: (ok: boolean, note: string) => void; error?: string | null }) {
  const b = s.break;
  const a = s.approval;
  const p = a?.proposal ?? s.run?.proposal ?? null;
  const c = s.chain;
  if (!b) return <div className="empty">Nothing selected.</div>;
  const d = b.delta_minor ?? 0;
  return (
    <div className="decision">
      <section className="head">
        <div>
          <h2>{RULE_LABEL[b.rule] ?? b.rule}</h2>
          <div className="sub">
            {b.title}. Opened {ago(b.opened_at)} ·{" "}
            <span className={`pill ${b.severity === "critical" ? "red" : b.severity === "warn" ? "amber" : "grey"}`}>{b.severity}</span>{" "}
            <Link to={`/breaks/${b.id}`} className="muted">break #{b.id}</Link>
          </div>
        </div>
        <div className="stake">
          <div className={"n " + (d ? "delta neg" : "")}>{d ? fmtDelta(b.delta_minor, b.currency) : "—"}</div>
          <div className="l">{d ? "money in question" : "no money at stake"}</div>
        </div>
      </section>

      {p && (
        <section>
          <div className="verdict">
            <div className="act">
              {ACTION_LABEL[p.action] ?? p.action}
              <small>agent proposal · {Math.round((p.confidence ?? 0) * 100)}% confidence</small>
            </div>
            <div className="what">
              <Concrete p={p} />
              <p className="muted">{p.rationale}</p>
            </div>
          </div>
          {a && <div style={{ marginTop: 14 }}><Policy a={a} /></div>}
        </section>
      )}

      <section>
        <h3>Evidence</h3>
        <div className="t">
          <div>
            <h3>Expected</h3>
            <KV obj={b.expected} />
          </div>
          <div>
            <h3>Observed</h3>
            <KV obj={b.observed} />
          </div>
        </div>
      </section>

      {c?.order && (
        <section>
          <h3>
            Order {c.order.id} · {money(c.order.amount_minor, c.order.currency)} · {c.order.status} · {c.order.payer_email ?? "no payer email"}
          </h3>
          <div className="chain-grid">
            <div>
              <ul className="chain-list">
                {c.captures.map((x) => (
                  <li key={x.id}>
                    <span className="id">capture <code>{x.id}</code></span>
                    <span className="amt">
                      {money(x.amount_minor, x.currency)} · {x.status}
                      {x.api_status && x.api_status !== x.status ? <span className="pill red" style={{ marginLeft: 6 }}>PayPal says {x.api_status}</span> : null}
                    </span>
                  </li>
                ))}
                {c.refunds.map((x) => (
                  <li key={x.id}>
                    <span className="id">refund <code>{x.id}</code></span>
                    <span className="amt delta neg">−{money(x.amount_minor, x.currency)} · {x.status}</span>
                  </li>
                ))}
                {c.disputes.map((x) => (
                  <li key={x.id}>
                    <span className="id">dispute <code>{x.id}</code></span>
                    <span className="amt">{x.reason} · {x.status}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <ul className="chain-list">
                {c.events.slice(-8).map((e) => (
                  <li key={e.id}>
                    <span className="id">{new Date(e.occurred_at).toLocaleString()}</span>
                    <span className="amt" style={{ fontWeight: 500 }}>{e.event_type} <span className="muted">· {e.source}</span></span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      )}

      {s.run && (
        <section>
          <h3>How the agent got here</h3>
          <Investigation run={s.run} />
        </section>
      )}

      {a && (
        <section>
          <h3>{a.status === "pending" ? "Your decision" : "Decision"}</h3>
          <Decide a={a} busy={busy} onDecide={onDecide} />
          {error && <div className="err">{error}</div>}
        </section>
      )}
    </div>
  );
}
