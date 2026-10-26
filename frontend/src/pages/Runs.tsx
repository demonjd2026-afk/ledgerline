import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";
import { AgentRun, api, ACTION_LABEL, RULE_LABEL, ago } from "../lib/api";
import { Trace } from "../components/Trace";
import { ProposalBody } from "../components/ProposalCard";

export default function Runs() {
  const { id } = useParams();
  const nav = useNavigate();
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.runs });
  const one = useQuery({ queryKey: ["run", id], queryFn: () => api.run(Number(id)), enabled: !!id });

  const cols = useMemo<ColDef<AgentRun>[]>(
    () => [
      { field: "id", headerName: "#", width: 70 },
      { field: "specialist", headerName: "Specialist", width: 150, valueFormatter: (p) => (p.value ? String(p.value).replace(/_/g, " ") : "—") },
      { headerName: "Proposed", flex: 1, valueGetter: (p) => p.data?.proposal?.action, valueFormatter: (p) => ACTION_LABEL[p.value] ?? p.value ?? "—" },
      { field: "status", headerName: "Status", width: 150, valueFormatter: (p) => String(p.value).replace(/_/g, " "), cellClass: (p) => (p.value === "executed" ? "cell-green" : p.value === "failed" ? "cell-red" : p.value === "awaiting_approval" ? "cell-amber" : "") },
      { headerName: "Tool calls", width: 100, type: "rightAligned", valueGetter: (p) => (p.data?.trace ?? []).filter((t: any) => t.tool).length },
      { field: "model", headerName: "Model", width: 200, cellClass: "cell-muted" },
      { field: "started_at", headerName: "Started", width: 150, valueFormatter: (p) => ago(p.value), sort: "desc" },
    ],
    []
  );

  return (
    <>
      <h1>Agent runs</h1>
      <p className="lede">Every run is a checkpointed graph: load the chain, triage, investigate with read-only tools, propose one action, pass the policy gate. Nothing in a run can move money on its own.</p>
      <div className="two">
        <div className="ag-theme-ledger" style={{ height: "calc(100vh - 220px)", minHeight: 400 }}>
          <AgGridReact<AgentRun>
            rowData={runs.data ?? []}
            columnDefs={cols}
            defaultColDef={{ sortable: true, resizable: true }}
            rowSelection={{ mode: "singleRow", checkboxes: false, enableClickSelection: true }}
            onRowClicked={(e) => e.data && nav(`/runs/${e.data.id}`)}
            getRowId={(p) => String(p.data.id)}
            suppressCellFocus
          />
        </div>
        <div>
          {!id && <div className="empty">Select a run to see its trace.</div>}
          {one.data && (
            <>
              <div className="sheet">
                <h2>
                  Run #{one.data.run.id} · {one.data.break ? RULE_LABEL[one.data.break.rule] ?? one.data.break.rule : ""}
                </h2>
                <p className="policy">
                  {one.data.break?.title} · <Link to={`/breaks/${one.data.run.break_id}`}>open break</Link>
                </p>
                {one.data.run.proposal && <ProposalBody proposal={one.data.run.proposal} />}
              </div>
              <div className="sheet">
                <h2>Trace</h2>
                <Trace trace={one.data.run.trace} />
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
