import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { AgGridReact } from "ag-grid-react";
import { gridTheme } from "../lib/gridTheme";
import type { ColDef } from "ag-grid-community";
import { api, Break, RULE_LABEL, fmtDelta, ago } from "../lib/api";

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
      { field: "severity", headerName: "Severity", width: 100, cellClass: (p) => (p.value === "critical" ? "cell-red" : p.value === "warn" ? "cell-amber" : "cell-muted"), filter: true },
      { field: "rule", headerName: "Break", flex: 1, minWidth: 200, valueFormatter: (p) => RULE_LABEL[p.value] ?? p.value, filter: true },
      { field: "title", headerName: "Detail", flex: 2, minWidth: 320, cellClass: "cell-muted" },
      { field: "resource_id", headerName: "Resource", width: 150, cellClass: "cell-mono" },
      { field: "correlation_id", headerName: "Order", width: 150, cellClass: "cell-mono" },
      {
        headerName: "Delta",
        width: 120,
        type: "rightAligned",
        valueGetter: (p) => p.data?.delta_minor ?? null,
        valueFormatter: (p) => fmtDelta(p.data?.delta_minor ?? null, p.data?.currency ?? null),
        cellClass: (p) => (p.value ? "cell-red" : "cell-muted"),
        comparator: (a, b) => Math.abs(a ?? 0) - Math.abs(b ?? 0),
      },
      { field: "status", headerName: "State", width: 150, valueFormatter: (p) => String(p.value).replace(/_/g, " "), filter: true },
      { field: "agent_status", headerName: "Agent", width: 140, hide: true, valueFormatter: (p) => (p.value ? String(p.value).replace(/_/g, " ") : "—"), cellClass: "cell-muted" },
      { field: "opened_at", headerName: "Opened", width: 120, valueFormatter: (p) => ago(p.value), sort: "desc", cellClass: "cell-muted" },
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
      <div className="grid" style={{ height: "calc(100vh - 240px)", minHeight: 420 }}>
        <AgGridReact<Break>
            theme={gridTheme}
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
