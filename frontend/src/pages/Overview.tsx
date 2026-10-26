import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, ago } from "../lib/api";
import { LedgerLine, LinesHead } from "../components/LedgerLine";

const SEV = { critical: 0, warn: 1, info: 2 } as const;
function sortBySeverity<T extends { severity: keyof typeof SEV; opened_at: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => SEV[a.severity] - SEV[b.severity] || b.opened_at.localeCompare(a.opened_at));
}

export default function Overview() {
  const qc = useQueryClient();
  const ov = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const breaks = useQuery({ queryKey: ["breaks", "open"], queryFn: () => api.breaks("open,in_progress,awaiting_approval") });
  const recon = useMutation({ mutationFn: api.reconcile, onSuccess: () => qc.invalidateQueries() });
  const o = ov.data;
  const openBySev = o?.breaks_open_by_severity ?? {};
  const critical = openBySev.critical ?? 0;
  const exposure = Object.entries(o?.exposure ?? {});

  return (
    <>
      <div className="row spread">
        <div>
          <h1>Books against PayPal</h1>
          <p className="lede">
            Every order, capture, refund, payout, dispute and invoice, reconciled continuously against PayPal's own record.
            {o?.last_event_at && <> Last event {ago(o.last_event_at)}.</>}
          </p>
        </div>
        <button className="btn quiet" onClick={() => recon.mutate()} disabled={recon.isPending}>
          {recon.isPending ? "Reconciling…" : "Reconcile now"}
        </button>
      </div>

      <div className="kpis">
        <Link to="/breaks" className="kpi">
          <div className={"n " + (critical ? "red" : "green")}>{critical}</div>
          <div className="l">Critical breaks</div>
          <div className="s">{openBySev.warn ?? 0} warning{(openBySev.warn ?? 0) === 1 ? "" : "s"} · {openBySev.info ?? 0} note{(openBySev.info ?? 0) === 1 ? "" : "s"}</div>
        </Link>
        <div className="kpi">
          <div className={"n " + (exposure.length ? "red" : "")}>{exposure.length ? exposure.map(([, v]) => v).join(" / ") : "0.00"}</div>
          <div className="l">Money in question{exposure.length ? ` (${exposure.map(([c]) => c).join("/")})` : ""}</div>
          <div className="s">sum of open deltas</div>
        </div>
        <Link to="/approvals" className="kpi">
          <div className={"n " + (o?.approvals_pending ? "amber" : "")}>{o?.approvals_pending ?? 0}</div>
          <div className="l">Waiting on you</div>
          <div className="s">agent proposals to approve</div>
        </Link>
        <div className="kpi">
          <div className="n green">{o?.breaks_resolved ?? 0}</div>
          <div className="l">Resolved</div>
          <div className="s">{o?.agent_runs ?? 0} agent runs</div>
        </div>
        <Link to="/ledger" className="kpi">
          <div className="n">{o?.events ?? 0}</div>
          <div className="l">Ledger events</div>
          <div className="s">{o?.orders ?? 0} orders · {o?.captures ?? 0} captures · {o?.refunds ?? 0} refunds</div>
        </Link>
        <div className="kpi">
          <div className={"n " + (o?.disputes_open ? "amber" : "")}>{o?.disputes_open ?? 0}</div>
          <div className="l">Open disputes</div>
          <div className="s">{o?.payout_items ?? 0} payout items · {o?.invoices ?? 0} invoices</div>
        </div>
      </div>

      <h2>Open breaks</h2>
      {breaks.data?.length ? (
        <div>
          <LinesHead />
          <div className="lines">{sortBySeverity(breaks.data).slice(0, 12).map((b) => <LedgerLine key={b.id} b={b} />)}</div>
          {breaks.data.length > 12 && (
            <p className="lede" style={{ marginTop: 10 }}>
              <Link to="/breaks">All {breaks.data.length} open breaks</Link>
            </p>
          )}
        </div>
      ) : (
        <div className="empty">
          Nothing is out of line. New breaks appear here the moment a webhook or poll disagrees with the ledger.
          {!o?.events && (
            <>
              <br />
              <br />
              To see the system working without PayPal credentials, run <code>ledgerline sim replay</code>.
            </>
          )}
        </div>
      )}
    </>
  );
}
