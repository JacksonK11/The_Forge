import { useState, useEffect, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import {
  getRun,
  getRunFiles,
  approveSpec,
  getPackageDownloadUrl,
} from "../api/client.js";

const STATUS_CONFIG = {
  queued: { label: "Queued", color: "bg-gray-700 text-gray-300", icon: "⏳" },
  validating: { label: "Validating Blueprint", color: "bg-blue-900 text-blue-300", icon: "🔍" },
  parsing: { label: "Parsing Blueprint", color: "bg-blue-900 text-blue-300", icon: "📖" },
  confirming: { label: "Awaiting Your Approval", color: "bg-yellow-900 text-yellow-300", icon: "✋" },
  architecting: { label: "Mapping Architecture", color: "bg-purple-900 text-purple-300", icon: "🗺️" },
  generating: { label: "Generating Code", color: "bg-indigo-900 text-indigo-300", icon: "⚡" },
  packaging: { label: "Packaging", color: "bg-teal-900 text-teal-300", icon: "📦" },
  complete: { label: "Complete", color: "bg-green-900 text-green-300", icon: "✅" },
  failed: { label: "Failed", color: "bg-red-900 text-red-300", icon: "❌" },
};

const LAYER_NAMES = {
  1: "Database Schema",
  2: "Infrastructure",
  3: "Backend API",
  4: "Worker / Agent Logic",
  5: "Web Dashboard",
  6: "Deployment",
  7: "Documentation",
};

export default function RunStatus() {
  const { runId } = useParams();
  const [run, setRun] = useState(null);
  const [files, setFiles] = useState([]);
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState(null);
  const [expandedLayer, setExpandedLayer] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchRun = useCallback(async () => {
    try {
      const data = await getRun(runId);
      setRun(data);
      if (["generating", "complete", "packaging"].includes(data.status)) {
        const filesData = await getRunFiles(runId, false);
        setFiles(filesData);
      }
    } catch (err) {
      console.error("Failed to fetch run:", err);
    } finally {
      setLoading(false);
    }
  }, [runId]);

  // Poll every 3s while active
  useEffect(() => {
    fetchRun();
    const activeStatuses = ["queued", "validating", "parsing", "architecting", "generating", "packaging"];
    const interval = setInterval(() => {
      if (run && activeStatuses.includes(run.status)) {
        fetchRun();
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [fetchRun, run?.status]);

  async function handleApprove() {
    setApproving(true);
    setApproveError(null);
    try {
      await approveSpec(runId);
      await fetchRun();
    } catch (err) {
      setApproveError(`Approval failed: ${err.message}`);
    } finally {
      setApproving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-400">
        Loading run...
      </div>
    );
  }

  if (!run) {
    return (
      <div className="text-center py-20">
        <div className="text-red-400 mb-4">Run not found</div>
        <Link to="/" className="text-forge-accent hover:underline text-sm">← Back to New Build</Link>
      </div>
    );
  }

  const statusConfig = STATUS_CONFIG[run.status] || STATUS_CONFIG.queued;
  const progressPct = run.file_count > 0
    ? Math.round((run.files_complete / run.file_count) * 100)
    : 0;

  // Group files by layer
  const filesByLayer = files.reduce((acc, f) => {
    const key = f.layer;
    if (!acc[key]) acc[key] = [];
    acc[key].push(f);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <Link to="/history" className="text-gray-500 hover:text-gray-300 text-xs mb-2 block">
            ← All Builds
          </Link>
          <h1 className="text-2xl font-bold text-white">{run.title}</h1>
          <div className="text-gray-400 text-xs mt-1 font-mono">{runId}</div>
        </div>
        <span className={`px-3 py-1.5 rounded-full text-sm font-medium ${statusConfig.color}`}>
          {statusConfig.icon} {statusConfig.label}
        </span>
      </div>

      {/* Progress bar (only during generation) */}
      {run.status === "generating" && run.file_count > 0 && (
        <div>
          <div className="flex justify-between text-xs text-gray-400 mb-1.5">
            <span>
              {run.files_complete}/{run.file_count} files
              {run.files_failed > 0 && (
                <span className="text-red-400 ml-2">({run.files_failed} failed)</span>
              )}
            </span>
            <span>{progressPct}%</span>
          </div>
          <div className="w-full bg-forge-700 rounded-full h-2">
            <div
              className="bg-forge-accent rounded-full h-2 transition-all duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      )}

      {/* Error message */}
      {run.error_message && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg px-4 py-3 text-red-300 text-sm">
          <div className="font-semibold mb-1">Build Error</div>
          {run.error_message}
        </div>
      )}

      {/* Spec Confirmation panel (status = confirming) */}
      {run.status === "confirming" && run.spec_json && (
        <div className="border border-yellow-700 bg-yellow-900/20 rounded-xl p-6 space-y-5">
          <div>
            <h2 className="text-yellow-300 font-bold text-lg mb-1">Spec Ready — Review Before Building</h2>
            <p className="text-gray-400 text-sm">
              The Forge has parsed your blueprint. Review the plan below, then approve to start code generation.
            </p>
          </div>

          {/* Spec summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              ["Files", run.spec_json.file_list?.length || 0],
              ["Services", run.spec_json.fly_services?.length || 0],
              ["Tables", run.spec_json.database_tables?.length || 0],
              ["Routes", run.spec_json.api_routes?.length || 0],
            ].map(([label, value]) => (
              <div key={label} className="bg-forge-800 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold text-white">{value}</div>
                <div className="text-gray-400 text-xs">{label}</div>
              </div>
            ))}
          </div>

          {/* Services */}
          {run.spec_json.fly_services?.length > 0 && (
            <div>
              <div className="text-gray-400 text-xs font-semibold uppercase tracking-wider mb-2">Fly.io Services</div>
              <div className="space-y-2">
                {run.spec_json.fly_services.map((s) => (
                  <div key={s.name} className="flex justify-between bg-forge-800 rounded px-3 py-2 text-sm">
                    <span className="text-white font-mono">{s.name}</span>
                    <span className="text-gray-400">{s.machine} · {s.memory}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tables */}
          {run.spec_json.database_tables?.length > 0 && (
            <div>
              <div className="text-gray-400 text-xs font-semibold uppercase tracking-wider mb-2">Database Tables</div>
              <div className="flex flex-wrap gap-2">
                {run.spec_json.database_tables.map((t) => (
                  <span key={t.name} className="bg-forge-700 text-gray-300 px-3 py-1 rounded font-mono text-xs">
                    {t.name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {approveError && (
            <div className="bg-red-900/30 border border-red-700 rounded px-3 py-2 text-red-300 text-sm">
              {approveError}
            </div>
          )}

          <div className="flex gap-3">
            <button
              onClick={handleApprove}
              disabled={approving}
              className="flex-1 bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white font-semibold py-3 rounded-lg transition-colors text-sm"
            >
              {approving ? "Starting..." : "✓ Approve & Build"}
            </button>
            <Link
              to="/"
              className="px-6 py-3 bg-forge-700 hover:bg-forge-600 text-gray-300 font-semibold rounded-lg transition-colors text-sm text-center"
            >
              Edit Blueprint
            </Link>
          </div>
        </div>
      )}

      {/* Download panel (status = complete) */}
      {run.status === "complete" && run.package_ready && (
        <div className="border border-green-700 bg-green-900/20 rounded-xl p-6">
          <h2 className="text-green-300 font-bold text-lg mb-2">Build Complete</h2>
          <p className="text-gray-400 text-sm mb-4">
            {run.files_complete} files generated
            {run.files_failed > 0 && ` · ${run.files_failed} failed`}.
            Download the ZIP, push to GitHub, run FLY_SECRETS.txt commands, and your agent is live.
          </p>
          <a
            href={getPackageDownloadUrl(runId)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block bg-green-700 hover:bg-green-600 text-white font-semibold py-3 px-8 rounded-lg transition-colors text-sm"
          >
            Download Package (.zip) →
          </a>
        </div>
      )}

      {/* File list (during/after generation) */}
      {files.length > 0 && (
        <div>
          <h2 className="text-gray-400 text-xs font-semibold uppercase tracking-wider mb-3">
            Generated Files
          </h2>
          <div className="space-y-2">
            {Object.entries(filesByLayer)
              .sort(([a], [b]) => Number(a) - Number(b))
              .map(([layer, layerFiles]) => (
                <div key={layer} className="border border-forge-600 rounded-lg overflow-hidden">
                  <button
                    onClick={() => setExpandedLayer(expandedLayer === layer ? null : layer)}
                    className="w-full flex items-center justify-between px-4 py-3 bg-forge-800 hover:bg-forge-700 transition-colors text-left"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-gray-500 text-xs font-mono">L{layer}</span>
                      <span className="text-white text-sm font-medium">
                        {LAYER_NAMES[layer] || `Layer ${layer}`}
                      </span>
                      <span className="text-gray-400 text-xs">
                        {layerFiles.filter((f) => f.status === "complete").length}/{layerFiles.length} files
                      </span>
                    </div>
                    <span className="text-gray-500 text-xs">{expandedLayer === layer ? "▲" : "▼"}</span>
                  </button>
                  {expandedLayer === layer && (
                    <div className="divide-y divide-forge-600">
                      {layerFiles.map((f) => (
                        <div key={f.file_id} className="px-4 py-2.5 flex items-center justify-between bg-forge-900">
                          <span className="font-mono text-xs text-gray-300">{f.file_path}</span>
                          <span
                            className={`text-xs px-2 py-0.5 rounded ${
                              f.status === "complete"
                                ? "bg-green-900/50 text-green-400"
                                : f.status === "failed"
                                ? "bg-red-900/50 text-red-400"
                                : f.status === "generating"
                                ? "bg-blue-900/50 text-blue-400"
                                : "bg-gray-800 text-gray-500"
                            }`}
                          >
                            {f.status}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
