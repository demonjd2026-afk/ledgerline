import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { ModuleRegistry, AllCommunityModule } from "ag-grid-community";
import "./styles.css";
import { api } from "./lib/api";
import Overview from "./pages/Overview";
import Breaks from "./pages/Breaks";
import BreakDetail from "./pages/BreakDetail";
import Approvals from "./pages/Approvals";
import Runs from "./pages/Runs";
import Ledger from "./pages/Ledger";

ModuleRegistry.registerModules([AllCommunityModule]);

const qc = new QueryClient({ defaultOptions: { queries: { refetchInterval: 5000, staleTime: 2000 } } });

function Rail() {
  const { data } = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const open = Object.values(data?.breaks_open_by_severity ?? {}).reduce((a, b) => a + b, 0);
  const pending = data?.approvals_pending ?? 0;
  return (
    <nav className="rail">
      <div className="brand">
        Ledgerline
        <small>Revenue operations for PayPal</small>
      </div>
      <NavLink to="/" end>Overview</NavLink>
      <NavLink to="/breaks">
        <span>Breaks</span>
        <span className={"count" + (open ? " hot" : "")}>{open || ""}</span>
      </NavLink>
      <NavLink to="/approvals">
        <span>Approvals</span>
        <span className={"count" + (pending ? " hot" : "")}>{pending || ""}</span>
      </NavLink>
      <NavLink to="/runs">Agent runs</NavLink>
      <NavLink to="/ledger">Ledger</NavLink>
      <div className="foot">
        {data?.paypal_configured ? "PayPal sandbox connected" : "PayPal not configured — fixture mode"}
        <br />
        Model: {data?.llm_model ?? "…"}
      </div>
    </nav>
  );
}

function App() {
  return (
    <div className="shell">
      <Rail />
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/breaks" element={<Breaks />} />
          <Route path="/breaks/:id" element={<BreakDetail />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:id" element={<Runs />} />
          <Route path="/ledger" element={<Ledger />} />
        </Routes>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
