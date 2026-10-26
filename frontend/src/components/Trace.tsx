const NODE_LABEL: Record<string, string> = {
  load_context: "Loaded break and order chain",
  triage: "Triaged",
  dispute_defender: "Dispute defender",
  refund_advisor: "Refund advisor",
  drift_explainer: "Drift explainer",
  policy_gate: "Policy gate",
  wait_for_human: "Waited for a person",
  execute: "Executed",
};

export function Trace({ trace }: { trace: Array<Record<string, any>> }) {
  if (!trace?.length) return <div className="empty">No trace yet.</div>;
  return (
    <ul className="trace">
      {trace.map((t, i) => {
        const cls = t.node === "execute" ? "exec" : t.node === "wait_for_human" ? "wait" : "";
        const { node, ...rest } = t;
        let line = NODE_LABEL[node] ?? node;
        if (t.tool) line = `Called ${t.tool}`;
        if (node === "triage") line = `Triaged → ${String(t.specialist).replace(/_/g, " ")} (${Math.round((t.confidence ?? 0) * 100)}%)`;
        if (node === "policy_gate") line = `Policy: ${t.decision} — ${(t.reasons ?? []).join("; ")}`;
        if (node === "wait_for_human") line = t.decision ? `${t.decision.approved ? "Approved" : "Declined"} by ${t.decision.by}` : "Waiting for a person";
        if (node === "execute") line = `Executed: ${t.status}${t.dry_run ? " (dry run)" : ""}`;
        const detail = node === "load_context" ? null : t.tool ? { args: t.args, result: t.result_preview } : t.proposal ? t.proposal : node === "triage" ? { summary: t.summary, missing_evidence: t.missing_evidence } : null;
        return (
          <li key={i} className={cls}>
            <div className="node">{line}</div>
            {detail && <pre>{typeof detail === "string" ? detail : JSON.stringify(detail, null, 2)}</pre>}
            {!detail && Object.keys(rest).length > 0 && node !== "policy_gate" && node !== "wait_for_human" && node !== "execute" && (
              <pre>{JSON.stringify(rest, null, 2)}</pre>
            )}
          </li>
        );
      })}
    </ul>
  );
}
