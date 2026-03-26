import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, useLocation, useNavigate } from "react-router-dom";
import { ToastProvider } from "./context/ToastContext.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import OfflineIndicator from "./components/OfflineIndicator.jsx";
import { useNotifications } from "./hooks/useNotifications.js";

// ── Lazy page imports ─────────────────────────────────────────────────────────

const Command     = lazy(() => import("./pages/Command.jsx"));
const Build       = lazy(() => import("./pages/Build.jsx"));
const Upgrade     = lazy(() => import("./pages/Upgrade.jsx"));
const Queue       = lazy(() => import("./pages/Queue.jsx"));
const Active      = lazy(() => import("./pages/Active.jsx"));
const History     = lazy(() => import("./pages/History.jsx"));
const Intelligence = lazy(() => import("./pages/Intelligence.jsx"));
const Settings    = lazy(() => import("./pages/Settings.jsx"));
const RunStatus   = lazy(() => import("./pages/RunStatus.jsx"));

// ── Loading spinner ───────────────────────────────────────────────────────────

function PageSpinner() {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "300px" }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ width: 32, height: 32, border: "2px solid var(--p)", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.7s linear infinite", margin: "0 auto 12px" }} />
        <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", letterSpacing: "0.1em", textTransform: "uppercase" }}>Loading...</span>
      </div>
    </div>
  );
}

// ── Clock ─────────────────────────────────────────────────────────────────────

function Clock() {
  const [time, setTime] = useState(() => formatTime());
  useEffect(() => {
    const id = setInterval(() => setTime(formatTime()), 1000);
    return () => clearInterval(id);
  }, []);
  return <span className="forge-time">{time}</span>;
}

function formatTime() {
  return new Date().toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

// ── Nav ───────────────────────────────────────────────────────────────────────

const NAV_TABS = [
  { path: "/",            label: "Command",     badge: null },
  { path: "/build",       label: "Build",       badge: null },
  { path: "/upgrade",     label: "Upgrade",     badge: null },
  { path: "/queue",       label: "Queue",       badge: "amber" },
  { path: "/active",      label: "Active",      badge: "purple" },
  { path: "/history",     label: "History",     badge: null },
  { path: "/intelligence",label: "Intelligence",badge: null },
];

const MOBILE_TABS = [
  { path: "/",        label: "CMD",    icon: "⚡" },
  { path: "/build",   label: "Build",  icon: "🔨" },
  { path: "/queue",   label: "Queue",  icon: "⏳", badge: "amber" },
  { path: "/active",  label: "Active", icon: "🔥", badge: "purple" },
  { path: "/history", label: "Hist",   icon: "📋" },
];

function ForgeNav() {
  const location = useLocation();
  const { pendingApprovals, activeBuilds } = useNotifications();

  function badgeCount(tab) {
    if (tab.path === "/queue") return pendingApprovals || null;
    if (tab.path === "/active") return activeBuilds || null;
    return null;
  }

  return (
    <nav className="forge-nav">
      <NavLink to="/" className="forge-logo" style={{ textDecoration: "none" }}>
        <div className="logo-dot" />
        <span>THE FORGE</span>
        <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--p2)", background: "var(--p-d)", border: "1px solid var(--p-g)", borderRadius: 4, padding: "2px 7px", marginLeft: 8, letterSpacing: "0.06em" }}>
          V5
        </span>
      </NavLink>

      {NAV_TABS.map((tab) => {
        const isActive = tab.path === "/"
          ? location.pathname === "/"
          : location.pathname.startsWith(tab.path);
        const count = badgeCount(tab);
        return (
          <NavLink
            key={tab.path}
            to={tab.path}
            className={`forge-tab${isActive ? " active" : ""}`}
          >
            {tab.label.toUpperCase()}
            {count > 0 && (
              <span className={`forge-badge ${tab.badge || ""}`}>{count}</span>
            )}
          </NavLink>
        );
      })}

      <NavLink
        to="/settings"
        className={`forge-tab${location.pathname === "/settings" ? " active" : ""}`}
        style={{ marginLeft: "auto" }}
      >
        SETTINGS
      </NavLink>

      <div className="forge-nav-right" style={{ marginLeft: 0 }}>
        <Clock />
        <div className="forge-avatar">F</div>
      </div>
    </nav>
  );
}

function MobileTabs() {
  const location = useLocation();
  const { pendingApprovals, activeBuilds } = useNotifications();

  return (
    <div className="forge-mobile-tabs mobile-bottom-nav">
      {MOBILE_TABS.map((tab) => {
        const isActive = tab.path === "/"
          ? location.pathname === "/"
          : location.pathname.startsWith(tab.path);
        const count = tab.path === "/queue" ? pendingApprovals : tab.path === "/active" ? activeBuilds : 0;
        return (
          <NavLink
            key={tab.path}
            to={tab.path}
            className={`mobile-bottom-nav-item${isActive ? " active" : ""}`}
          >
            <div style={{ position: "relative" }}>
              <span className="nav-icon" style={{ fontSize: 18 }}>{tab.icon}</span>
              {count > 0 && (
                <span style={{ position: "absolute", top: -4, right: -6, background: "var(--amber)", color: "var(--bg)", borderRadius: 8, fontSize: 8, fontFamily: "var(--fm)", fontWeight: 700, padding: "1px 4px", lineHeight: 1.4 }}>
                  {count}
                </span>
              )}
            </div>
            <span className="nav-label">{tab.label}</span>
          </NavLink>
        );
      })}
    </div>
  );
}

// ── App layout ────────────────────────────────────────────────────────────────

function AppLayout() {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      <ForgeNav />
      <main style={{ flex: 1, overflowY: "auto", WebkitOverflowScrolling: "touch" }}>
        <div className="forge-shell">
          <Suspense fallback={<PageSpinner />}>
            <Routes>
              <Route path="/"             element={<Command />} />
              <Route path="/build"        element={<Build />} />
              <Route path="/upgrade"      element={<Upgrade />} />
              <Route path="/upgrade/:runId" element={<RunStatus upgrade />} />
              <Route path="/queue"        element={<Queue />} />
              <Route path="/active"       element={<Active />} />
              <Route path="/history"      element={<History />} />
              <Route path="/intelligence" element={<Intelligence />} />
              <Route path="/settings"     element={<Settings />} />
              <Route path="/runs/:runId"  element={<RunStatus />} />
            </Routes>
          </Suspense>
        </div>
      </main>
      <MobileTabs />
    </div>
  );
}

// ── Root app ──────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <BrowserRouter>
          <OfflineIndicator />
          <AppLayout />
        </BrowserRouter>
      </ToastProvider>
    </ErrorBoundary>
  );
}
