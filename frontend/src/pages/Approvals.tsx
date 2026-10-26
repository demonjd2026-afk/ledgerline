import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useNavigate } from "react-router-dom";
import { api, Approval, ACTION_LABEL, RULE_LABEL, ago, fmtDelta } from "../lib/api";
import { DecisionSheet, Sheet } from "../components/DecisionSheet";

type Tab = "pending" | "executed,declined,failed";

export default function Approvals() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("pending");
  const list = useQuery({ queryKey: ["approvals", tab], queryFn: () => api.approvals(tab) });
  const sheet = useQuery<Sheet>({ queryKey: ["sheet", id], queryFn: () => api.sheet(Number(id)), enabled: !!id });
  const decide = useMutation({
    mutationFn: ({ aid, ok, note }: { aid: number; ok: boolean; note: string }) => api.decide(aid, ok, note),
    onSuccess: () => qc.invalidateQueries(),
  });

  // Land on the first item so the page is never empty on the right.
  useEffect(() => {
    if (!id && list.data?.length) nav(`/approvals/${list.data[0].id}`, { replace: true });
  }, [id, list.data, nav]);

  const SEV: Record<string, number> = { critical: 0, warn: 1, info: 2 };
  const rows = [...(list.data ?? [])].sort(
    (x, y) => (SEV[x.break?.severity ?? "info"] - SEV[y.break?.severity ?? "info"]) || Math.abs(y.break?.delta_minor ?? 0) - Math.abs(x.break?.delta_minor ?? 0)
  );
  return (
    <>
      <div className="row spread" style={{ marginBottom: 14 }}>
        <div>
          <h1>Approvals</h1>
          <p className="lede" style={{ marginBottom: 0 }}>
            Actions the agent wants to take that policy says a person must sign off. Approving executes immediately with an idempotency key.
          </p>
        </div>
      </div>
      <div className="tabs">
        <button className={tab === "pending" ? "on" : ""} onClick={() => setTab("pending")}>
          Waiting{tab === "pending" && rows.length ? <span className="n">{rows.length}</span> : null}
        </button>
        <button className={tab !== "pending" ? "on" : ""} onClick={() => setTab("executed,declined,failed")}>Decided</button>
      </div>
      <div className="split">
        <div>
          {rows.length === 0 ? (
            <div className="empty">{tab === "pending" ? "Nothing waiting on you." : "No decisions yet."}</div>
          ) : (
            <div className="queue">
              {rows.map((a) => (
                <QueueItem key={a.id} a={a} on={String(a.id) === id} />
              ))}
            </div>
          )}
        </div>
        <div>
          {sheet.data ? (
            <DecisionSheet
              s={sheet.data}
              busy={decide.isPending}
              onDecide={(ok, note) => decide.mutate({ aid: Number(id), ok, note })}
              error={decide.error ? String(decide.error.message) : null}
            />
          ) : (
            <div className="empty">{rows.length ? "Select an item." : ""}</div>
          )}
        </div>
      </div>
    </>
  );
}

function QueueItem({ a, on }: { a: Approval; on: boolean }) {
  const b = a.break;
  const amt = b?.delta_minor ? fmtDelta(b.delta_minor, b.currency) : "";
  return (
    <Link to={`/approvals/${a.id}`} className={on ? "on" : ""}>
      <div className="q1">
        <span>{b ? RULE_LABEL[b.rule] ?? b.rule : `Break #${a.break_id}`}</span>
        <span className={"amt " + (b?.delta_minor ? "delta neg" : "")}>{amt}</span>
      </div>
      <div className="q2">
        <span>{ACTION_LABEL[a.action] ?? a.action}</span>
        <span>{a.status === "pending" ? ago(a.created_at) : a.status}</span>
      </div>
    </Link>
  );
}
