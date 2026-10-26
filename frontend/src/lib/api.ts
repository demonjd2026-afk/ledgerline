export type Break = {
  id: number;
  rule: string;
  severity: "info" | "warn" | "critical";
  status: string;
  resource_type: string;
  resource_id: string;
  correlation_id: string | null;
  title: string;
  expected: Record<string, unknown>;
  observed: Record<string, unknown>;
  delta_minor: number | null;
  delta?: string;
  currency: string | null;
  opened_at: string;
  resolved_at: string | null;
  resolution: Record<string, unknown> | null;
  agent_run_id?: number | null;
  agent_status?: string | null;
};

export type Approval = {
  id: number;
  agent_run_id: number;
  break_id: number;
  action: string;
  proposal: Record<string, any>;
  policy_version: number;
  policy_decision: string;
  policy_reasons: string[];
  status: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  execution_result: Record<string, any> | null;
  created_at: string;
  break?: Break | null;
};

export type AgentRun = {
  id: number;
  break_id: number;
  thread_id: string;
  status: string;
  specialist: string | null;
  model: string | null;
  trace: Array<Record<string, any>>;
  proposal: Record<string, any> | null;
  outcome: Record<string, any> | null;
  started_at: string;
  finished_at: string | null;
  error: string | null;
};

export type Overview = {
  events: number;
  orders: number;
  captures: number;
  refunds: number;
  disputes_open: number;
  payout_items: number;
  invoices: number;
  breaks_open_by_severity: Record<string, number>;
  breaks_resolved: number;
  exposure: Record<string, string>;
  approvals_pending: number;
  agent_runs: number;
  webhooks_received: number;
  webhooks_rejected: number;
  jobs: Record<string, number>;
  last_event_at: string;
  paypal_configured: boolean;
  llm_model: string;
};

const TOKEN_KEY = "ledgerline.operator_token";
function token(): string {
  try { return sessionStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
}
export function setToken(t: string) {
  try { sessionStorage.setItem(TOKEN_KEY, t); } catch {}
}

async function j<T>(input: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const t = token();
  if (t) headers["x-operator-token"] = t;
  const r = await fetch(input, { ...init, headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) } });
  if (r.status === 401) {
    const entered = window.prompt("This console is protected. Enter the operator token.");
    if (entered) {
      setToken(entered.trim());
      return j<T>(input, init);
    }
    throw new Error("operator token required");
  }
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      const b = await r.json();
      msg = b.detail || JSON.stringify(b);
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  overview: () => j<Overview>("/api/overview"),
  breaks: (status?: string) => j<Break[]>(`/api/breaks${status ? `?status=${status}` : ""}`),
  breakDetail: (id: number) => j<{ break: Break; runs: AgentRun[]; approvals: Approval[] }>(`/api/breaks/${id}`),
  runBreak: (id: number) => j<AgentRun>(`/api/breaks/${id}/run`, { method: "POST" }),
  dismiss: (id: number, note: string) => j<Break>(`/api/breaks/${id}/dismiss`, { method: "POST", body: JSON.stringify({ note, by: "operator" }) }),
  reconcile: () => j<{ new_breaks: number }>("/api/reconcile", { method: "POST" }),
  approvals: (status = "pending") => j<Approval[]>(`/api/approvals?status=${status}`),
  sheet: (id: number) => j<any>(`/api/approvals/${id}/sheet`),
  decide: (id: number, approved: boolean, note: string) =>
    j<{ run: AgentRun; approval: Approval }>(`/api/approvals/${id}/decide`, { method: "POST", body: JSON.stringify({ approved, note, by: "operator" }) }),
  runs: () => j<AgentRun[]>("/api/runs"),
  run: (id: number) => j<{ run: AgentRun; break: Break | null; approvals: Approval[] }>(`/api/runs/${id}`),
  ledger: (table: string) => j<Record<string, any>[]>(`/api/ledger/${table}`),
  events: (q = "") => j<Record<string, any>[]>(`/api/ledger/events${q}`),
  chain: (orderId: string) => j<any>(`/api/orders/${orderId}/chain`),
  policy: () => j<any>("/api/policy"),
};

export function fmtDelta(minor: number | null, currency: string | null): string {
  if (minor == null || !currency) return "";
  const sign = minor < 0 ? "−" : "+";
  const v = Math.abs(minor) / 100;
  return `${sign}${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export const RULE_LABEL: Record<string, string> = {
  ORDER_AMOUNT_MISMATCH: "Captured ≠ order amount",
  DUPLICATE_CAPTURE: "Order captured twice",
  DUPLICATE_ORDER: "Customer charged twice",
  CAPTURE_WITHOUT_ORDER: "Capture for unknown order",
  REFUND_EXCEEDS_CAPTURE: "Refunds exceed capture",
  WEBHOOK_API_DRIFT: "Ledger disagrees with PayPal",
  STALE_AUTHORIZATION: "Authorisation never captured",
  DISPUTE_RESPONSE_DUE: "Dispute response due",
  DISPUTE_UNRECONCILED_HOLD: "Dispute hold unmatched",
  PAYOUT_ITEM_FAILED: "Payout failed",
  PAYOUT_FEE_VARIANCE: "Payout fee out of band",
  INVOICE_PAID_NO_CAPTURE: "Invoice paid, no payment found",
  SETTLEMENT_LAG: "Not yet in reporting",
};

export const ACTION_LABEL: Record<string, string> = {
  refund: "Refund the customer",
  provide_evidence: "Submit dispute evidence",
  ledger_correction: "Correct the ledger",
  no_action: "No action needed",
  escalate: "Escalate to a person",
};
