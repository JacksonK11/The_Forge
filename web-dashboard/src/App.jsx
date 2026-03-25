import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ToastProvider } from "./context/ToastContext.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import OfflineIndicator from "./components/OfflineIndicator.jsx";
import { DesktopSidebar, MobileTabBar } from "./components/Sidebar.jsx";
import { useIsMobile } from "./hooks/useMediaQuery.js";

// ── Lazy page imports ─────────────────────────────────────────────────────────

const NewBuild = lazy(() => import("./pages/NewBuild.jsx"));
const UpgradeAgent = lazy(() => import("./pages/UpgradeAgent.jsx"));
const UpgradeStatus = lazy(() => import("./pages/UpgradeStatus.jsx"));
const MyAgents = lazy(() => import("./pages/MyAgents.jsx"));
const BuildHistory = lazy(() => import("./pages/BuildHistory.jsx"));
const Intelligence = lazy(() => import("./pages/Intelligence.jsx"));
const Templates = lazy(() => import("./pages/Templates.jsx"));
const Settings = lazy(() => import("./pages/Settings.jsx"));
const RunStatus = lazy(() => import("./pages/RunStatus.jsx"));
const Approvals = lazy(() => import("./pages/Approvals.jsx"));

// ── Loading spinner ───────────────────────────────────────────────────────────

function PageSpinner() {
  return (
    <div className="flex-1 flex items-center justify-center min-h-[300px]">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-xs text-gray-600 font-['IBM_Plex_Mono'] tracking-widest">Loading...</span>
      </div>
    </div>
  );
}

// ── Layout wrapper ────────────────────────────────────────────────────────────

function AppLayout() {
  const isMobile = useIsMobile();

  return (
    <div className="flex h-screen bg-gray-950 overflow-hidden">
      {!isMobile && <DesktopSidebar />}

      <main className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <div
          className={`flex-1 min-h-0 overflow-y-auto ios-scroll ${
            isMobile ? "mobile-content-area" : ""
          }`}
        >
          <Suspense fallback={<PageSpinner />}>
            <Routes>
              <Route path="/" element={<NewBuild />} />
              <Route path="/upgrade" element={<UpgradeAgent />} />
              <Route path="/upgrade/:runId" element={<UpgradeStatus />} />
              <Route path="/agents" element={<MyAgents />} />
              <Route path="/history" element={<BuildHistory />} />
              <Route path="/intelligence" element={<Intelligence />} />
              <Route path="/templates" element={<Templates />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/runs/:runId" element={<RunStatus />} />
              <Route path="/approvals" element={<Approvals />} />
            </Routes>
          </Suspense>
        </div>
      </main>

      {isMobile && <MobileTabBar />}
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
