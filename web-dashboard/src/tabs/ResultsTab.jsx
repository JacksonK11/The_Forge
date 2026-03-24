
import { useState, useEffect, useCallback } from "react";
import { getRun, getRuns, getRunFiles, getRunPackageBlob, registerAgent, triggerDownload, resumeRun, forceFailRun, getDeployStatus, setRunSecrets } from "../api.js";
import { BASE_URL } from "../api.js";

const LAYER_LABELS = {
  1: "Layer 1: Database Schema",
  2: "Layer 2: Infrastructure",
  3: "Layer 3: Backend API",
  4: "Layer 4: Worker / Agent Logic",
  5: "Layer 5: Web Dashboard",
  6: "Layer 6: Deployment",
  7: "Layer 7: Documentation",
};

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

function FileStatusIcon({ status }) {
  if (status === "complete") return <span className="text-green-400">✓</span>;
  if (status === "retried") return <span className="text-yellow-400">↺</span>;
  if (status === "failed") return <span className="text-red-400">✗</span>;
  return <span className="text-gray-500">·</span>;
}

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

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return "—";
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)}MB`;
}

function groupFilesByLayer(files) {
  const groups = {};
  for (const f of files) {
    const layer = f.layer || 0;
    if (!groups[layer]) groups[layer] = [];
    groups[layer].push(f);
  }
  return groups;
}

function DeploymentPanel({ run, isMobile = false }) {
  const [deployStatus, setDeployStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [secretInputs, setSecretInputs] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg] = useState("");

  const runId = run?.id || run?.run_id;

  useEffect(() => {
    if (!runId) return;
    setLoading(true);
    getDeployStatus(runId)
      .then((data) => setDeployStatus(data))
      .catch(() => setDeployStatus(null))
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) return null;
  if (!deployStatus) return null;

  const { registered_apps = [], manual_secrets_needed = [], has_deployment } = deployStatus;

  // Nothing to show if no deployment and no secrets needed
  if (!has_deployment && manual_secrets_needed.length === 0) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-5">
        <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Deployment</p>
        <p className="text-gray-600 text-xs">Auto-deploy not configured</p>
      </div>
    );
  }

  async function handleSetSecrets() {
    setSubmitting(true);
    setSubmitMsg("");
    try {
      const result = await setRunSecrets(runId, secretInputs);
      const setCount = result.set?.length || 0;
      const failCount = result.failed?.length || 0;
      setSubmitMsg(
        failCount === 0
          ? `${setCount} secret(s) set successfully.`
          : `${setCount} set, ${failCount} failed.`
      );
    } catch (err) {
      setSubmitMsg(`Failed: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-5">
      <p className="text-gray-500 text-xs uppercase tracking-wider mb-3">Deployment</p>

      {/* Deployed apps */}
      {registered_apps.map((app, i) => (
        <div key={i} className="mb-3">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="inline-block w-2 h-2 rounded-full bg-green-400 flex-shrink-0" />
            <span className="text-green-400 text-xs font-medium">Deployed</span>
            <span className="text-gray-500 text-xs font-mono truncate">{app.agent_name}</span>
          </div>
          <div className="flex flex-col gap-1.5 pl-4">
            {app.api_url && (
              <div className={`flex items-center gap-2 ${isMobile ? "min-h-[36px]" : ""}`}>
                <span className="text-gray-500 text-xs w-16 flex-shrink-0">API</span>
                <a
                  href={app.api_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-cyan-400 hover:text-cyan-300 text-xs font-mono truncate transition-colors"
                >
                  {app.api_url}
                </a>
              </div>
            )}
            {app.dashboard_url && (
              <div className={`flex items-center gap-2 ${isMobile ? "min-h-[36px]" : ""}`}>
                <span className="text-gray-500 text-xs w-16 flex-shrink-0">Dashboard</span>
                <a
                  href={app.dashboard_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-purple-400 hover:text-purple-300 text-xs font-mono truncate transition-colors"
                >
                  {app.dashboard_url}
                </a>
              </div>
            )}
          </div>
        </div>
      ))}

      {/* Manual secrets form */}
      {manual_secrets_needed.length > 0 && (
        <div className="mt-3 border-t border-gray-800 pt-3">
          <p className="text-amber-400 text-xs font-medium mb-2">
            {manual_secrets_needed.length} secret(s) require manual input
          </p>
          <div className="flex flex-col gap-2 mb-3">
            {manual_secrets_needed.map((key) => (
              <div key={key} className="flex flex-col gap-1">
                <label className="text-gray-400 text-xs font-mono">{key}</label>
                <input
                  type="password"
                  placeholder={`Enter ${key}`}
                  value={secretInputs[key] || ""}
                  onChange={(e) =>
                    setSecretInputs((prev) => ({ ...prev, [key]: e.target.value }))
                  }
                  className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-gray-200 text-xs font-mono placeholder-gray-600 focus:outline-none focus:border-amber-600 transition-colors"
                />
              </div>
            ))}
          </div>
          <button
            onClick={handleSetSecrets}
            disabled={submitting || Object.keys(secretInputs).length === 0}
            className={`w-full py-2 text-xs font-medium rounded-lg transition-colors disabled:opacity-50 ${
              isMobile ? "min-h-[44px]" : ""
            } bg-amber-700 hover:bg-amber-600 text-white`}
          >
            {submitting ? "Setting secrets..." : "Set & Deploy"}
          </button>
          {submitMsg && (
            <p className="text-xs mt-2 text-teal-300">{submitMsg}</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function ResultsTab({ initialRunId, onRebuild, isMobile = false }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedRun, setSelectedRun] = useState(null);
  const [runFiles, setRunFiles] = useState([]);
  const [runLogs, setRunLogs] = useState([]);
  const [runCost, setRunCost] = useState(null);
  const [runVersions, setRunVersions] = useState([]);
  const [activeDetailTab, setActiveDetailTab] = useState("files");
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [registering, setRegistering] = useState(false);
  const [registerMsg, setRegisterMsg] = useState("");
  const [showRunList, setShowRunList] = useState(true);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    try {
      const list = await getRuns();
      setRuns(list);
      if (initialRunId) {
        const found = list.find((r) => String(r.run_id) === String(initialRunId));
        if (found) loadRunDetail(found.run_id);
      }
    } catch {
      // non-fatal
    } finally {
      setLoading(false);
    }
  }, [initialRunId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadRunDetail(runId) {
    setLoadingDetail(true);
    setRunFiles([]);
    setRunLogs([]);
    setRunCost(null);
    setRunVersions([]);
    setSelectedFile(null);
    setActiveDetailTab("files");
    try {
      const API_KEY = import.meta.env.VITE_API_SECRET_KEY || "";
      const headers = { Authorization: `Bearer ${API_KEY}` };
      const [detail, files, logsRes, costRes, versionsRes] = await Promise.allSettled([
        getRun(runId),
        getRunFiles(runId, true),
        fetch(`${BASE_URL}/forge/runs/${runId}/logs`, { headers }).then((r) => r.json()),
        fetch(`${BASE_URL}/forge/runs/${runId}/cost`, { headers }).then((r) => r.json()),
        fetch(`${BASE_URL}/forge/runs/${runId}/versions`, { headers }).then((r) => r.json()),
      ]);
      if (detail.status === "fulfilled") setSelectedRun(detail.value);
      if (files.status === "fulfilled") setRunFiles(Array.isArray(files.value) ? files.value : []);
      if (logsRes.status === "fulfilled") setRunLogs(Array.isArray(logsRes.value) ? logsRes.value : []);
      if (costRes.status === "fulfilled") setRunCost(costRes.value);
      if (versionsRes.status === "fulfilled") setRunVersions(Array.isArray(versionsRes.value) ? versionsRes.value : []);
    } catch {
      // non-fatal — selectedRun already set to summary
    } finally {
      setLoadingDetail(false);
    }
  }

  useEffect(() => {
    loadRuns();
  }, [loadRuns]);

  async function handleDownloadZip() {
    if (!selectedRun) return;
    const id = selectedRun.id || selectedRun.run_id;
    try {
      const blob = await getRunPackageBlob(id);
      const slug = selectedRun.repo_name || selectedRun.agent_slug || `forge-build-${id}`;
      triggerDownload(blob, `${slug}.zip`);
    } catch (err) {
      alert(`Download failed: ${err.message}`);
    }
  }

  async function handleRegisterAgent() {
    if (!selectedRun) return;
    setRegistering(true);
    setRegisterMsg("");
    const slug = selectedRun.agent_slug || selectedRun.repo_name || "";
    try {
      await registerAgent({
        run_id: selectedRun.id || selectedRun.run_id,
        agent_name: selectedRun.title,
        agent_slug: slug,
        api_url: `https://${slug}-api.fly.dev`,
        dashboard_url: `https://${slug}-dashboard.fly.dev`,
      });
      setRegisterMsg("Agent registered in The Office.");
    } catch (err) {
      setRegisterMsg(`Failed: ${err.message}`);
    } finally {
      setRegistering(false);
    }
  }

  function handleRebuild() {
    if (selectedRun && onRebuild) {
      onRebuild(selectedRun.blueprint_text || "");
    }
  }

  async function handleResume() {
    if (!selectedRun) return;
    const id = selectedRun.id || selectedRun.run_id;
    try {
      await resumeRun(id);
      await loadRunDetail(id);
    } catch (err) {
      alert(`Resume failed: ${err.message}`);
    }
  }

  async function handleForceFail() {
    if (!selectedRun) return;
    const id = selectedRun.id || selectedRun.run_id;
    try {
      await forceFailRun(id);
      await loadRunDetail(id);
    } catch (err) {
      alert(`Force fail failed: ${err.message}`);
    }
  }

  function handleSelectRun(run) {
    setSelectedRun(run);
    setRunFiles([]);
    setSelectedFile(null);
    loadRunDetail(run.run_id);
    if (isMobile) {
      setShowRunList(false);
    }
  }

  function handleBackToList() {
    setShowRunList(true);
    setSelectedRun(null);
    setRunFiles([]);
    setSelectedFile(null);
  }

  const ACTIVE_STATUSES = ["generating", "architecting", "queued", "validating", "parsing", "packaging"];

  const files = runFiles;
  const layerGroups = groupFilesByLayer(files);
  const completedFiles = files.filter((f) => f.status === "complete").length;
  const failedFiles = files.filter((f) => f.status === "failed").length;
  const costEstimate = ((files.length || 0) * 0.002).toFixed(3);
  const slug = selectedRun?.agent_slug || selectedRun?.repo_name || "";

  // ── Mobile Layout ──────────────────────────────────────────────────────
  if (isMobile) {
    // Show run list or detail based on selection
    if (showRunList || !selectedRun) {
      return (
        <div className="flex flex-col h-full min-h-0">
          <div className="p-4 border-b border-gray-800 flex items-center justify-between flex-shrink-0">
            <h2 className="font-['Bebas_Neue'] text-2xl text-gray-100 tracking-widest">
              RESULTS
            </h2>
            <button
              onClick={loadRuns}
              className="min-h-[44px] min-w-[44px] flex items-center justify-center text-gray-500 hover:text-gray-300 text-sm transition-colors"
            >
              Refresh
            </button>
          </div>

          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="p-4 text-gray-500 text-sm">Loading...</div>
            ) : runs.length === 0 ? (
              <div className="p-4 text-gray-500 text-sm">No builds yet.</div>
            ) : (
              <div className="flex flex-col">
                {runs.map((run) => {
                  const id = run.id || run.run_id;
                  return (
                    <button
                      key={id}
                      onClick={() => handleSelectRun(run)}
                      className="w-full text-left px-4 py-4 border-b border-gray-800 transition-colors hover:bg-gray-800 active:bg-gray-750 min-h-[60px]"
                    >
                      <p className="text-gray-200 text-base font-medium truncate">{run.title}</p>
                      <div className="flex items-center gap-2 mt-1.5">
                        <StatusBadge status={run.status} />
                        <span className="text-gray-600 text-xs font-mono">
                          {run.file_count ?? 0} files
                        </span>
                      </div>
                      <p className="text-gray-600 text-xs mt-1 font-mono">
                        {formatDate(run.created_at)}
                      </p>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      );
    }

    // Mobile detail view
    return (
      <div className="flex flex-col h-full min-h-0">
        {/* Back header */}
        <div className="p-4 border-b border-gray-800 flex items-center gap-3 flex-shrink-0">
          <button
            onClick={handleBackToList}
            className="min-h-[44px] min-w-[44px] flex items-center justify-center text-gray-400 hover:text-gray-200 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <h2 className="font-['Bebas_Neue'] text-xl text-gray-100 tracking-widest truncate">
            {selectedRun.title}
          </h2>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {/* Status + meta */}
          <div className="flex items-center gap-3 flex-wrap mb-4">
            <StatusBadge status={selectedRun.status} />
            <span className="text-gray-500 text-xs font-mono">
              {formatDate(selectedRun.created_at)}
            </span>
            {selectedRun.duration_seconds && (
              <span className="text-gray-500 text-xs font-mono">
                {formatDuration(selectedRun.duration_seconds)}
              </span>
            )}
          </div>

          {/* Action buttons — full width, 44px min height */}
          <div className="flex flex-col gap-2 mb-5">
            {selectedRun.package_ready && (
              <button
                onClick={handleDownloadZip}
                className="w-full min-h-[44px] px-4 py-3 bg-green-700 hover:bg-green-600 active:bg-green-500 text-white text-sm font-medium rounded-lg transition-colors"
              >
                Download ZIP
              </button>
            )}
            {selectedRun.github_repo_url && (
              <a
                href={selectedRun.github_repo_url}
                target="_blank"
                rel="noopener noreferrer"
                className="w-full min-h-[44px] px-4 py-3 bg-gray-800 hover:bg-gray-700 text-cyan-400 text-sm font-medium rounded-lg transition-colors text-center flex items-center justify-center"
              >
                Open on GitHub →
              </a>
            )}
            <div className="flex gap-2">
              <button
                onClick={handleRebuild}
                className="flex-1 min-h-[44px] px-4 py-3 bg-gray-800 hover:bg-gray-700 active:bg-gray-600 text-purple-400 text-sm font-medium rounded-lg transition-colors"
              >
                Rebuild
              </button>
              <button
                onClick={handleRegisterAgent}
                disabled={registering}
                className="flex-1 min-h-[44px] px-4 py-3 bg-gray-800 hover:bg-gray-700 active:bg-gray-600 text-teal-400 text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
              >
                {registering ? "Registering..." : "Add to Office"}
              </button>
            </div>
            {selectedRun.status === "failed" && (
              <button
                onClick={handleResume}
                className="w-full min-h-[44px] px-4 py-3 bg-amber-700 hover:bg-amber-600 active:bg-amber-500 text-white text-sm font-medium rounded-lg transition-colors"
              >
                Resume
              </button>
            )}
            {ACTIVE_STATUSES.includes(selectedRun.status) && (
              <button
                onClick={handleForceFail}
                className="w-full min-h-[44px] px-4 py-3 bg-red-900 hover:bg-red-800 active:bg-red-700 text-red-200 text-sm font-medium rounded-lg transition-colors"
              >
                Mark Failed
              </button>
            )}
          </div>

          {registerMsg && (
            <p className="text-sm text-teal-300 bg-teal-950/30 border border-teal-900 rounded-lg px-3 py-2 mb-4">
              {registerMsg}
            </p>
          )}

          {selectedRun.status === "complete" && (
            <DeploymentPanel run={selectedRun} isMobile={true} />
          )}

          {loadingDetail && (
            <p className="text-gray-500 text-xs mb-4">Loading files...</p>
          )}

          {/* Stats — 2x2 grid on mobile */}
          <div className="grid grid-cols-2 gap-2 mb-5">
            {[
              { label: "Total Files", value: loadingDetail ? "…" : files.length, color: "text-gray-100" },
              { label: "Complete", value: completedFiles, color: "text-green-400" },
              { label: "Failed", value: failedFiles, color: "text-red-400" },
              { label: "Est. Cost", value: `$${costEstimate}`, color: "text-yellow-400" },
            ].map((s) => (
              <div
                key={s.label}
                className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-3 text-center"
              >
                <p className={`text-lg font-bold font-mono ${s.color}`}>{s.value}</p>
                <p className="text-gray-500 text-xs mt-0.5">{s.label}</p>
              </div>
            ))}
          </div>

          {/* Error banner — mobile */}
          {selectedRun.error_message && (
            <div className="bg-red-950/30 border border-red-900 rounded-lg px-4 py-3 text-red-300 text-sm mb-5">
              {selectedRun.error_message}
            </div>
          )}

          {/* Deployment links */}
          {slug && (
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-5">
              <p className="text-gray-500 text-xs uppercase tracking-wider mb-3">Deployment Links</p>
              <div className="flex flex-col gap-2">
                {[
                  { label: "Dashboard", url: `https://${slug}-dashboard.fly.dev` },
                  { label: "API", url: `https://${slug}-api.fly.dev` },
                  { label: "Health", url: `https://${slug}-api.fly.dev/health` },
                ].map((link) => (
                  <a
                    key={link.label}
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="min-h-[44px] flex items-center gap-3 px-3 py-2 bg-gray-800 rounded-lg active:bg-gray-700 transition-colors"
                  >
                    <span className="text-gray-500 text-xs w-20 flex-shrink-0">{link.label}</span>
                    <span className="text-cyan-400 text-xs font-mono truncate">{link.url}</span>
                  </a>
                ))}
              </div>
            </div>
          )}

          {/* Detail tabs */}
          <div className="flex gap-0 mb-4 border-b border-gray-800 overflow-x-auto">
            {[
              { id: "files", label: files.length > 0 ? `Files (${files.length})` : "Files" },
              { id: "logs", label: runLogs.length > 0 ? `Logs (${runLogs.length})` : "Logs" },
              { id: "cost", label: "Cost" },
              { id: "versions", label: runVersions.length > 0 ? `Versions (${runVersions.length})` : "Versions" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveDetailTab(tab.id)}
                className={`px-4 py-2.5 text-xs font-medium uppercase tracking-wider transition-colors border-b-2 -mb-px flex-shrink-0 min-h-[44px] ${
                  activeDetailTab === tab.id
                    ? "text-purple-400 border-purple-500"
                    : "text-gray-500 border-transparent"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Files tab */}
          {activeDetailTab === "files" && (
            <>
              {files.length > 0 && (
                <div className="mb-5">
                  <div className="flex flex-col gap-3">
                    {Object.entries(layerGroups)
                      .sort(([a], [b]) => Number(a) - Number(b))
                      .map(([layer, layerFiles]) => (
                        <div key={layer} className="border border-gray-800 rounded-lg overflow-hidden w-full">
                          <div className="bg-gray-800/50 px-4 py-2.5 text-xs text-gray-400 font-medium uppercase tracking-wider">
                            {LAYER_LABELS[layer] || `Layer ${layer}`}
                          </div>
                          <div className="divide-y divide-gray-800">
                            {layerFiles.map((f, i) => (
                              <button
                                key={i}
                                onClick={() => setSelectedFile(selectedFile?.file_path === f.file_path ? null : f)}
                                className={`w-full text-left px-4 py-3 hover:bg-gray-800 active:bg-gray-750 transition-colors flex items-center gap-3 min-h-[44px] ${
                                  selectedFile?.file_path === f.file_path ? "bg-gray-800" : ""
                                }`}
                              >
                                <FileStatusIcon status={f.status} />
                                <span className="text-gray-300 text-sm font-mono flex-1 truncate">
                                  {f.file_path || f.path || f.filename}
                                </span>
                                {f.size && (
                                  <span className="text-gray-600 text-xs font-mono flex-shrink-0">
                                    {formatBytes(f.size)}
                                  </span>
                                )}
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {selectedFile && (
                <div className="mb-5 border border-gray-700 rounded-lg overflow-hidden w-full">
                  <div className="bg-gray-800 px-4 py-2.5 flex items-center justify-between">
                    <span className="text-gray-300 text-xs font-mono truncate flex-1 mr-2">
                      {selectedFile.file_path || selectedFile.path || selectedFile.filename}
                    </span>
                    <button
                      onClick={() => setSelectedFile(null)}
                      className="min-h-[44px] min-w-[44px] flex items-center justify-center text-gray-500 hover:text-gray-300 text-sm transition-colors flex-shrink-0"
                    >
                      ✕
                    </button>
                  </div>
                  <pre className="bg-gray-950 text-gray-300 text-xs font-['IBM_Plex_Mono'] p-4 overflow-x-auto max-h-72 overflow-y-auto whitespace-pre-wrap max-w-full">
                    {selectedFile.content || selectedFile.generated_content || "No content available."}
                  </pre>
                </div>
              )}

              {files.some((f) => (f.file_path || f.path || f.filename || "").includes("SECURITY_REPORT")) && (
                <div className="mb-5 border border-orange-900 rounded-lg overflow-hidden w-full">
                  <div className="bg-orange-950/30 px-4 py-2.5">
                    <span className="text-orange-400 text-sm font-medium">Security Report</span>
                  </div>
                  <pre className="bg-gray-950 text-gray-300 text-xs font-['IBM_Plex_Mono'] p-4 overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap">
                    {files.find((f) => (f.file_path || f.path || f.filename || "").includes("SECURITY_REPORT"))?.content || ""}
                  </pre>
                </div>
              )}

              {files.length === 0 && !loadingDetail && (
                <p className="text-gray-600 text-sm">No files generated yet.</p>
              )}
            </>
          )}

          {/* Logs tab */}
          {activeDetailTab === "logs" && (
            <div className="mb-5">
              {runLogs.length === 0 ? (
                <p className="text-gray-600 text-sm">No logs available.</p>
              ) : (
                <div className="bg-gray-950 border border-gray-800 rounded-lg overflow-hidden">
                  <div className="max-h-[500px] overflow-y-auto font-['IBM_Plex_Mono'] text-xs divide-y divide-gray-800/50">
                    {runLogs.map((log, i) => {
                      const levelColor =
                        log.level === "ERROR" ? "text-red-400" :
                        log.level === "WARNING" ? "text-yellow-400" :
                        log.level === "INFO" ? "text-blue-400" : "text-gray-500";
                      return (
                        <div key={i} className="px-4 py-2.5">
                          <div className="flex items-center gap-2 mb-0.5">
                            <span className={`text-xs flex-shrink-0 ${levelColor}`}>{log.level || "DEBUG"}</span>
                            <span className="text-gray-600 text-xs flex-shrink-0">
                              {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : ""}
                            </span>
                          </div>
                          <p className="text-gray-300 break-all leading-relaxed">{log.message}</p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Cost tab */}
          {activeDetailTab === "cost" && (
            <div className="mb-5">
              {!runCost ? (
                <p className="text-gray-600 text-sm">No cost data available.</p>
              ) : (
                <div className="space-y-4">
                  <div className="grid grid-cols-1 gap-3">
                    {[
                      { label: "Total Cost (USD)", value: `$${(runCost.total_cost_usd ?? 0).toFixed(4)}`, color: "text-yellow-400" },
                      { label: "Total Cost (AUD)", value: `A$${(runCost.total_cost_aud ?? 0).toFixed(4)}`, color: "text-orange-400" },
                      { label: "Total Tokens", value: ((runCost.total_input_tokens ?? 0) + (runCost.total_output_tokens ?? 0)).toLocaleString(), color: "text-cyan-400" },
                    ].map((s) => (
                      <div key={s.label} className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 flex items-center justify-between">
                        <span className="text-gray-400 text-sm">{s.label}</span>
                        <span className={`text-lg font-bold font-mono ${s.color}`}>{s.value}</span>
                      </div>
                    ))}
                  </div>
                  {runCost.breakdown && runCost.breakdown.length > 0 && (
                    <div className="border border-gray-800 rounded-lg overflow-hidden">
                      <div className="bg-gray-800/50 px-4 py-2.5 text-xs text-gray-400 font-medium uppercase tracking-wider">
                        Cost Breakdown by Stage
                      </div>
                      <div className="divide-y divide-gray-800">
                        {runCost.breakdown.map((row, i) => (
                          <div key={i} className="px-4 py-3">
                            <div className="flex items-center justify-between gap-2 mb-1">
                              <span className="text-gray-300 text-sm capitalize">{row.stage}</span>
                              <span className="text-yellow-400 text-sm font-mono font-medium">${(row.cost_usd ?? 0).toFixed(4)}</span>
                            </div>
                            <div className="flex items-center gap-3 text-xs text-gray-500">
                              <span className="font-mono truncate">{row.model}</span>
                              <span>in:{(row.input_tokens ?? 0).toLocaleString()}</span>
                              <span>out:{(row.output_tokens ?? 0).toLocaleString()}</span>
                            </div>
                            {row.file_path && (
                              <p className="text-gray-600 text-xs font-mono mt-1 truncate">{row.file_path}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Versions tab */}
          {activeDetailTab === "versions" && (
            <div className="mb-5">
              {runVersions.length === 0 ? (
                <p className="text-gray-600 text-sm">No version history available.</p>
              ) : (
                <div className="space-y-3">
                  {runVersions.map((v, i) => (
                    <div key={i} className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3">
                      <div className="flex items-center justify-between gap-3 mb-1">
                        <span className="text-gray-200 text-sm font-medium font-mono">{v.version || `v${i + 1}`}</span>
                        <span className="text-gray-500 text-xs font-mono">{v.created_at ? new Date(v.created_at).toLocaleString() : "—"}</span>
                      </div>
                      {v.changes && <p className="text-gray-400 text-sm mt-1">{v.changes}</p>}
                      {v.file_count != null && (
                        <p className="text-gray-600 text-xs mt-1">{v.file_count} files</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Desktop Layout ─────────────────────────────────────────────────────
  return (
    <div className="flex h-full gap-0 -m-6 min-h-0">
      {/* Left: run list */}
      <div className="w-72 flex-shrink-0 border-r border-gray-800 bg-gray-900 flex flex-col">
        <div className="p-4 border-b border-gray-800 flex items-center justify-between">
          <h2 className="font-['Bebas_Neue'] text-2xl text-gray-100 tracking-widest">
            RESULTS
          </h2>
          <button
            onClick={loadRuns}
            className="text-gray-500 hover:text-gray-300 text-xs transition-colors"
          >
            Refresh
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="p-4 text-gray-500 text-sm">Loading...</div>
          ) : runs.length === 0 ? (
            <div className="p-4 text-gray-500 text-sm">No builds yet.</div>
          ) : (
            runs.map((run) => {
              const id = run.id || run.run_id;
              const isSelected = selectedRun && (selectedRun.id || selectedRun.run_id) === id;
              return (
                <button
                  key={id}
                  onClick={() => handleSelectRun(run)}
                  className={`w-full text-left px-4 py-3 border-b border-gray-800 transition-colors hover:bg-gray-800 ${
                    isSelected ? "bg-purple-950/30 border-l-2 border-l-purple-600" : ""
                  }`}
                >
                  <p className="text-gray-200 text-sm font-medium truncate">{run.title}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <StatusBadge status={run.status} />
                    <span className="text-gray-600 text-xs font-mono">
                      {run.file_count ?? 0} files
                    </span>
                  </div>
                  <p className="text-gray-600 text-xs mt-1 font-mono">
                    {formatDate(run.created_at)}
                  </p>
                </button>
              );
            })
          )}
        </div>
      </div>

      {/* Right: detail */}
      <div className="flex-1 overflow-y-auto p-6">
        {!selectedRun ? (
          <div className="flex items-center justify-center h-64 text-gray-600">
            Select a build to view details
          </div>
        ) : (
          <div>
            {/* Header */}
            <div className="flex items-start justify-between gap-4 mb-5">
              <div>
                <h3 className="text-gray-100 text-xl font-semibold mb-1">
                  {selectedRun.title}
                </h3>
                <div className="flex items-center gap-3 flex-wrap">
                  <StatusBadge status={selectedRun.status} />
                  <span className="text-gray-500 text-xs font-mono">
                    {formatDate(selectedRun.created_at)}
                  </span>
                  {selectedRun.duration_seconds && (
                    <span className="text-gray-500 text-xs font-mono">
                      {formatDuration(selectedRun.duration_seconds)}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex gap-2 flex-wrap">
                {selectedRun.package_ready && (
                  <button
                    onClick={handleDownloadZip}
                    className="px-3 py-1.5 bg-green-700 hover:bg-green-600 text-white text-xs rounded-lg transition-colors"
                  >
                    Download ZIP
                  </button>
                )}
                {selectedRun.github_repo_url && (
                  <a
                    href={selectedRun.github_repo_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-cyan-400 text-xs rounded-lg transition-colors"
                  >
                    GitHub →
                  </a>
                )}
                <button
                  onClick={handleRebuild}
                  className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-purple-400 text-xs rounded-lg transition-colors"
                >
                  Rebuild
                </button>
                <button
                  onClick={handleRegisterAgent}
                  disabled={registering}
                  className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-teal-400 text-xs rounded-lg transition-colors disabled:opacity-50"
                >
                  {registering ? "Registering..." : "Add to Office"}
                </button>
                {selectedRun.status === "failed" && (
                  <button
                    onClick={handleResume}
                    className="px-3 py-1.5 bg-amber-700 hover:bg-amber-600 text-white text-xs rounded-lg transition-colors"
                  >
                    Resume
                  </button>
                )}
                {ACTIVE_STATUSES.includes(selectedRun.status) && (
                  <button
                    onClick={handleForceFail}
                    className="px-3 py-1.5 bg-red-900 hover:bg-red-800 text-red-200 text-xs rounded-lg transition-colors"
                  >
                    Mark Failed
                  </button>
                )}
              </div>
            </div>

            {registerMsg && (
              <p className="text-sm text-teal-300 bg-teal-950/30 border border-teal-900 rounded-lg px-3 py-2 mb-4">
                {registerMsg}
              </p>
            )}

            {selectedRun.status === "complete" && (
              <DeploymentPanel run={selectedRun} isMobile={false} />
            )}

            {/* Error banner — desktop */}
            {selectedRun.error_message && (
              <div className="bg-red-950/30 border border-red-900 rounded-lg px-4 py-3 text-red-300 text-sm mb-5">
                {selectedRun.error_message}
              </div>
            )}

            {/* Stats */}
            <div className="grid grid-cols-4 gap-3 mb-6">
              {[
                { label: "Total Files", value: files.length, color: "text-gray-100" },
                { label: "Complete", value: completedFiles, color: "text-green-400" },
                { label: "Failed", value: failedFiles, color: "text-red-400" },
                { label: "Est. Cost", value: `$${costEstimate}`, color: "text-yellow-400" },
              ].map((s) => (
                <div
                  key={s.label}
                  className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 text-center"
                >
                  <p className={`text-xl font-bold font-mono ${s.color}`}>{s.value}</p>
                  <p className="text-gray-500 text-xs mt-0.5">{s.label}</p>
                </div>
              ))}
            </div>

            {/* Deployment links */}
            {slug && (
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-5">
                <p className="text-gray-500 text-xs uppercase tracking-wider mb-3">Deployment Links</p>
                <div className="space-y-2">
                  {[
                    { label: "Dashboard", url: `https://${slug}-dashboard.fly.dev` },
                    { label: "API", url: `https://${slug}-api.fly.dev` },
                    { label: "Health", url: `https://${slug}-api.fly.dev/health` },
                  ].map((link) => (
                    <div key={link.label} className="flex items-center gap-3">
                      <span className="text-gray-500 text-xs w-20">{link.label}</span>
                      <a
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-cyan-400 hover:text-cyan-300 text-xs font-mono transition-colors"
                      >
                        {link.url}
                      </a>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Detail tabs */}
            <div className="flex gap-0 mb-5 border-b border-gray-800">
              {[
                { id: "files", label: files.length > 0 ? `Files (${files.length})` : "Files" },
                { id: "logs", label: runLogs.length > 0 ? `Logs (${runLogs.length})` : "Logs" },
                { id: "cost", label: "Cost" },
                { id: "versions", label: runVersions.length > 0 ? `Versions (${runVersions.length})` : "Versions" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveDetailTab(tab.id)}
                  className={`px-4 py-2 text-xs font-medium uppercase tracking-wider transition-colors border-b-2 -mb-px ${
                    activeDetailTab === tab.id
                      ? "text-purple-400 border-purple-500"
                      : "text-gray-500 hover:text-gray-300 border-transparent"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Files tab */}
            {activeDetailTab === "files" && (
              <>
                {files.length > 0 && (
                  <div className="mb-6">
                    <div className="space-y-4">
                      {Object.entries(layerGroups)
                        .sort(([a], [b]) => Number(a) - Number(b))
                        .map(([layer, layerFiles]) => (
                          <div key={layer} className="border border-gray-800 rounded-lg overflow-hidden">
                            <div className="bg-gray-800/50 px-4 py-2 text-xs text-gray-400 font-medium uppercase tracking-wider">
                              {LAYER_LABELS[layer] || `Layer ${layer}`}
                            </div>
                            <div className="divide-y divide-gray-800">
                              {layerFiles.map((f, i) => (
                                <button
                                  key={i}
                                  onClick={() => setSelectedFile(selectedFile?.file_path === f.file_path ? null : f)}
                                  className={`w-full text-left px-4 py-2.5 hover:bg-gray-800 transition-colors flex items-center gap-3 ${
                                    selectedFile?.file_path === f.file_path ? "bg-gray-800" : ""
                                  }`}
                                >
                                  <FileStatusIcon status={f.status} />
                                  <span className="text-gray-300 text-sm font-mono flex-1 truncate">
                                    {f.file_path || f.path || f.filename}
                                  </span>
                                  {f.size && (
                                    <span className="text-gray-600 text-xs font-mono flex-shrink-0">
                                      {formatBytes(f.size)}
                                    </span>
                                  )}
                                </button>
                              ))}
                            </div>
                          </div>
                        ))}
                    </div>
                  </div>
                )}

                {selectedFile && (
                  <div className="mb-6 border border-gray-700 rounded-lg overflow-hidden">
                    <div className="bg-gray-800 px-4 py-2.5 flex items-center justify-between">
                      <span className="text-gray-300 text-sm font-mono">
                        {selectedFile.file_path || selectedFile.path || selectedFile.filename}
                      </span>
                      <button
                        onClick={() => setSelectedFile(null)}
                        className="text-gray-500 hover:text-gray-300 text-sm transition-colors"
                      >
                        ✕
                      </button>
                    </div>
                    <pre className="bg-gray-950 text-gray-300 text-xs font-['IBM_Plex_Mono'] p-4 overflow-x-auto max-h-96 overflow-y-auto whitespace-pre-wrap">
                      {selectedFile.content || selectedFile.generated_content || "No content available."}
                    </pre>
                  </div>
                )}

                {files.some((f) => (f.file_path || f.path || f.filename || "").includes("SECURITY_REPORT")) && (
                  <div className="mb-6 border border-orange-900 rounded-lg overflow-hidden">
                    <div className="bg-orange-950/30 px-4 py-2.5">
                      <span className="text-orange-400 text-sm font-medium">Security Report</span>
                    </div>
                    <pre className="bg-gray-950 text-gray-300 text-xs font-['IBM_Plex_Mono'] p-4 overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap">
                      {files.find((f) => (f.file_path || f.path || f.filename || "").includes("SECURITY_REPORT"))?.content || ""}
                    </pre>
                  </div>
                )}

                {files.length === 0 && !loadingDetail && (
                  <p className="text-gray-600 text-sm">No files generated yet.</p>
                )}
              </>
            )}

            {/* Logs tab */}
            {activeDetailTab === "logs" && (
              <div className="mb-6">
                {runLogs.length === 0 ? (
                  <p className="text-gray-600 text-sm">No logs available.</p>
                ) : (
                  <div className="bg-gray-950 border border-gray-800 rounded-lg overflow-hidden">
                    <div className="max-h-[600px] overflow-y-auto font-['IBM_Plex_Mono'] text-xs divide-y divide-gray-800/50">
                      {runLogs.map((log, i) => {
                        const levelColor =
                          log.level === "ERROR" ? "text-red-400" :
                          log.level === "WARNING" ? "text-yellow-400" :
                          log.level === "INFO" ? "text-blue-400" : "text-gray-500";
                        return (
                          <div key={i} className="flex gap-3 px-4 py-2 hover:bg-gray-900/50">
                            <span className="text-gray-600 flex-shrink-0 w-20 truncate">
                              {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : "—"}
                            </span>
                            <span className={`flex-shrink-0 w-16 ${levelColor}`}>
                              {log.level || "DEBUG"}
                            </span>
                            <span className="text-gray-300 break-all">{log.message}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Cost tab */}
            {activeDetailTab === "cost" && (
              <div className="mb-6">
                {!runCost ? (
                  <p className="text-gray-600 text-sm">No cost data available.</p>
                ) : (
                  <div className="space-y-4">
                    <div className="grid grid-cols-3 gap-3">
                      {[
                        { label: "Total Cost (USD)", value: `$${(runCost.total_cost_usd ?? 0).toFixed(4)}`, color: "text-yellow-400" },
                        { label: "Total Cost (AUD)", value: `A$${(runCost.total_cost_aud ?? 0).toFixed(4)}`, color: "text-orange-400" },
                        { label: "Total Tokens", value: ((runCost.total_input_tokens ?? 0) + (runCost.total_output_tokens ?? 0)).toLocaleString(), color: "text-cyan-400" },
                      ].map((s) => (
                        <div key={s.label} className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 text-center">
                          <p className={`text-xl font-bold font-mono ${s.color}`}>{s.value}</p>
                          <p className="text-gray-500 text-xs mt-0.5">{s.label}</p>
                        </div>
                      ))}
                    </div>
                    {runCost.breakdown && runCost.breakdown.length > 0 && (
                      <div className="border border-gray-800 rounded-lg overflow-hidden">
                        <div className="bg-gray-800/50 px-4 py-2 text-xs text-gray-400 font-medium uppercase tracking-wider">
                          Cost Breakdown by Stage
                        </div>
                        <div className="divide-y divide-gray-800">
                          {runCost.breakdown.map((row, i) => (
                            <div key={i} className="flex items-center gap-4 px-4 py-2.5 text-xs">
                              <span className="text-gray-400 w-24 flex-shrink-0 capitalize">{row.stage}</span>
                              <span className="text-gray-500 font-mono flex-shrink-0 w-28 truncate">{row.model}</span>
                              <span className="text-gray-500 flex-1 truncate font-mono text-gray-600">{row.file_path || "—"}</span>
                              <span className="text-gray-400 font-mono flex-shrink-0">in:{(row.input_tokens ?? 0).toLocaleString()}</span>
                              <span className="text-gray-400 font-mono flex-shrink-0">out:{(row.output_tokens ?? 0).toLocaleString()}</span>
                              <span className="text-yellow-400 font-mono font-medium flex-shrink-0">${(row.cost_usd ?? 0).toFixed(4)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Versions tab */}
            {activeDetailTab === "versions" && (
              <div className="mb-6">
                {runVersions.length === 0 ? (
                  <p className="text-gray-600 text-sm">No version history available.</p>
                ) : (
                  <div className="space-y-3">
                    {runVersions.map((v, i) => (
                      <div key={i} className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3">
                        <div className="flex items-center justify-between gap-4 mb-1">
                          <span className="text-gray-200 text-sm font-medium font-mono">{v.version || `v${i + 1}`}</span>
                          <span className="text-gray-500 text-xs font-mono">{v.created_at ? new Date(v.created_at).toLocaleString() : "—"}</span>
                        </div>
                        {v.changes && <p className="text-gray-400 text-xs mt-1">{v.changes}</p>}
                        {v.file_count != null && (
                          <p className="text-gray-600 text-xs mt-1">{v.file_count} files</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}