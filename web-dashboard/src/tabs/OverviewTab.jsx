import { useState, useEffect, useCallback } from "react";
import { getRuns, getAgents, getHealth, getForgeStats, getAnalytics } from "../api.js";

function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m === 0) return `${s}s`;
  return `${m}m ${s}s`;
}

function StatusDot({ status }) {
  const isOnline = status === "online" || status === "healthy" || status === true;
  return (
    <span
      className={`inline-block w-3 h-3 rounded-full ${
        isOnline ? "bg-green-400" : "bg-red-400"
      }`}
    />
  );
}

function StatusBadge({ status }) {
  const map = {
    complete: "bg-green-900/50 text-green-400 border-green-800",
    failed: "bg-red-900/50 text-red-400 border-red-800",
    generating: "bg-purple-900/50 text-purple-400 border-purple-800",
    packaging: "bg-blue-900/50 text-blue-400 border-blue-800",
    queued: "bg-gray-800 text-gray-400 border-gray-700",
    confirming: "bg-yellow-900/50 text-yellow-400 border-yellow-800",
  };
  const cls = map[status] || "bg-gray-800 text-gray-400 border-gray-700";
  return (
    <span className={`inline-flex px-2 py-0.5 rounded border text-xs font-medium uppercase tracking-wide ${cls}`}>
      {status}
    </span>
  );
}

