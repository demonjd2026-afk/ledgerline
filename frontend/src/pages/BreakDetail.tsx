import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, RULE_LABEL, ago, fmtDelta } from "../lib/api";
import { DecisionBox, PolicyLine, ProposalBody } from "../components/ProposalCard";
import { Trace } from "../components/Trace";

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

export default function BreakDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["break", id], queryFn: () => api.breakDetail(Number(id)) });
  const run = useMutation({ mutationFn: () => api.runBreak(Number(id)), onSuccess: () => qc.invalidateQueries() });
  const decide = useMutation({
    mutationFn: ({ aid, ok, note }: { aid: number; ok: boolean; note: string }) => api.decide(aid, ok, note),
    onSuccess: () => qc.invalidateQueries(),
  });
  const dismiss = useMutation({ mutationFn: () => api.dismiss(Number(id), "Dismissed from console"), onSuccess: () => qc.invalidateQueries() });
  const chain = useQuery({
    queryKey: ["chain", q.data?.break.correlation_id],
    queryFn: () => api.chain(q.data!.break.correlation_id!),
    enabled: !!q.data?.break.correlation_id,
    refetchInterval: false,
  });

  if (!q.data) return <div className="empty">Loading…</div>;
  const b = q.data.break;
  const latestRun = q.data.runs.at(-1);
  const latestApproval = q.data.approvals.at(-1);
  const d = b.delta_minor ?? 0;

  return (
    <>
      <p className="lede" style={{ marginBottom: 6 }}>
        <Link to="/breaks">Breaks</Link> / {b.rule}
      </p>
      <div className="row spread">
        <div>
          <h1>{RULE_LABEL[b.rule] ?? b.rule}</h1>
          <p className="lede">
            {b.title}. Opened {ago(b.opened_at)}.{" "}
            <span className={`pill ${b.severity === "critical" ? "red" : b.severity === "warn" ? "amber" : "grey"}`}>{b.severity}</span>{" "}
            <span className={`pill ${b.status === "resolved" ? "green" : b.status === "awaiting_approval" ? "amber" : "blue"}`}>{b.status.replace(/_/g, " ")}</span>
          </p>
        </div>
        <div className="row">
          {b.status !== "resolved" && !latestApproval?.status.match(/pending/) && (
            <button className="btn" onClick={() => run.mutate()} disabled={run.isPending}>
              {run.isPending ? "Agent working…" : latestRun ? "Run agent again" : "Run agent"}
            </button>
          )}
          {b.status !== "resolved" && (
            <button className="btn quiet" onClick={() => dismiss.mutate()}>
              Dismiss
            </button>
          )}
        </div>
      </div>

      <div className="two">
        <div>
          <div className="sheet">
            <h2>Evidence</h2>
            <div className="t">
              <div>
                <h4>Expected</h4>
                <KV obj={b.expected} />
              </div>
              <div>
                <h4>Observed</h4>
                <KV obj={b.observed} />
              </div>
            </div>
            {b.delta_minor != null && (
              <p style={{ marginTop: 12 }}>
                Difference <b className={"delta " + (d ? "neg" : "")}>{fmtDelta(b.delta_minor, b.currency)}</b>
              </p>
            )}
            {b.resolution && (
              <p className="policy">
                Resolution: <b>{String(b.resolution.kind).replace(/_/g, " ")}</b>
                {b.resolution.note ? <> — {String(b.resolution.note)}</> : null}
                {b.resolution.by ? <> · {String(b.resolution.by)}</> : null}
              </p>
            )}
          </div>

          {chain.data?.order && (
            <div className="sheet">
              <h2>Order chain {b.correlation_id}</h2>
              <p className="policy">
                {chain.data.order.amount} {chain.data.order.currency} · {chain.data.order.status} · {chain.data.order.payer_email ?? "no payer email"}
              </p>
              <div className="t">
                <div>
                  <h4>Captures</h4>
                  {chain.data.captures.map((c: any) => (
                    <div key={c.id} className="kv">
                      <code>{c.id}</code> {c.amount} {c.currency} · {c.status}
                      {c.api_status && c.api_status !== c.status && <span className="pill red" style={{ marginLeft: 6 }}>PayPal: {c.api_status}</span>}
                    </div>
                  ))}
                  <h4 style={{ marginTop: 10 }}>Refunds</h4>
                  {chain.data.refunds.length ? chain.data.refunds.map((r: any) => (
                    <div key={r.id} className="kv">
                      <code>{r.id}</code> {r.amount} {r.currency} · {r.status}
                    </div>
                  )) : <div className="kv">none</div>}
                  {chain.data.disputes.length > 0 && (
                    <>
                      <h4 style={{ marginTop: 10 }}>Disputes</h4>
                      {chain.data.disputes.map((x: any) => (
                        <div key={x.id} className="kv">
                          <code>{x.id}</code> {x.reason} · {x.status}
                        </div>
                      ))}
                    </>
                  )}
                </div>
                <div>
                  <h4>Events</h4>
                  {chain.data.events.map((e: any) => (
                    <div key={e.id} className="kv">
                      {new Date(e.occurred_at).toLocaleString()} · <b>{e.event_type}</b> · {e.source}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        <div>
          <div className="sheet">
            <h2>Agent</h2>
            {!latestRun && <div className="empty">No run yet. The worker picks up critical and warning breaks automatically; you can also run it now.</div>}
            {latestRun?.proposal && <ProposalBody proposal={latestRun.proposal} />}
            {latestApproval && <PolicyLine a={latestApproval} />}
            {latestApproval && (
              <DecisionBox a={latestApproval} busy={decide.isPending} onDecide={(ok, note) => decide.mutate({ aid: latestApproval.id, ok, note })} />
            )}
            {decide.error && <p className="policy" style={{ color: "var(--red)" }}>{String(decide.error.message)}</p>}
            {latestRun?.error && <p className="policy" style={{ color: "var(--red)" }}>Run failed: {latestRun.error}</p>}
          </div>
          {latestRun && (
            <div className="sheet">
              <h2>What the agent did</h2>
              <Trace trace={latestRun.trace} />
            </div>
          )}
        </div>
      </div>
    </>
  );
}
