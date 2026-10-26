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

const PAGES: Record<string, { title: string; blurb: string }> = {
  "": { title: "Overview", blurb: "Books against PayPal, reconciled continuously" },
  breaks: { title: "Breaks", blurb: "Where the ledger and PayPal disagree" },
  approvals: { title: "Approvals", blurb: "Agent proposals that policy routes to a person" },
  runs: { title: "Agent runs", blurb: "Every investigation, step by step" },
  ledger: { title: "Ledger", blurb: "Append-only events and the tables projected from them" },
};

const Icon = ({ d }: { d: string }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={d} />
  </svg>
);
const ICONS = {
  overview: "M3 12h4l3-8 4 16 3-8h4",
  breaks: "M12 9v4m0 4h.01M10.3 3.9 2.6 17.1A2 2 0 0 0 4.3 20h15.4a2 2 0 0 0 1.7-2.9L13.7 3.9a2 2 0 0 0-3.4 0z",
  approvals: "M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11",
  runs: "M4 4h16v4H4zM4 10h16v4H4zM4 16h16v4H4z",
  ledger: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15z",
};

function Rail() {
  const { data } = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const open = Object.values(data?.breaks_open_by_severity ?? {}).reduce((a, b) => a + b, 0);
  const pending = data?.approvals_pending ?? 0;
  return (
    <nav className="rail">
      <div className="brand">
        <span className="mark" aria-hidden="true">
          <svg width="26" height="26" viewBox="0 0 26 26"><rect x="1" y="1" width="24" height="24" rx="6" fill="currentColor" /><path d="M7 8h12M7 13h12M7 18h7" stroke="var(--paper)" strokeWidth="2" strokeLinecap="round" /></svg>
        </span>
        <span>
          Ledgerline
          <small>Revenue operations for PayPal</small>
        </span>
      </div>
      <div className="nav-group">Monitor</div>
      <NavLink to="/" end><span><Icon d={ICONS.overview} />Overview</span></NavLink>
      <NavLink to="/breaks"><span><Icon d={ICONS.breaks} />Breaks</span><span className={"count" + (open ? " hot" : "")}>{open || ""}</span></NavLink>
      <div className="nav-group">Act</div>
      <NavLink to="/approvals"><span><Icon d={ICONS.approvals} />Approvals</span><span className={"count" + (pending ? " hot" : "")}>{pending || ""}</span></NavLink>
      <NavLink to="/runs"><span><Icon d={ICONS.runs} />Agent runs</span></NavLink>
      <div className="nav-group">Records</div>
      <NavLink to="/ledger"><span><Icon d={ICONS.ledger} />Ledger</span></NavLink>
      <div className="foot">
        <div className="status-card">
          <div><span className={"dot " + (data?.paypal_configured ? "ok" : "warn")} />{data?.paypal_configured ? "PayPal sandbox connected" : "Fixture mode"}</div>
          <div><span className={"dot " + (data?.llm_model && data.llm_model !== "stub" ? "ok" : "")} />{data?.llm_model?.split(":").pop() ?? "…"}</div>
          <div><span className={"dot " + ((data?.jobs?.queued ?? 0) > 0 ? "warn" : "ok")} />Worker · {data?.jobs?.queued ?? 0} queued</div>
        </div>
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
  const page = PAGES[seg] ?? { title: seg, blurb: "" };
  const next = theme === "light" ? "dark" : theme === "dark" ? "auto" : "light";
  const critical = data?.breaks_open_by_severity?.critical ?? 0;
  return (
    <header className="topbar">
      <div className="crumbs">
        <b>{page.title}</b>
        <span className="blurb">{page.blurb}</span>
      </div>
      <div className="meta">
        <span className={"chip " + (critical ? "red" : "green")}>
          <span className="dot" />{critical ? `${critical} critical open` : "All clear"}
        </span>
        <span className="chip">{data?.events ?? 0} events</span>
        <span className="chip">Synced {ago(data?.last_event_at)}</span>
        <span className="chip amber">Sandbox</span>
        <button className="theme" onClick={() => setTheme(next)} title="Switch theme" aria-label="Switch theme">
          {theme === "light" ? "Light" : theme === "dark" ? "Dark" : "Auto"} theme
        </button>
        <span className="avatar" title="Operator">OP</span>
      </div>
    </header>
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
