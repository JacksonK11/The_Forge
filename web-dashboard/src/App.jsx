import { useState, useCallback } from "react";
import BuildTab from "./tabs/BuildTab.jsx";
import UpdateTab from "./tabs/UpdateTab.jsx";
import ResultsTab from "./tabs/ResultsTab.jsx";
import FilesTab from "./tabs/FilesTab.jsx";
import MemoryTab from "./tabs/MemoryTab.jsx";
import ChatTab from "./tabs/ChatTab.jsx";
import OverviewTab from "./tabs/OverviewTab.jsx";
import PipelineTab from "./tabs/PipelineTab.jsx";
import ArchitectureTab from "./tabs/ArchitectureTab.jsx";
import MobileLayout from "./components/MobileLayout.jsx";
import { useIsMobile } from "./hooks/useMediaQuery.js";

const TABS = [
  {
    id: "build",
    label: "Build",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
      </svg>
    ),
  },
  {
    id: "update",
    label: "Update",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h5M20 20v-5h-5M4 9a9 9 0 0115 0M20 15a9 9 0 01-15 0" />
      </svg>
    ),
  },
  {
    id: "results",
    label: "Results",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
      </svg>
    ),
  },
  {
    id: "files",
    label: "Files",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
      </svg>
    ),
  },
  {
    id: "memory",
    label: "Memory",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    ),
  },
  {
    id: "chat",
    label: "Chat",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
      </svg>
    ),
  },
  {
    id: "overview",
    label: "Overview",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
      </svg>
    ),
  },
  {
    id: "pipeline",
    label: "Pipeline",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    ),
  },
  {
    id: "architecture",
    label: "Architecture",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    ),
  },
];

// Tabs that use full-height layout (no scroll wrapper padding)
const FULL_HEIGHT_TABS = new Set(["results", "chat"]);

export default function App() {
  const [activeTab, setActiveTab] = useState("build");
  const [sidebarExpanded, setSidebarExpanded] = useState(true);
  const [resultsRunId, setResultsRunId] = useState(null);
  const [buildBlueprint, setBuildBlueprint] = useState("");

  const isMobile = useIsMobile();

  const goToResults = useCallback((runId) => {
    setResultsRunId(runId || null);
    setActiveTab("results");
  }, []);

  const goToBuildWithBlueprint = useCallback((blueprintText) => {
    setBuildBlueprint(blueprintText);
    setActiveTab("build");
  }, []);

  const isFullHeight = FULL_HEIGHT_TABS.has(activeTab);

  function renderTab() {
    switch (activeTab) {
      case "build":
        return (
          <BuildTab
            key={buildBlueprint}
            initialBlueprint={buildBlueprint}
            onGoToResults={goToResults}
            isMobile={isMobile}
          />
        );
      case "update":
        return <UpdateTab />;
      case "results":
        return (
          <ResultsTab
            initialRunId={resultsRunId}
            onRebuild={goToBuildWithBlueprint}
          />
        );
      case "files":
        return <FilesTab />;
      case "memory":
        return <MemoryTab />;
      case "chat":
        return <ChatTab isMobile={isMobile} />;
      case "overview":
        return <OverviewTab />;
      case "pipeline":
        return <PipelineTab />;
      case "architecture":
        return <ArchitectureTab />;
      default:
        return null;
    }
  }

  if (isMobile) {
    return (
      <MobileLayout
        tabs={TABS}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        tabContent={renderTab}
      />
    );
  }

  return (
    <div className="flex h-screen bg-gray-950 overflow-hidden">
      {/* ── Sidebar ── */}
      <aside
        className={`flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col transition-all duration-200 ${
          sidebarExpanded ? "w-[220px]" : "w-[56px]"
        }`}
      >
        {/* Logo */}
        <div className="flex items-center h-14 border-b border-gray-800 px-3 flex-shrink-0">
          <button
            onClick={() => setSidebarExpanded(!sidebarExpanded)}
            className="w-9 h-9 rounded-lg bg-purple-800/30 border border-purple-700/50 flex items-center justify-center flex-shrink-0 hover:bg-purple-700/40 transition-colors"
            title={sidebarExpanded ? "Collapse sidebar" : "Expand sidebar"}
          >
            <span className="text-purple-300 text-base font-bold">⚒</span>
          </button>
          {sidebarExpanded && (
            <div className="ml-2.5 overflow-hidden">
              <p className="text-gray-100 font-['Bebas_Neue'] text-lg tracking-widest leading-none whitespace-nowrap">
                THE FORGE
              </p>
              <p className="text-gray-600 text-xs whitespace-nowrap">AI Build Engine</p>
            </div>
          )}
        </div>

        {/* Nav items */}
        <nav className="flex-1 overflow-y-auto py-3 space-y-0.5 px-1.5">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-lg tab-transition text-left ${
                  isActive
                    ? "bg-purple-700/30 text-purple-300 border border-purple-700/40"
                    : "text-gray-500 hover:text-gray-300 hover:bg-gray-800 border border-transparent"
                }`}
                title={!sidebarExpanded ? tab.label : undefined}
              >
                <span className={`flex-shrink-0 ${isActive ? "text-purple-400" : ""}`}>
                  {tab.icon}
                </span>
                {sidebarExpanded && (
                  <span className="text-sm font-medium whitespace-nowrap overflow-hidden">
                    {tab.label}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Bottom: version */}
        {sidebarExpanded && (
          <div className="px-4 py-3 border-t border-gray-800 flex-shrink-0">
            <p className="text-gray-700 text-xs font-mono">v1.0.0</p>
            <p className="text-gray-700 text-xs">Agent 1 of 5</p>
          </div>
        )}
      </aside>

      {/* ── Main content ── */}
      <main className={`flex-1 min-w-0 flex flex-col overflow-hidden ${isFullHeight ? "" : ""}`}>
        {/* Top bar */}
        <header className="h-14 border-b border-gray-800 bg-gray-900/50 flex items-center px-6 flex-shrink-0">
          <div className="flex items-center gap-3">
            <h1 className="text-gray-300 font-['Bebas_Neue'] text-xl tracking-widest">
              {TABS.find((t) => t.id === activeTab)?.label?.toUpperCase()}
            </h1>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <a
              href="https://the-forge-api.fly.dev/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
            >
              API Docs
            </a>
            <span className="text-gray-800">·</span>
            <a
              href="https://fly.io/apps/the-forge-api"
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
            >
              Fly.io
            </a>
          </div>
        </header>

        {/* Tab content */}
        <div className={`flex-1 min-h-0 ${isFullHeight ? "overflow-hidden" : "overflow-y-auto"}`}>
          <div className={isFullHeight ? "h-full p-6" : "p-6"}>
            {renderTab()}
          </div>
        </div>
      </main>
    </div>
  );
}