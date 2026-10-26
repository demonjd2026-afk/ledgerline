import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, RULE_LABEL, ago } from "../lib/api";
import { DecisionBox, PolicyLine, ProposalBody } from "../components/ProposalCard";

export default function Approvals() {
  const [tab, setTab] = useState<"pending" | "executed,declined,failed">("pending");
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["approvals", tab], queryFn: () => api.approvals(tab) });
  const decide = useMutation({
    mutationFn: ({ aid, ok, note }: { aid: number; ok: boolean; note: string }) => api.decide(aid, ok, note),
    onSuccess: () => qc.invalidateQueries(),
  });

  return (
    <>
      <h1>Approvals</h1>
      <p className="lede">
        Everything here is an action the agent wants to take but policy says a person must sign off: refunds above the limit, anything touching a dispute, corrections outside the allowed rules. Approving executes it immediately with an idempotency key, so a retry can never run it twice.
      </p>
      <div className="tabs">
        <button className={tab === "pending" ? "on" : ""} onClick={() => setTab("pending")}>Waiting</button>
        <button className={tab !== "pending" ? "on" : ""} onClick={() => setTab("executed,declined,failed")}>Decided</button>
      </div>
      {data.length === 0 && <div className="empty">{tab === "pending" ? "Nothing waiting on you." : "No decisions recorded yet."}</div>}
      {data.map((a) => (
        <div className="sheet" key={a.id}>
          <div className="row spread">
            <div>
              <h2 style={{ marginBottom: 2 }}>
                {a.break ? RULE_LABEL[a.break.rule] ?? a.break.rule : `Break #${a.break_id}`}
              </h2>
              <div className="policy" style={{ margin: 0 }}>
                {a.break?.title} · <Link to={`/breaks/${a.break_id}`}>evidence</Link> · proposed {ago(a.created_at)}
              </div>
            </div>
            <span className={`pill ${a.status === "pending" ? "amber" : a.status === "executed" ? "green" : a.status === "failed" ? "red" : "grey"}`}>{a.status}</span>
          </div>
          <ProposalBody proposal={a.proposal} />
          <PolicyLine a={a} />
          <DecisionBox a={a} busy={decide.isPending} onDecide={(ok, note) => decide.mutate({ aid: a.id, ok, note })} />
          {a.execution_result?.error && <p className="policy" style={{ color: "var(--red)" }}>Execution failed: {a.execution_result.error}</p>}
        </div>
      ))}
      {decide.error && <p className="policy" style={{ color: "var(--red)" }}>{String(decide.error.message)}</p>}
    </>
  );
}