function CollapsiblePanel({ title, defaultOpen = true, isMobile = false, children }) {
  const [open, setOpen] = useState(isMobile ? defaultOpen : true);

  return (
    <div className="mb-4">
      {isMobile ? (
        <button
          onClick={() => setOpen(!open)}
          className="w-full flex items-center justify-between min-h-[44px] py-2 mb-2"
        >
          <h3 className="font-['Bebas_Neue'] text-2xl text-gray-300 tracking-wider">
            {title}
          </h3>
          <svg
            className={`w-5 h-5 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      ) : (
        <h3 className="font-['Bebas_Neue'] text-2xl text-gray-300 tracking-wider mb-4">
          {title}
        </h3>
      )}
      {open && children}
    </div>
  );
}

const IN_PROGRESS_STATUSES = new Set([
  "queued", "validating", "parsing", "confirming", "architecting", "generating", "packaging", "pushing",
]);

export default function OverviewTab({ isMobile = false }) {
  const [runs, setRuns] = useState([]);
  const [agents, setAgents] = useState([]);
  const [apiStatus, setApiStatus] = useState("checking");
  const [loading, setLoading] = useState(true);
  const [forgeStats, setForgeStats] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [runsData, agentsData, statsData] = await Promise.allSettled([
        getRuns(),
        getAgents(),
        getForgeStats(),
      ]);
      if (runsData.status === "fulfilled") {
        setRuns(Array.isArray(runsData.value) ? runsData.value : []);
      }
      if (agentsData.status === "fulfilled") {
        setAgents(Array.isArray(agentsData.value) ? agentsData.value : []);
      }
      if (statsData.status === "fulfilled") {
        setForgeStats(statsData.value);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAnalytics = useCallback(async () => {
    setAnalyticsLoading(true);
    try {
      const data = await getAnalytics();
      setAnalytics(data);
    } catch {
      // non-fatal — analytics may not be available yet
    } finally {
      setAnalyticsLoading(false);
    }
  }, []);

  const checkHealth = useCallback(async () => {
    try {
      await getHealth();
      setApiStatus("online");
    } catch {
      setApiStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
    checkHealth();
    loadAnalytics();
  }, [load, checkHealth, loadAnalytics]);

  const totalBuilds = runs.length;
  const completed = runs.filter((r) => r.status === "complete").length;
  const failed = runs.filter((r) => r.status === "failed").length;
  const inProgress = runs.filter((r) => IN_PROGRESS_STATUSES.has(r.status)).length;
  const successRate = totalBuilds > 0 ? Math.round((completed / totalBuilds) * 100) : 0;
  const completedRuns = runs.filter((r) => r.status === "complete");
  const avgFiles =
    completedRuns.length > 0
      ? Math.round(
          completedRuns.reduce((acc, r) => acc + (r.file_count || 0), 0) / completedRuns.length
        )
      : 0;
  const recentRuns = [...runs]
    .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
    .slice(0, 5);

  const hasRecentActivity = runs.some((r) => {
    const d = new Date(r.updated_at || r.created_at || 0);
    return Date.now() - d.getTime() < 60 * 60 * 1000;
  });

  const kpiStats = [
    {
      label: "Total Builds",
      value: totalBuilds,
      sub: "all time",
      color: "text-purple-400",
      border: "border-purple-900",
    },
    {
      label: "Completed",
      value: completed,
      sub: `${successRate}% success`,
      color: "text-green-400",
      border: "border-green-900",
    },
    {
      label: "Failed",
      value: failed,
      sub: `${totalBuilds > 0 ? Math.round((failed / totalBuilds) * 100) : 0}% fail rate`,
      color: "text-red-400",
      border: "border-red-900",
    },
    {
      label: "In Progress",
      value: inProgress,
      sub: "active builds",
      color: "text-yellow-400",
      border: "border-yellow-900",
    },
  ];

  const totalFilesGenerated = forgeStats?.total_files_generated ?? runs.reduce((acc, r) => acc + (r.file_count || 0), 0);
  const monthlyCostAud = forgeStats?.monthly_cost_aud ?? 0;

  const secondaryStats = [
    {
      label: "Avg Files / Build",
      value: avgFiles,
      sub: "completed builds only",
      color: "text-cyan-400",
    },
    {
      label: "Total Files Generated",
      value: totalFilesGenerated.toLocaleString(),
      sub: "all time",
      color: "text-indigo-400",
    },
    {
      label: "Registered Agents",
      value: agents.length,
      sub: "in The Office",
      color: "text-teal-400",
    },
    {
      label: "Success Rate",
      value: `${successRate}%`,
      sub: "completed / total",
      color: successRate >= 80 ? "text-green-400" : successRate >= 50 ? "text-yellow-400" : "text-red-400",
    },
    {
      label: "Monthly Cost",
      value: `A$${monthlyCostAud.toFixed(2)}`,
      sub: "this calendar month",
      color: "text-orange-400",
    },
  ];

  const systemStatuses = [
    {
      label: "API",
      status: apiStatus === "online" ? "online" : "error",
      detail: apiStatus === "online" ? "Responding" : apiStatus === "checking" ? "Checking..." : "Unreachable",
    },
    {
      label: "Worker",
      status: hasRecentActivity ? "online" : "online",
      detail: hasRecentActivity ? "Active" : "Idle",
    },
    {
      label: "Database",
      status: runs.length > 0 || !loading ? "online" : "checking",
      detail: runs.length > 0 ? "Connected" : "Unknown",
    },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className={`font-['Bebas_Neue'] text-gray-100 tracking-widest ${isMobile ? "text-3xl" : "text-4xl"}`}>
          OVERVIEW
        </h2>
        <button
          onClick={() => { load(); checkHealth(); }}
          className="text-xs text-gray-500 hover:text-gray-300 border border-gray-800 hover:border-gray-700 px-3 py-2 rounded-lg transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
        >
          Refresh
        </button>
      </div>

      {/* KPI Stats */}
      <div className={`grid gap-4 mb-6 ${isMobile ? "grid-cols-1" : "grid-cols-2 lg:grid-cols-4"}`}>
        {kpiStats.map((s) => (
          <div
            key={s.label}
            className={`bg-gray-900 border ${s.border} rounded-xl ${isMobile ? "p-4 flex items-center gap-4" : "p-5"}`}
          >
            {isMobile ? (
              <>
                <div className="flex-shrink-0">
                  <p className={`text-3xl font-bold font-mono ${s.color}`}>{s.value}</p>
                </div>
                <div>
                  <p className="text-gray-300 text-sm font-medium">{s.label}</p>
                  <p className="text-gray-600 text-xs">{s.sub}</p>
                </div>
              </>
            ) : (
              <>
                <p className={`text-3xl font-bold font-mono ${s.color}`}>{s.value}</p>
                <p className="text-gray-300 text-sm font-medium mt-1">{s.label}</p>
                <p className="text-gray-600 text-xs mt-0.5">{s.sub}</p>
              </>
            )}
          </div>
        ))}
      </div>

      {/* Secondary metrics */}
      <CollapsiblePanel
        title="METRICS"
        defaultOpen={!isMobile}
        isMobile={isMobile}
      >
        <div className={`grid gap-4 mb-6 ${isMobile ? "grid-cols-1" : "grid-cols-2 lg:grid-cols-3"}`}>
          {secondaryStats.map((s) => (
            <div key={s.label} className={`bg-gray-900 border border-gray-800 rounded-xl ${isMobile ? "p-4 flex items-center gap-4" : "p-5"}`}>
              {isMobile ? (
                <>
                  <div className="flex-shrink-0">
                    <p className={`text-2xl font-bold font-mono ${s.color}`}>{s.value}</p>
                  </div>
                  <div>
                    <p className="text-gray-300 text-sm font-medium">{s.label}</p>
                    <p className="text-gray-600 text-xs">{s.sub}</p>
                  </div>
                </>
              ) : (
                <>
                  <p className={`text-2xl font-bold font-mono ${s.color}`}>{s.value}</p>
                  <p className="text-gray-300 text-sm font-medium mt-1">{s.label}</p>
                  <p className="text-gray-600 text-xs mt-0.5">{s.sub}</p>
                </>
              )}
            </div>
          ))}
        </div>
      </CollapsiblePanel>

      {/* System status */}
      <CollapsiblePanel
        title="SYSTEM STATUS"
        defaultOpen={true}
        isMobile={isMobile}
      >
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 mb-6">
          <div className={`grid gap-4 ${isMobile ? "grid-cols-1" : "grid-cols-3"}`}>
            {systemStatuses.map((s) => (
              <div key={s.label} className={`flex items-center gap-3 ${isMobile ? "min-h-[44px]" : ""}`}>
                <StatusDot status={s.status} />
                <div>
                  <p className={`text-gray-200 font-medium ${isMobile ? "text-base" : "text-sm"}`}>{s.label}</p>
                  <p className={`text-gray-500 ${isMobile ? "text-sm" : "text-xs"}`}>{s.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </CollapsiblePanel>

      {/* Registered agents */}
      {agents.length > 0 && (
        <CollapsiblePanel
          title="REGISTERED AGENTS"
          defaultOpen={!isMobile}
          isMobile={isMobile}
        >
          <div className={`grid gap-3 mb-6 ${isMobile ? "grid-cols-1" : "grid-cols-1 lg:grid-cols-2"}`}>
            {agents.map((agent, i) => (
              <div
                key={agent.id || i}
                className={`bg-gray-900 border border-gray-800 rounded-xl p-4 flex items-start justify-between ${isMobile ? "min-h-[56px]" : ""}`}
              >
                <div className="min-w-0 flex-1">
                  <p className={`text-gray-200 font-medium ${isMobile ? "text-base" : "text-sm"}`}>
                    {agent.agent_name || agent.name}
                  </p>
                  {agent.api_url && (
                    <a
                      href={agent.api_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={`text-cyan-500 hover:text-cyan-400 font-mono mt-0.5 block transition-colors truncate ${isMobile ? "text-sm" : "text-xs"}`}
                    >
                      {agent.api_url}
                    </a>
                  )}
                </div>
                <div className={`flex items-center gap-2 flex-shrink-0 ${isMobile ? "min-h-[44px] pl-3" : ""}`}>
                  <StatusDot status={agent.health_status || "online"} />
                  <span className={`text-gray-500 capitalize ${isMobile ? "text-sm" : "text-xs"}`}>
                    {agent.health_status || "unknown"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </CollapsiblePanel>
      )}

      {/* Analytics */}
      <CollapsiblePanel
        title="ANALYTICS"
        defaultOpen={!isMobile}
        isMobile={isMobile}
      >
        {analytics && analytics.recent_success_rate < 80 && analytics.total_builds >= 5 && (
          <div className="mb-4 px-4 py-3 bg-amber-900/40 border border-amber-700 rounded-xl text-amber-400 text-sm">
            Success rate below 80% — check failed builds
          </div>
        )}
        <div className={`grid gap-4 mb-6 ${isMobile ? "grid-cols-1" : "grid-cols-2 lg:grid-cols-4"}`}>
          <div className={`bg-gray-900 border border-gray-800 rounded-xl ${isMobile ? "p-4 flex items-center gap-4" : "p-5"}`}>
            {isMobile ? (
              <>
                <div className="flex-shrink-0">
                  <p className="text-2xl font-bold font-mono text-blue-400">
                    {analyticsLoading ? "—" : analytics ? (() => {
                      const secs = analytics.avg_duration_seconds || 0;
                      const m = Math.floor(secs / 60);
                      const s = Math.round(secs % 60);
                      return m > 0 ? `${m}m ${s}s` : `${s}s`;
                    })() : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-gray-300 text-sm font-medium">Avg Build Time</p>
                  <p className="text-gray-600 text-xs">last 10 completed</p>
                </div>
              </>
            ) : (
              <>
                <p className="text-2xl font-bold font-mono text-blue-400">
                  {analyticsLoading ? "—" : analytics ? (() => {
                    const secs = analytics.avg_duration_seconds || 0;
                    const m = Math.floor(secs / 60);
                    const s = Math.round(secs % 60);
                    return m > 0 ? `${m}m ${s}s` : `${s}s`;
                  })() : "—"}
                </p>
                <p className="text-gray-300 text-sm font-medium mt-1">Avg Build Time</p>
                <p className="text-gray-600 text-xs mt-0.5">last 10 completed</p>
              </>
            )}
          </div>

          <div className={`bg-gray-900 border border-gray-800 rounded-xl ${isMobile ? "p-4 flex items-center gap-4" : "p-5"}`}>
            {isMobile ? (
              <>
                <div className="flex-shrink-0">
                  <p className="text-2xl font-bold font-mono text-cyan-400">
                    {analyticsLoading ? "—" : analytics ? analytics.avg_files_per_build : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-gray-300 text-sm font-medium">Avg Files/Build</p>
                  <p className="text-gray-600 text-xs">completed builds</p>
                </div>
              </>
            ) : (
              <>
                <p className="text-2xl font-bold font-mono text-cyan-400">
                  {analyticsLoading ? "—" : analytics ? analytics.avg_files_per_build : "—"}
                </p>
                <p className="text-gray-300 text-sm font-medium mt-1">Avg Files/Build</p>
                <p className="text-gray-600 text-xs mt-0.5">completed builds</p>
              </>
            )}
          </div>

          <div className={`bg-gray-900 border border-gray-800 rounded-xl ${isMobile ? "p-4 flex items-center gap-4" : "p-5"}`}>
            {isMobile ? (
              <>
                <div className="flex-shrink-0">
                  <p className="text-2xl font-bold font-mono text-orange-400">
                    {analyticsLoading ? "—" : analytics ? `A$${Number(analytics.avg_cost_aud).toFixed(2)}` : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-gray-300 text-sm font-medium">Avg Cost AUD</p>
                  <p className="text-gray-600 text-xs">per completed build</p>
                </div>
              </>
            ) : (
              <>
                <p className="text-2xl font-bold font-mono text-orange-400">
                  {analyticsLoading ? "—" : analytics ? `A$${Number(analytics.avg_cost_aud).toFixed(2)}` : "—"}
                </p>
                <p className="text-gray-300 text-sm font-medium mt-1">Avg Cost AUD</p>
                <p className="text-gray-600 text-xs mt-0.5">per completed build</p>
              </>
            )}
          </div>

          <div className={`bg-gray-900 border border-gray-800 rounded-xl ${isMobile ? "p-4 flex items-center gap-4" : "p-5"}`}>
            {isMobile ? (
              <>
                <div className="flex-shrink-0">
                  <p className={`text-2xl font-bold font-mono ${
                    analyticsLoading || !analytics
                      ? "text-gray-400"
                      : analytics.recent_success_rate >= 80
                      ? "text-green-400"
                      : analytics.recent_success_rate >= 50
                      ? "text-yellow-400"
                      : "text-red-400"
                  }`}>
                    {analyticsLoading ? "—" : analytics ? `${analytics.recent_success_rate}%` : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-gray-300 text-sm font-medium">Recent Success Rate</p>
                  <p className="text-gray-600 text-xs">last 30 runs</p>
                </div>
              </>
            ) : (
              <>
                <p className={`text-2xl font-bold font-mono ${
                  analyticsLoading || !analytics
                    ? "text-gray-400"
                    : analytics.recent_success_rate >= 80
                    ? "text-green-400"
                    : analytics.recent_success_rate >= 50
                    ? "text-yellow-400"
                    : "text-red-400"
                }`}>
                  {analyticsLoading ? "—" : analytics ? `${analytics.recent_success_rate}%` : "—"}
                </p>
                <p className="text-gray-300 text-sm font-medium mt-1">Recent Success Rate</p>
                <p className="text-gray-600 text-xs mt-0.5">last 30 runs</p>
              </>
            )}
          </div>
        </div>
      </CollapsiblePanel>

      {/* Recent activity */}
      <CollapsiblePanel
        title="RECENT ACTIVITY"
        defaultOpen={true}
        isMobile={isMobile}
      >
        {loading ? (
          <p className="text-gray-600 text-sm">Loading...</p>
        ) : recentRuns.length === 0 ? (
          <p className="text-gray-600 text-sm">No builds yet.</p>
        ) : (
          <div className="relative">
            {/* Timeline line */}
            <div className="absolute left-3 top-3 bottom-3 w-px bg-gray-800" />
            <div className="space-y-4 pl-9">
              {recentRuns.map((run, i) => (
                <div key={run.id || i} className="relative">
                  <div className="absolute -left-9 top-1 w-2.5 h-2.5 rounded-full bg-gray-700 border border-gray-600 mt-0.5" />
                  <div className={`bg-gray-900 border border-gray-800 rounded-xl ${isMobile ? "px-3 py-3" : "px-4 py-3"}`}>
                    <div className={`flex items-start justify-between gap-3 ${isMobile ? "flex-col gap-2" : ""}`}>
                      <div className="min-w-0 flex-1">
                        <p className={`text-gray-200 font-medium ${isMobile ? "text-base" : "text-sm"}`}>
                          {run.title}
                        </p>
                        <p className={`text-gray-500 font-mono mt-0.5 ${isMobile ? "text-sm" : "text-xs"}`}>
                          {formatDate(run.created_at)}
                          {run.duration_seconds
                            ? ` · ${formatDuration(run.duration_seconds)}`
                            : ""}
                        </p>
                      </div>
                      <StatusBadge status={run.status} />
                    </div>
                    {run.file_count > 0 && (
                      <p className={`text-gray-600 mt-1.5 ${isMobile ? "text-sm" : "text-xs"}`}>
                        {run.file_count} files
                        {run.status === "complete" ? " generated" : ""}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </CollapsiblePanel>
    </div>
  );
}