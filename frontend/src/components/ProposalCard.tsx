import { useState } from "react";
import { ACTION_LABEL, Approval } from "../lib/api";

export function ProposalBody({ proposal }: { proposal: Record<string, any> }) {
  const p = proposal;
  return (
    <div className="proposal">
      <div className="act">{ACTION_LABEL[p.action] ?? p.action}</div>
      {p.action === "refund" && (
        <p>
          Refund <b>{(p.amount_minor / 100).toFixed(2)} {p.currency}</b> on capture <code>{p.capture_id}</code>
          {p.note_to_payer && <> — note to customer: “{p.note_to_payer}”</>}
        </p>
      )}
      {p.action === "provide_evidence" && (
        <>
          <p>Submit to dispute <code>{p.dispute_id}</code>:</p>
          <ol className="evidence">
            {(p.evidences ?? []).map((e: any, i: number) => (
              <li key={i}>
                <b>{String(e.evidence_type).replace(/_/g, " ").toLowerCase()}</b> — {e.notes}
              </li>
            ))}
          </ol>
          {p.message_to_buyer && <p>Message to buyer: “{p.message_to_buyer}”</p>}
        </>
      )}
      {p.action === "ledger_correction" && (
        <p>
          Set the ledger to match PayPal: {Object.entries(p.correction ?? {}).map(([k, v]) => `${k} = ${v}`).join(", ")}
        </p>
      )}
      {p.action === "escalate" && <p>{p.escalation_summary}</p>}
      <p>
        <b>Why:</b> {p.rationale}
      </p>
      <p style={{ fontSize: 12.5 }}>Confidence {Math.round((p.confidence ?? 0) * 100)}%</p>
    </div>
  );
}

export function PolicyLine({ a }: { a: Approval }) {
  const auto = a.policy_decision === "auto";
  return (
    <div className="policy">
      Policy v{a.policy_version}: <b>{auto ? "ran automatically" : a.policy_decision === "forbidden" ? "forbidden" : "needs a person"}</b> — {a.policy_reasons.join("; ")}
    </div>
  );
}

export function DecisionBox({ a, onDecide, busy }: { a: Approval; onDecide: (approved: boolean, note: string) => void; busy: boolean }) {
  const [note, setNote] = useState("");
  if (a.status !== "pending") {
    return (
      <div className="policy">
        {a.status === "executed" ? "Executed" : a.status === "declined" ? "Declined" : a.status}
        {a.decided_by && <> by {a.decided_by}</>}
        {a.decision_note && <> — “{a.decision_note}”</>}
        {a.execution_result?.dry_run && <> (dry run; PayPal was not called)</>}
      </div>
    );
  }
  return (
    <div>
      <textarea className="note" placeholder="Optional note for the audit trail" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn green" disabled={busy} onClick={() => onDecide(true, note)}>
          Approve and execute
        </button>
        <button className="btn danger" disabled={busy} onClick={() => onDecide(false, note)}>
          Decline
        </button>
      </div>
    </div>
  );
}
