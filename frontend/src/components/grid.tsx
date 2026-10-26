import { useRef, useState, type ReactNode } from "react";
import type { AgGridReact } from "ag-grid-react";
import type { ICellRendererParams } from "ag-grid-community";

/* Custom AG Grid pieces shared by the console's grids: a toolbar (search, export, count),
   and cell renderers that turn raw status strings into the same pills used elsewhere. */

const TONE: Record<string, string> = {
  critical: "red", warn: "amber", info: "grey",
  open: "grey", in_progress: "blue", awaiting_approval: "amber", resolved: "green", dismissed: "grey",
  running: "blue", executed: "green", declined: "red", failed: "red", closed: "grey",
  pending: "amber", approved: "green",
  COMPLETED: "green", PENDING: "amber", DECLINED: "red", REFUNDED: "blue", PARTIALLY_REFUNDED: "blue", FAILED: "red", SUCCESS: "green", PAID: "green", OPEN: "amber", CREATED: "grey", VOIDED: "grey", APPROVED: "green", SENT: "blue", UNCLAIMED: "amber",
};

const LABEL: Record<string, string> = { awaiting_approval: "needs decision", in_progress: "agent working" };

export function PillRenderer(p: ICellRendererParams) {
  const v = p.value;
  if (v == null || v === "") return <span className="cell-muted">—</span>;
  const s = String(v);
  const label = LABEL[s] ?? (/^[A-Z][A-Z_]+$/.test(s) ? s.toLowerCase().replace(/_/g, " ") : s.replace(/_/g, " "));
  return <span className={"pill " + (TONE[s] ?? "grey")}>{label}</span>;
}

export function SeverityRenderer(p: ICellRendererParams) {
  const s = String(p.value ?? "");
  return (
    <span className={"sevcell " + s}>
      <span className="dot" />
      {s}
    </span>
  );
}

export function GridToolbar({ gridRef, count, name, children }: { gridRef: React.RefObject<AgGridReact | null>; count: number; name: string; children?: ReactNode }) {
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const apply = (v: string) => {
    setQ(v);
    gridRef.current?.api?.setGridOption("quickFilterText", v);
  };
  return (
    <div className="grid-toolbar">
      <div className="search">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
        <input ref={inputRef} value={q} onChange={(e) => apply(e.target.value)} placeholder={`Search ${name}…`} aria-label={`Search ${name}`} />
        {q && <button className="clear" onClick={() => apply("")} aria-label="Clear search">×</button>}
      </div>
      <span className="muted fig">{count.toLocaleString()} rows</span>
      {children}
      <button className="btn quiet sm" onClick={() => gridRef.current?.api?.exportDataAsCsv({ fileName: `ledgerline-${name}.csv` })}>
        Export CSV
      </button>
    </div>
  );
}
