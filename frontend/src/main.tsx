import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { ModuleRegistry, AllCommunityModule } from "ag-grid-community";
import "./styles.css";
import { api, ago } from "./lib/api";
import Overview from "./pages/Overview";
import Breaks from "./pages/Breaks";
import BreakDetail from "./pages/BreakDetail";
import Approvals from "./pages/Approvals";
import Runs from "./pages/Runs";
import Ledger from "./pages/Ledger";

ModuleRegistry.registerModules([AllCommunityModule]);

const qc = new QueryClient({ defaultOptions: { queries: { refetchInterval: 5000, staleTime: 2000 } } });

const TITLES: Record<string, string> = { "": "Overview", breaks: "Breaks", approvals: "Approvals", runs: "Agent runs", ledger: "Ledger" };

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
      <NavLink to="/breaks"><span>Breaks</span><span className={"count" + (open ? " hot" : "")}>{open || ""}</span></NavLink>
      <NavLink to="/approvals"><span>Approvals</span><span className={"count" + (pending ? " hot" : "")}>{pending || ""}</span></NavLink>
      <NavLink to="/runs">Agent runs</NavLink>
      <NavLink to="/ledger">Ledger</NavLink>
      <div className="foot">
        <div><span className={"dot " + (data?.paypal_configured ? "ok" : "warn")} />{data?.paypal_configured ? "PayPal sandbox" : "Fixture mode"}</div>
        <div><span className={"dot " + (data?.llm_model && data.llm_model !== "stub" ? "ok" : "")} />Model <b>{data?.llm_model?.split(":").pop() ?? "…"}</b></div>
        <div><span className={"dot " + ((data?.jobs?.queued ?? 0) > 0 ? "warn" : "ok")} />Queue {data?.jobs?.queued ?? 0} waiting · {data?.jobs?.done ?? 0} done</div>
      </div>
    </nav>
  );
}

function useTheme() {
  const [theme, setTheme] = useState<string>(() => {
    try { return localStorage.getItem("ledgerline.theme") ?? "auto"; } catch { return "auto"; }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", theme);
    try { localStorage.setItem("ledgerline.theme", theme); } catch {}
  }, [theme]);
  return [theme, setTheme] as const;
}

function Topbar() {
  const { pathname } = useLocation();
  const { data } = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const [theme, setTheme] = useTheme();
  const seg = pathname.split("/")[1] ?? "";
  const next = theme === "light" ? "dark" : theme === "dark" ? "auto" : "light";
  return (
    <div className="topbar">
      <div className="crumbs">
        <b>{TITLES[seg] ?? seg}</b>
      </div>
      <div className="meta">
        <span>{data?.events ?? 0} events · {data?.orders ?? 0} orders · {data?.disputes_open ?? 0} open disputes</span>
        <span>Last event {ago(data?.last_event_at)}</span>
        <span>Sandbox</span>
        <button className="theme" onClick={() => setTheme(next)} title="Switch theme">
          {theme === "light" ? "Light" : theme === "dark" ? "Dark" : "Auto"}
        </button>
      </div>
    </div>
  );
}

function App() {
  return (
    <div className="shell">
      <Rail />
      <main className="main">
        <Topbar />
        <div className="page">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/breaks" element={<Breaks />} />
            <Route path="/breaks/:id" element={<BreakDetail />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/approvals/:id" element={<Approvals />} />
            <Route path="/runs" element={<Runs />} />
            <Route path="/runs/:id" element={<Runs />} />
            <Route path="/ledger" element={<Ledger />} />
          </Routes>
        </div>
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
