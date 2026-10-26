import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";
import { api } from "../lib/api";

const TABS = ["events", "orders", "captures", "refunds", "disputes", "payouts", "invoices"] as const;
type Tab = (typeof TABS)[number];

const HIDE = new Set(["payload", "headers", "body", "last_event_id", "amount_minor", "fee_minor", "net_minor", "paid_amount_minor", "api_amount_minor"]);
const WIDTHS: Record<string, number> = { id: 180, status: 140, currency: 80, event_type: 200, source: 90, resource_type: 110 };

function colsFor(rows: Record<string, any>[]): ColDef[] {
  if (!rows.length) return [];
  const keys = Object.keys(rows[0]).filter((k) => !HIDE.has(k));
  return keys.map((k) => ({
    field: k,
    headerName: k.replace(/_/g, " "),
    width: WIDTHS[k],
    flex: WIDTHS[k] ? undefined : 1,
    minWidth: 90,
    filter: true,
    cellClass: (p) =>
      k === "api_status" && p.data?.api_status && p.data.api_status !== p.data.status
        ? "cell-red"
        : /_at$|time/.test(k)
          ? "cell-muted"
          : /^(amount|fee|net|paid_amount|api_amount)$/.test(k)
            ? "cell-mono"
            : "",
    type: /^(amount|fee|net|paid_amount|api_amount)$/.test(k) ? "rightAligned" : undefined,
    valueFormatter: (p) => (/_at$|time$/.test(k) && p.value ? new Date(p.value).toLocaleString() : p.value ?? ""),
  }));
}

export default function Ledger() {
  const [tab, setTab] = useState<Tab>("events");
  const { data = [] } = useQuery({ queryKey: ["ledger", tab], queryFn: () => (tab === "events" ? api.events("?limit=1000") : api.ledger(tab)) });
  const cols = useMemo(() => colsFor(data), [data]);

  return (
    <>
      <h1>Ledger</h1>
      <p className="lede">
        The append-only event log and the tables projected from it. In the captures table, a red <i>api status</i> is PayPal disagreeing with the webhook-derived state.
      </p>
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t} className={t === tab ? "on" : ""} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      {data.length === 0 ? (
        <div className="empty">No {tab} yet.</div>
      ) : (
        <div className="ag-theme-ledger" style={{ height: "calc(100vh - 230px)", minHeight: 420 }}>
          <AgGridReact rowData={data} columnDefs={cols} defaultColDef={{ sortable: true, resizable: true }} getRowId={(p) => String(p.data.id)} suppressCellFocus pagination paginationPageSize={100} />
        </div>
      )}
    </>
  );
}
