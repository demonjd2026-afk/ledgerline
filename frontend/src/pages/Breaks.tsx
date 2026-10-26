import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";
import { api, Break, RULE_LABEL, fmtDelta } from "../lib/api";

const STATUS_SETS: Record<string, string | undefined> = {
  Open: "open,in_progress,awaiting_approval",
  Resolved: "resolved",
  All: undefined,
};

export default function Breaks() {
  const [tab, setTab] = useState("Open");
  const nav = useNavigate();
  const { data = [] } = useQuery({ queryKey: ["breaks", tab], queryFn: () => api.breaks(STATUS_SETS[tab]) });

  const cols = useMemo<ColDef<Break>[]>(
    () => [
      { field: "severity", headerName: "Severity", width: 110, cellClass: (p) => (p.value === "critical" ? "cell-red" : p.value === "warn" ? "cell-amber" : "cell-muted"), filter: true },
      { field: "rule", headerName: "Break", flex: 1.2, valueFormatter: (p) => RULE_LABEL[p.value] ?? p.value, filter: true },
      { field: "title", headerName: "Detail", flex: 2, cellClass: "cell-mono" },
      { field: "resource_id", headerName: "Resource", width: 170, cellClass: "cell-mono" },
      { field: "correlation_id", headerName: "Order", width: 160, cellClass: "cell-mono" },
      {
        headerName: "Delta",
        width: 140,
        type: "rightAligned",
        valueGetter: (p) => p.data?.delta_minor ?? null,
        valueFormatter: (p) => fmtDelta(p.data?.delta_minor ?? null, p.data?.currency ?? null),
        cellClass: (p) => (p.value ? "cell-red" : "cell-muted"),
        comparator: (a, b) => Math.abs(a ?? 0) - Math.abs(b ?? 0),
      },
      { field: "status", headerName: "State", width: 160, valueFormatter: (p) => String(p.value).replace(/_/g, " "), filter: true },
      { field: "agent_status", headerName: "Agent", width: 150, valueFormatter: (p) => (p.value ? String(p.value).replace(/_/g, " ") : "—"), cellClass: "cell-muted" },
      { field: "opened_at", headerName: "Opened", width: 170, valueFormatter: (p) => new Date(p.value).toLocaleString(), sort: "desc" },
    ],
    []
  );

  return (
    <>
      <h1>Breaks</h1>
      <p className="lede">A break is a specific disagreement between the ledger and PayPal, or an obligation about to be missed. Click a row to see the evidence and what the agent proposes.</p>
      <div className="tabs">
        {Object.keys(STATUS_SETS).map((t) => (
          <button key={t} className={t === tab ? "on" : ""} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      <div className="ag-theme-ledger" style={{ height: "calc(100vh - 240px)", minHeight: 420 }}>
        <AgGridReact<Break>
          rowData={data}
          columnDefs={cols}
          defaultColDef={{ sortable: true, resizable: true }}
          rowSelection={{ mode: "singleRow", checkboxes: false, enableClickSelection: true }}
          onRowClicked={(e) => e.data && nav(`/breaks/${e.data.id}`)}
          getRowId={(p) => String(p.data.id)}
          animateRows
          suppressCellFocus
        />
      </div>
    </>
  );
}
