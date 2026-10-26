import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { DecisionSheet, Sheet } from "../components/DecisionSheet";
import { Trace } from "../components/Trace";

export default function BreakDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["break", id], queryFn: () => api.breakDetail(Number(id)) });
  const chain = useQuery({
    queryKey: ["chain", q.data?.break.correlation_id],
    queryFn: () => api.chain(q.data!.break.correlation_id!),
    enabled: !!q.data?.break.correlation_id,
    refetchInterval: false,
  });
  const run = useMutation({ mutationFn: () => api.runBreak(Number(id)), onSuccess: () => qc.invalidateQueries() });
  const dismiss = useMutation({ mutationFn: () => api.dismiss(Number(id), "Dismissed from console"), onSuccess: () => qc.invalidateQueries() });
  const decide = useMutation({
    mutationFn: ({ aid, ok, note }: { aid: number; ok: boolean; note: string }) => api.decide(aid, ok, note),
    onSuccess: () => qc.invalidateQueries(),
  });

  if (!q.data) return <div className="empty">Loading…</div>;
  const b = q.data.break;
  const latestRun = q.data.runs.at(-1) ?? null;
  const latestApproval = q.data.approvals.at(-1) ?? null;
  const sheet: Sheet = { approval: latestApproval, break: b, run: latestRun, chain: chain.data?.order ? chain.data : null };
  const canRun = b.status !== "resolved" && latestApproval?.status !== "pending" && !run.isPending;

  return (
    <>
      <div className="row spread" style={{ marginBottom: 14 }}>
        <div className="muted" style={{ fontSize: 13 }}>
          <Link to="/breaks">Breaks</Link> / {b.rule} / #{b.id}
        </div>
        <div className="row">
          {canRun && (
            <button className="btn" onClick={() => run.mutate()}>
              {latestRun ? "Run agent again" : "Run agent"}
            </button>
          )}
          {run.isPending && <span className="muted">Agent working…</span>}
          {b.status !== "resolved" && (
            <button className="btn quiet" onClick={() => dismiss.mutate()}>Dismiss</button>
          )}
        </div>
      </div>
      <DecisionSheet
        s={sheet}
        busy={decide.isPending}
        onDecide={(ok, note) => latestApproval && decide.mutate({ aid: latestApproval.id, ok, note })}
        error={decide.error ? String(decide.error.message) : latestRun?.error ? `Run failed: ${latestRun.error}` : null}
      />
      {!latestRun && (
        <p className="muted" style={{ marginTop: 12 }}>
          No agent run yet. The worker picks up critical and warning breaks automatically; "Run agent" starts one now.
        </p>
      )}
      {latestRun && (
        <div className="sheet" style={{ marginTop: 14 }}>
          <h2>Full trace</h2>
          <Trace trace={latestRun.trace} />
        </div>
      )}
    </>
  );
}
