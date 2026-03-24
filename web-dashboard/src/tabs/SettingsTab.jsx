import { useState, useEffect, useRef, useCallback } from "react";
import { getDetailedHealth, getRecentLogs, getSettings, saveSettings } from "../api.js";

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

// ── Configuration section ─────────────────────────────────────────────────────

const SETTING_GROUPS = [
  {
    label: "Model Routing",
    fields: [
      { key: "claude_model", label: "Claude Model", type: "text" },
      { key: "claude_fast_model", label: "Fast Model", type: "text" },
    ],
  },
  {
    label: "Token Limits",
    fields: [
      { key: "parse_max_tokens", label: "Parse Max Tokens", type: "number" },
      { key: "architecture_max_tokens", label: "Architecture Max Tokens", type: "number" },
      { key: "codegen_max_tokens", label: "Codegen Max Tokens", type: "number" },
    ],
  },
  {
    label: "Pipeline Tuning",
    fields: [
      { key: "large_blueprint_threshold", label: "Large Blueprint Threshold chars", type: "number" },
      { key: "max_retries", label: "Max Retries", type: "number" },
      { key: "orphan_timeout_minutes", label: "Orphan Timeout minutes", type: "number" },
      { key: "quality_score_minimum", label: "Quality Score Minimum", type: "number" },
    ],
  },
  {
    label: "Notifications",
    fields: [
      { key: "cost_alert_threshold_aud", label: "Cost Alert Threshold AUD", type: "number" },
      { key: "telegram_notify_on_complete", label: "Notify on Complete", type: "checkbox" },
      { key: "telegram_notify_on_failure", label: "Notify on Failure", type: "checkbox" },
      { key: "telegram_notify_on_stall", label: "Notify on Stall", type: "checkbox" },
    ],
  },
];

function ConfigurationSection() {
  const [settings, setSettings] = useState({});
  const [dirty, setDirty] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState(null);
  const [saveError, setSaveError] = useState(null);

  const fetchSettings = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getSettings();
      setSettings(data);
      setDirty({});
    } catch (err) {
      setSaveError(err.message || "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  function handleChange(key, value) {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setDirty((prev) => ({ ...prev, [key]: value }));
    setSaveMsg(null);
    setSaveError(null);
  }

  async function handleSave() {
    if (Object.keys(dirty).length === 0) {
      setSaveMsg("No changes to save.");
      return;
    }
    setSaving(true);
    setSaveMsg(null);
    setSaveError(null);
    try {
      await saveSettings(dirty);
      setDirty({});
      setSaveMsg("Settings saved successfully.");
    } catch (err) {
      setSaveError(err.message || "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <section className="mt-8">
        <h2 className="text-gray-200 font-semibold text-sm uppercase tracking-wider mb-3">
          Configuration
        </h2>
        <p className="text-gray-600 text-sm">Loading settings...</p>
      </section>
    );
  }

  return (
    <section className="mt-8">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-gray-200 font-semibold text-sm uppercase tracking-wider">
          Configuration
        </h2>
        <button
          onClick={fetchSettings}
          disabled={loading}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors px-2 py-1 rounded border border-gray-700 hover:border-gray-600 disabled:opacity-50"
        >
          Reset
        </button>
      </div>

      <div className="space-y-6">
        {SETTING_GROUPS.map((group) => (
          <div key={group.label} className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h3 className="text-gray-400 text-xs uppercase tracking-wider font-semibold mb-4">
              {group.label}
            </h3>
            <div className="space-y-3">
              {group.fields.map((field) => (
                <div key={field.key} className="flex items-center justify-between gap-4">
                  <label className="text-gray-300 text-sm flex-shrink-0 w-48">
                    {field.label}
                  </label>
                  {field.type === "checkbox" ? (
                    <input
                      type="checkbox"
                      checked={settings[field.key] === "true"}
                      onChange={(e) => handleChange(field.key, e.target.checked ? "true" : "false")}
                      className="w-4 h-4 accent-purple-500 cursor-pointer"
                    />
                  ) : (
                    <input
                      type={field.type}
                      value={settings[field.key] ?? ""}
                      onChange={(e) => handleChange(field.key, e.target.value)}
                      className="flex-1 bg-gray-800 border border-gray-700 text-gray-100 text-sm rounded px-3 py-1.5 focus:outline-none focus:border-purple-600 min-w-0"
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 flex items-center gap-4">
        <button
          onClick={handleSave}
          disabled={saving || Object.keys(dirty).length === 0}
          className="px-4 py-2 bg-purple-700 hover:bg-purple-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors"
        >
          {saving ? "Saving..." : "Save Settings"}
        </button>
        {saveMsg && <p className="text-green-400 text-sm">{saveMsg}</p>}
        {saveError && <p className="text-red-400 text-sm">{saveError}</p>}
      </div>
    </section>
  );
}

// ── Main SettingsTab ──────────────────────────────────────────────────────────

export default function SettingsTab({ isActive = true }) {
  return (
    <div className="max-w-5xl mx-auto">
      <SystemHealth />
      <WorkerLogs isActive={isActive} />
      <ConfigurationSection />
    </div>
  );
}
