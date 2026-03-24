import { useState, useEffect, useRef, useCallback } from "react";
import { getDetailedHealth, getRecentLogs } from "../api.js";

// ── Status dot ────────────────────────────────────────────────────────────────

function StatusDot({ status }) {
  const colour =
    status === "ok" || status === "running" || status === true
      ? "bg-green-500"
      : status === "idle"
      ? "bg-yellow-400"
      : "bg-red-500";
  return <span className={`inline-block w-2.5 h-2.5 rounded-full flex-shrink-0 ${colour}`} />;
}

// ── Log level colour ──────────────────────────────────────────────────────────

function levelColour(level) {
  switch ((level || "").toUpperCase()) {
    case "DEBUG":
      return "text-gray-500";
    case "INFO":
      return "text-gray-300";
    case "WARNING":
      return "text-yellow-400";
    case "ERROR":
    case "CRITICAL":
      return "text-red-400";
    default:
      return "text-gray-400";
  }
}

function formatTime(isoString) {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    return d.toTimeString().slice(0, 8);
  } catch {
    return isoString;
  }
}

// ── System Health section ─────────────────────────────────────────────────────

function SystemHealth() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const intervalRef = useRef(null);

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getDetailedHealth();
      setHealth(data);
      setError(null);
    } catch (err) {
      setError(err.message || "Unable to connect");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    intervalRef.current = setInterval(fetchHealth, 30000);
    return () => clearInterval(intervalRef.current);
  }, [fetchHealth]);

  const components = health
    ? [
        { key: "api", label: "API", status: health.api?.status },
        { key: "worker", label: "Worker", status: health.worker?.status },
        { key: "database", label: "Database", status: health.database?.connected ? "ok" : "error" },
        { key: "redis", label: "Redis", status: health.redis?.connected ? "ok" : "error" },
      ]
    : [];

  return (
    <section className="mb-8">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-gray-200 font-semibold text-sm uppercase tracking-wider">
          System Health
        </h2>
        <button
          onClick={fetchHealth}
          disabled={loading}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors px-2 py-1 rounded border border-gray-700 hover:border-gray-600 disabled:opacity-50"
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      {error ? (
        <p className="text-red-400 text-sm">{error}</p>
      ) : !health ? (
        <p className="text-gray-600 text-sm">Loading...</p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {components.map(({ key, label, status }) => (
            <div
              key={key}
              className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2.5"
            >
              <StatusDot status={status} />
              <div className="min-w-0">
                <p className="text-gray-400 text-xs">{label}</p>
                <p className="text-gray-200 text-sm font-medium capitalize truncate">{status ?? "—"}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {health && (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs text-gray-500">
          <span>Uptime: {Math.floor((health.api?.uptime_seconds || 0) / 60)}m</span>
          <span>Queue depth: {health.redis?.queue_depth ?? "—"}</span>
          <span>Redis mem: {health.redis?.memory_used_mb ?? "—"} MB</span>
          <span>Log entries: {health.redis?.log_entries ?? "—"}</span>
        </div>
      )}
    </section>
  );
}

// ── Worker Logs section ───────────────────────────────────────────────────────

function WorkerLogs({ isActive }) {
  const [logs, setLogs] = useState([]);
  const [totalRead, setTotalRead] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [levelFilter, setLevelFilter] = useState("");
  const [runIdFilter, setRunIdFilter] = useState("");
  const intervalRef = useRef(null);

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getRecentLogs({ limit: 100, level: levelFilter, run_id: runIdFilter });
      setLogs(data.logs || []);
      setTotalRead(data.total_read || 0);
      setError(null);
    } catch (err) {
      setError(err.message || "Failed to load logs");
    } finally {
      setLoading(false);
    }
  }, [levelFilter, runIdFilter]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    if (!isActive) return;
    intervalRef.current = setInterval(fetchLogs, 5000);
    return () => clearInterval(intervalRef.current);
  }, [isActive, fetchLogs]);

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-gray-200 font-semibold text-sm uppercase tracking-wider">
          Worker Logs
        </h2>
        <span className="text-gray-600 text-xs">
          {totalRead} entries in Redis
        </span>
      </div>

      {/* Filter bar */}
      <div className="flex gap-2 mb-3 flex-wrap">
        <select
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value)}
          className="bg-gray-800 border border-gray-700 text-gray-300 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-purple-600"
        >
          <option value="">ALL LEVELS</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <input
          type="text"
          value={runIdFilter}
          onChange={(e) => setRunIdFilter(e.target.value)}
          placeholder="Filter by run_id..."
          className="bg-gray-800 border border-gray-700 text-gray-300 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-purple-600 flex-1 min-w-[160px] placeholder-gray-600"
        />
        <button
          onClick={fetchLogs}
          disabled={loading}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors px-3 py-1.5 rounded border border-gray-700 hover:border-gray-600 disabled:opacity-50"
        >
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error ? (
        <p className="text-red-400 text-sm">{error}</p>
      ) : logs.length === 0 && !loading ? (
        <p className="text-gray-600 text-sm">No log entries found.</p>
      ) : (
        <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
          <div className="overflow-y-auto max-h-[480px] font-mono text-xs leading-relaxed">
            {logs.map((entry, i) => (
              <div
                key={i}
                className="flex gap-2 px-3 py-1 border-b border-gray-800/50 hover:bg-gray-800/30"
              >
                <span className={`flex-shrink-0 font-semibold w-16 ${levelColour(entry.level)}`}>
                  [{entry.level}]
                </span>
                <span className="flex-shrink-0 text-gray-600 w-16">
                  {formatTime(entry.timestamp)}
                </span>
                <span className={`flex-1 break-all ${levelColour(entry.level)}`}>
                  {entry.message}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

// ── Main SettingsTab ──────────────────────────────────────────────────────────

export default function SettingsTab({ isActive = true }) {
  return (
    <div className="max-w-5xl mx-auto">
      <SystemHealth />
      <WorkerLogs isActive={isActive} />
    </div>
  );
}
