/* One screen with everything an operator needs to decide. Leads with one sentence; detail is
   there but folded. */
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

const money = (minor: number | null | undefined, cur: string | null | undefined) =>
  minor == null || !cur ? "—" : `${(Math.abs(minor) / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })} ${cur}`;

const human = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
function pretty(v: unknown): string {
  if (v == null) return "—";
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  const str = String(v);
  if (ISO.test(str)) return new Date(str).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  if (/^[A-Z][A-Z0-9_]+$/.test(str)) return human(str.toLowerCase());
  if (str === "true") return "Yes";
  if (str === "false") return "No";
  return str;
}

function Facts({ obj }: { obj: Record<string, unknown> }) {
  return (
    <dl className="facts">
      {Object.entries(obj).map(([k, v]) => (
        <div key={k}>
          <dt>{human(k)}</dt>
          <dd>{pretty(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Headline({ p, b }: { p: Record<string, any>; b: Break }) {
  if (p.headline) return <>{p.headline}</>;
  // Older runs without a headline: derive one.
  switch (p.action) {
    case "refund":
      return <>Refund {money(p.amount_minor, p.currency)} to the customer on capture {p.capture_id}.</>;
    case "provide_evidence":
      return <>Submit {p.evidences?.length ?? 0} evidence items on dispute {p.dispute_id}.</>;
    case "ledger_correction":
      return <>Correct the ledger to match PayPal for {p.capture_id ?? p.order_id}; no money moves.</>;
    case "escalate":
      return <>Hand this to a person.</>;
    default:
      return <>Close {RULE_LABEL[b.rule]?.toLowerCase() ?? b.rule} with no change.</>;
  }
}

function ActionDetail({ p }: { p: Record<string, any> }) {
  switch (p.action) {
    case "refund":
      return (
        <dl className="facts">
          <div><dt>Amount</dt><dd>{money(p.amount_minor, p.currency)}</dd></div>
          <div><dt>Capture</dt><dd><code>{p.capture_id}</code></dd></div>
          {p.note_to_payer && <div><dt>Note to customer</dt><dd>“{p.note_to_payer}”</dd></div>}
        </dl>
      );
    case "provide_evidence":
      return (
        <>
          <dl className="facts">
            <div><dt>Dispute</dt><dd><code>{p.dispute_id}</code></dd></div>
          </dl>
          <ol className="evidence">
            {(p.evidences ?? []).map((e: any, i: number) => (
              <li key={i}><b>{human(String(e.evidence_type).toLowerCase())}</b> — {e.notes}</li>
            ))}
          </ol>
          {p.message_to_buyer && <p className="muted" style={{ margin: "6px 0 0" }}>Message to buyer: “{p.message_to_buyer}”</p>}
        </>
      );
    case "ledger_correction": {
      const c = p.correction ?? {};
      return (
        <dl className="facts">
          {p.capture_id && <div><dt>Capture</dt><dd><code>{p.capture_id}</code></dd></div>}
          {Object.entries(c).filter(([k]) => k !== "source").map(([k, v]) => (
            <div key={k}><dt>{human(k)}</dt><dd>{String(v)}</dd></div>
          ))}
          <div><dt>Money moves</dt><dd>No</dd></div>
        </dl>
      );
    }
    case "escalate":
      return p.escalation_summary ? <p style={{ margin: 0 }}>{p.escalation_summary}</p> : null;
    default:
      return null;
  }
}

function Policy({ a }: { a: Approval }) {
  const cls = a.policy_decision === "auto" ? "auto" : a.policy_decision === "forbidden" ? "" : "human";
  const label = a.policy_decision === "auto" ? "Ran automatically" : a.policy_decision === "forbidden" ? "Forbidden by policy" : "Needs a person";
  return (
    <div className={"policy-strip " + cls}>
      <b>{label}</b>
      <span>{a.policy_reasons.join("; ")}</span>
      <span className="muted">policy v{a.policy_version}</span>
    </div>
  );
}

function Investigation({ run }: { run: AgentRun }) {
  const steps = run.trace ?? [];
  const tools = steps.filter((t) => t.tool);
  const triage = steps.find((t) => t.node === "triage");
  const label = (t: any) =>
    t.tool.startsWith("paypal_mcp_") ? ["PayPal MCP", t.tool.slice(11)] : t.tool.startsWith("paypal_get_") ? ["PayPal", t.tool.slice(11)] : ["Ledger", t.tool.replace(/^ledger_/, "")];
  const arg = (t: any) => t.args?.id ?? t.args?.order_id ?? t.args?.capture_id ?? t.args?.dispute_id ?? t.args?.refund_id ?? "";
  return (
    <>
      {triage && (
        <p style={{ margin: "0 0 10px" }}>
          <b>{human(triage.specialist)}</b> · {Math.round((triage.confidence ?? 0) * 100)}% confident. {triage.summary}
        </p>
      )}
      {tools.length ? (
        <div className="tools">
          {tools.map((t, i) => {
            const [src, name] = label(t);
            const failed = /"error"|RESOURCE_NOT_FOUND|"ok":false/.test(t.result_preview ?? "");
            return (
              <details key={i}>
                <summary>
                  <span className={"src " + (src === "PayPal MCP" ? "mcp" : "")}>{src}</span> {human(name)} <code>{arg(t)}</code>
                  {failed && <span className="pill red" style={{ marginLeft: 6 }}>not found</span>}
                </summary>
                <pre>{t.result_preview}</pre>
              </details>
            );
          })}
        </div>
      ) : (
        <p className="muted" style={{ margin: 0 }}>No tool calls{run.model === "stub" ? " (deterministic stub)" : ""}.</p>
      )}
    </>
  );
}

export function Decide({ a, busy, onDecide }: { a: Approval; busy: boolean; onDecide: (ok: boolean, note: string) => void }) {
  const [note, setNote] = useState("");
  if (a.status !== "pending") {
    const r = a.execution_result;
    return (
      <div className="decided">
        <b>{human(a.status)}</b>
        {a.decided_by ? ` by ${a.decided_by}` : ""}{a.decided_at ? ` · ${ago(a.decided_at)}` : ""}
        {a.decision_note ? ` · “${a.decision_note}”` : ""}
        {r?.dry_run ? " · dry run, PayPal not called" : ""}
        {r?.refund_id ? ` · PayPal refund ${r.refund_id} ${r.paypal_status ?? ""}` : ""}
        {r?.error ? <div className="err">{r.error}</div> : null}
      </div>
    );
  }
  return (
    <div className="decide">
      <textarea className="note" placeholder="Note for the audit trail (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="decide-btns">
        <button className="btn green" disabled={busy} onClick={() => onDecide(true, note)}>{busy ? "Working…" : "Approve and execute"}</button>
        <button className="btn danger" disabled={busy} onClick={() => onDecide(false, note)}>Decline</button>
      </div>
    </div>
  );
}

export function DecisionSheet({ s, busy, onDecide, error }: { s: Sheet; busy: boolean; onDecide: (ok: boolean, note: string) => void; error?: string | null }) {
  const b = s.break;
  const a = s.approval;
  const p = a?.proposal ?? s.run?.proposal ?? null;
  const c = s.chain;
  const [more, setMore] = useState(false);
  if (!b) return <div className="empty">Nothing selected.</div>;
  const d = b.delta_minor ?? 0;

  return (
    <div className="decision">
      <section className="head">
        <div>
          <div className="eyebrow">
            <span className={`pill ${b.severity === "critical" ? "red" : b.severity === "warn" ? "amber" : "grey"}`}>{b.severity}</span>
            {b.status === "resolved" ? (
              <span className="pill green">resolved{b.resolved_at ? ` · ${ago(b.resolved_at)}` : ""}</span>
            ) : b.status === "awaiting_approval" ? (
              <span className="pill amber">awaiting approval</span>
            ) : null}
            <span className="muted">{human(b.resource_type)} <code>{b.resource_id}</code> · opened {ago(b.opened_at)} · <Link to={`/breaks/${b.id}`}>break #{b.id}</Link></span>
          </div>
          <h2>{RULE_LABEL[b.rule] ?? b.rule}</h2>
          <div className="sub">{b.title.replace(/\d{4}-\d{2}-\d{2}T[\d:+.]+/g, (m) => new Date(m).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })).replace(/\(([A-Z_]+)\)/g, (_, w) => `(${human(w.toLowerCase())})`)}</div>
        </div>
        <div className="stake">
          <div className={"n " + (d ? "delta neg" : "")}>{d ? fmtDelta(b.delta_minor, b.currency) : "—"}</div>
          <div className="l">{d ? "in question" : "no money at stake"}</div>
        </div>
      </section>

      {p && (
        <section className="proposal">
          <div className="eyebrow"><span>Agent proposal</span><span className="muted">{Math.round((p.confidence ?? 0) * 100)}% confidence</span></div>
          <div className="headline">
            <span className="act">{ACTION_LABEL[p.action] ?? p.action}</span>
            <span className="text"><Headline p={p} b={b} /></span>
          </div>
          <ActionDetail p={p} />
          {p.rationale && (
            <div className="why">
              <button className="linkish" onClick={() => setMore(!more)}>{more ? "Hide the agent's reasoning" : "Why the agent thinks so"}</button>
              {more && <p>{p.rationale}</p>}
            </div>
          )}
          {a && <Policy a={a} />}
        </section>
      )}

      <section>
        <div className="eyebrow"><span>Evidence</span></div>
        <div className="t">
          <div><h3>Expected</h3><Facts obj={b.expected} /></div>
          <div><h3>Observed</h3><Facts obj={b.observed} /></div>
        </div>
      </section>

      {c?.order && (
        <section>
          <div className="eyebrow">
            <span>Order {c.order.id}</span>
            <span className="muted">{money(c.order.amount_minor, c.order.currency)} · {c.order.status}{c.order.payer_email ? ` · ${c.order.payer_email}` : ""}</span>
          </div>
          <div className="chain-grid">
            <ul className="chain-list">
              {c.captures.map((x) => (
                <li key={x.id}>
                  <span className="id">Capture <code>{x.id}</code></span>
                  <span className="amt">
                    {money(x.amount_minor, x.currency)} · {x.status}
                    {x.api_status && x.api_status !== x.status ? <span className="pill red" style={{ marginLeft: 6 }}>PayPal: {x.api_status}</span> : null}
                  </span>
                </li>
              ))}
              {c.refunds.map((x) => (
                <li key={x.id}>
                  <span className="id">Refund <code>{x.id}</code></span>
                  <span className="amt delta neg">−{money(x.amount_minor, x.currency)} · {x.status}</span>
                </li>
              ))}
              {c.disputes.map((x) => (
                <li key={x.id}>
                  <span className="id">Dispute <code>{x.id}</code></span>
                  <span className="amt">{human(String(x.reason ?? "").toLowerCase())} · {x.status}</span>
                </li>
              ))}
            </ul>
            <ul className="chain-list">
              {c.events.slice(-6).map((e) => (
                <li key={e.id}>
                  <span className="id">{new Date(e.occurred_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</span>
                  <span className="amt" style={{ fontWeight: 500 }}>{human(String(e.event_type).toLowerCase())} <span className="muted">· {e.source}</span></span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {s.run && (
        <section>
          <div className="eyebrow"><span>Investigation</span><span className="muted">{(s.run.trace ?? []).filter((t) => t.tool).length} tool calls</span></div>
          <Investigation run={s.run} />
        </section>
      )}

      {a && (
        <section>
          <div className="eyebrow"><span>{a.status === "pending" ? "Your decision" : "Decision"}</span></div>
          <Decide a={a} busy={busy} onDecide={onDecide} />
          {error && <div className="err">{error}</div>}
        </section>
      )}
    </div>
  );
}
