import { Link } from "react-router-dom";
import { Break, RULE_LABEL, ago, fmtDelta } from "../lib/api";

const STATUS: Record<string, string> = {
  open: "Open",
  in_progress: "Agent working",
  awaiting_approval: "Needs your decision",
  resolved: "Resolved",
  dismissed: "Dismissed",
};

const PREFER = ["status", "order_amount", "captured_total", "max_refundable", "refunded_total", "amount", "due", "fee", "evidence_submitted", "final_captures"];
function kv(obj: Record<string, unknown>, max = 2) {
  const rank = (k: string) => (PREFER.indexOf(k) === -1 ? 99 : PREFER.indexOf(k));
  const entries = Object.entries(obj)
    .filter(([, v]) => v != null && typeof v !== "object")
    .sort((a, b) => rank(a[0]) - rank(b[0]))
    .slice(0, max);
  return entries.map(([k, v]) => (
    <div key={k}>
      {k.replace(/_/g, " ")} <b>{/^[A-Z][A-Z0-9_]+$/.test(String(v)) ? String(v).toLowerCase().replace(/_/g, " ") : String(v)}</b>
    </div>
  ));
}

export function LinesHead() {
  return (
    <div className="lines-head">
      <div>Severity</div>
      <div>Break</div>
      <div className="h-kv">Expected</div>
      <div className="h-kv">Observed</div>
      <div className="r">Delta</div>
      <div className="r h-state">State</div>
    </div>
  );
}

export function LedgerLine({ b }: { b: Break }) {
  const d = b.delta_minor ?? 0;
  return (
    <Link to={`/breaks/${b.id}`} className="line">
      <div className={`sev ${b.severity}`}>{b.severity}</div>
      <div>
        <div className="title">{RULE_LABEL[b.rule] ?? b.rule}</div>
        <div className="sub">
          {b.title} · {ago(b.opened_at)}
        </div>
      </div>
      <div className="kv">{kv(b.expected)}</div>
      <div className="kv">{kv(b.observed)}</div>
      <div className={"delta " + (d ? "neg" : "")}>{d ? fmtDelta(b.delta_minor, b.currency) : ""}</div>
      <div className="state">{STATUS[b.status] ?? b.status}</div>
    </Link>
  );
}
