import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, ago } from "../lib/api";
import { LedgerLine, LinesHead } from "../components/LedgerLine";

const I = ({ d, tone }: { d: string; tone?: string }) => (
  <span className={"ic " + (tone ?? "")}>
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
  </span>
);
const P = {
  alert: "M12 9v4m0 4h.01M10.3 3.9 2.6 17.1A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.9L13.7 3.9a2 2 0 0 0-3.4 0z",
  money: "M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6",
  clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2",
  check: "M20 6 9 17l-5-5",
  book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15z",
  shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
};

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
          <div className="l"><I d={P.alert} tone={critical ? "red" : "green"} />Critical breaks</div>
          <div className={"n " + (critical ? "red" : "green")}>{critical}</div>
          <div className="s">{openBySev.warn ?? 0} warning{(openBySev.warn ?? 0) === 1 ? "" : "s"} · {openBySev.info ?? 0} note{(openBySev.info ?? 0) === 1 ? "" : "s"}</div>
        </Link>
        <div className="kpi">
          <div className="l"><I d={P.money} tone={exposure.length ? "red" : ""} />Money at stake</div>
          <div className={"n " + (exposure.length ? "red" : "")}>{exposure.length ? exposure.map(([, v]) => v).join(" / ") : "0.00"}</div>
          <div className="s">sum of open deltas{exposure.length ? `, ${exposure.map(([c]) => c).join("/")}` : ""}</div>
        </div>
        <Link to="/approvals" className="kpi">
          <div className="l"><I d={P.clock} tone={o?.approvals_pending ? "amber" : ""} />Waiting on you</div>
          <div className={"n " + (o?.approvals_pending ? "amber" : "")}>{o?.approvals_pending ?? 0}</div>
          <div className="s">agent proposals to approve</div>
        </Link>
        <div className="kpi">
          <div className="l"><I d={P.check} tone="green" />Resolved</div>
          <div className="n green">{o?.breaks_resolved ?? 0}</div>
          <div className="s">{o?.agent_runs ?? 0} agent runs</div>
        </div>
        <Link to="/ledger" className="kpi">
          <div className="l"><I d={P.book} />Ledger events</div>
          <div className="n">{o?.events ?? 0}</div>
          <div className="s">{o?.orders ?? 0} orders · {o?.captures ?? 0} captures · {o?.refunds ?? 0} refunds</div>
        </Link>
        <div className="kpi">
          <div className="l"><I d={P.shield} tone={o?.disputes_open ? "amber" : ""} />Open disputes</div>
          <div className={"n " + (o?.disputes_open ? "amber" : "")}>{o?.disputes_open ?? 0}</div>
          <div className="s">{o?.payout_items ?? 0} payout items · {o?.invoices ?? 0} invoices</div>
        </div>
      </div>

      <div className="panel">
        <header>
          <span>Open breaks</span>
          <span className="muted">{breaks.data?.length ? <Link to="/breaks">All {breaks.data.length} open</Link> : "none"}</span>
        </header>
        {breaks.data?.length ? (
          <div className="lines-wrap" style={{ border: 0, borderRadius: 0, boxShadow: "none" }}>
            <LinesHead />
            <div className="lines">{sortBySeverity(breaks.data).slice(0, 12).map((b) => <LedgerLine key={b.id} b={b} />)}</div>
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
      </div>
    </>
  );
}
