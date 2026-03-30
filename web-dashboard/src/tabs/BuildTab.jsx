import { useState, useEffect, useRef, useCallback } from "react";
import {
  submitBuild,
  getRun,
  approveRun,
  getRunPackageBlob,
  getTemplates,
  triggerDownload,
  submitBuildWithFiles,
  getRunCostEstimate,
  getRunFiles,
} from "../api.js";
import FileAttachmentArea from "../components/FileAttachmentArea.jsx";

const STAGES = [
  { key: "queued",      label: "Queued" },
  { key: "validating",  label: "Validating" },
  { key: "parsing",     label: "Parsing" },
  { key: "confirming",  label: "Spec Confirmation" },
  { key: "architecting",label: "Architecting" },
  { key: "generating",  label: "Generating" },
  { key: "packaging",   label: "Packaging" },
  { key: "pushing",     label: "GitHub Push" },
  { key: "complete",    label: "Complete" },
  { key: "failed",      label: "Failed" },
];

const ACTIVE_STAGES = STAGES.filter(
  (s) => s.key !== "failed"
).map((s) => s.key);

function stageIndex(status) {
  const idx = ACTIVE_STAGES.indexOf(status);
  return idx === -1 ? 0 : idx;
}

function toKebab(str) {
  return str
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");
}

function StageIcon({ status, stageKey, currentStatus }) {
  const current = stageIndex(currentStatus);
  const me = stageIndex(stageKey);

  if (currentStatus === "failed" && me === stageIndex(currentStatus)) {
    return <span className="text-red-400 text-lg">✗</span>;
  }
  if (me < current || currentStatus === "complete") {
    if (stageKey === "failed") return null;
    return <span className="text-green-400 text-lg">✓</span>;
  }
  if (me === current) {
    return (
      <span className="inline-block w-5 h-5 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
    );
  }
  return (
    <span className="inline-block w-4 h-4 rounded-full border border-gray-600" />
  );
}

function SpecPanel({ spec, runId, onApprove, onReject, isMobile }) {
  const [approving, setApproving] = useState(false);
  const [costEstimate, setCostEstimate] = useState(null);

  useEffect(() => {
    if (!runId) return;
    getRunCostEstimate(runId)
      .then(setCostEstimate)
      .catch(() => {});
  }, [runId]);

  async function handleApprove() {
    setApproving(true);
    try {
      await approveRun(runId);
      onApprove();
    } catch (err) {
      alert(`Approval failed: ${err.message}`);
      setApproving(false);
    }
  }

  const fileCount = costEstimate?.file_count ?? spec.file_list?.length ?? spec.file_count ?? "—";
  const estimatedCost = costEstimate?.estimated_cost_aud;

  return (
    <div className="mt-6 border border-purple-700 rounded-lg bg-purple-950/20 p-4 md:p-5">
      <h3 className="text-purple-300 font-semibold text-base mb-4 font-['Bebas_Neue'] tracking-wide text-xl">
        SPEC CONFIRMATION REQUIRED
      </h3>
      <p className="text-gray-400 text-sm mb-4">
        Review the parsed specification below. Approve to start code generation or reject to resubmit.
      </p>

      <div className={`grid gap-4 mb-4 ${isMobile ? "grid-cols-1" : "grid-cols-2"}`}>
        <div>
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Agent Name</p>
          <p className="text-gray-100 font-medium">{spec.agent_name || "—"}</p>
        </div>
        <div>
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Description</p>
          <p className="text-gray-100 text-sm">{spec.description || "—"}</p>
        </div>
        <div>
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Estimated Files</p>
          <p className="text-gray-100 font-medium">{fileCount}</p>
        </div>
        <div>
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-1">Estimated Cost</p>
          <p className={`font-medium ${estimatedCost > 10 ? "text-yellow-400" : "text-gray-100"}`}>
            {estimatedCost != null ? `A$${estimatedCost.toFixed(2)}` : "—"}
          </p>
        </div>
      </div>

      {spec.services && spec.services.length > 0 && (
        <div className="mb-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-2">Services</p>
          <div className="flex flex-wrap gap-2">
            {spec.services.map((s, i) => (
              <span key={i} className="bg-gray-800 text-gray-300 px-2 py-1 rounded text-xs font-mono">
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {spec.tables && spec.tables.length > 0 && (
        <div className="mb-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-2">Database Tables</p>
          <div className="flex flex-wrap gap-2">
            {spec.tables.map((t, i) => (
              <span key={i} className="bg-teal-900/40 text-teal-300 px-2 py-1 rounded text-xs font-mono">
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {spec.api_routes && spec.api_routes.length > 0 && (
        <div className="mb-4">
          <p className="text-gray-500 text-xs uppercase tracking-wider mb-2">API Routes</p>
          <div className="flex flex-wrap gap-2">
            {spec.api_routes.map((r, i) => (
              <span key={i} className="bg-gray-800 text-cyan-300 px-2 py-1 rounded text-xs font-mono">
                {r}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className={`flex gap-3 mt-5 ${isMobile ? "flex-col" : ""}`}>
        <button
          onClick={handleApprove}
          disabled={approving}
          className={`flex-1 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded-lg transition-colors ${
            isMobile ? "min-h-[44px] text-base" : ""
          }`}
        >
          {approving ? "Approving..." : "APPROVE — START BUILD"}
        </button>
        <button
          onClick={onReject}
          className={`px-5 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg transition-colors ${
            isMobile ? "min-h-[44px] text-base" : ""
          }`}
        >
          Reject
        </button>
      </div>
    </div>
  );
}

export default function BuildTab({ onGoToResults, initialBlueprint = "", isMobile = false }) {
  const [title, setTitle] = useState("");
  const [blueprintText, setBlueprintText] = useState(initialBlueprint);
  const [repoName, setRepoName] = useState("");
  const [pushToGithub, setPushToGithub] = useState(true);
  const [selectedTemplate, setSelectedTemplate] = useState("");
  const [attachedFiles, setAttachedFiles] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [templates, setTemplates] = useState([]);
  const [currentRun, setCurrentRun] = useState(null);
  const [runStatus, setRunStatus] = useState(null);
  const [runFiles, setRunFiles] = useState([]);
  const [error, setError] = useState("");
  const pollRef = useRef(null);
  const filesPollRef = useRef(null);
  const titleChanged = useRef(false);

  useEffect(() => {
    getTemplates()
      .then(setTemplates)
      .catch(() => {});
  }, []);

  function handleTitleChange(e) {
    const val = e.target.value;
    setTitle(val);
    if (!titleChanged.current) {
      setRepoName(toKebab(val));
    }
  }

  function handleRepoChange(e) {
    titleChanged.current = true;
    setRepoName(e.target.value);
  }

  function handleTemplateChange(e) {
    const id = e.target.value;
    setSelectedTemplate(id);
    if (id) {
      const tmpl = templates.find((t) => String(t.id) === id);
      if (tmpl) setBlueprintText(tmpl.content || "");
    }
  }

  function handleFilesAdded(newFiles) {
    const incoming = Array.from(newFiles);
    setAttachedFiles((prev) => [...prev, ...incoming]);
  }

  function handleFileRemoved(index) {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
  }

  const startPolling = useCallback((runId) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const data = await getRun(runId);
        setRunStatus(data);
        if (["complete", "failed"].includes(data.status)) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        // network hiccup — keep polling
      }
    }, 3000);
  }, []);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (filesPollRef.current) clearInterval(filesPollRef.current);
    };
  }, []);

  // Poll per-file status during generating stage
  useEffect(() => {
    const runId = runStatus?.run_id || currentRun;
    const isGenerating = runStatus?.status === "generating";
    if (isGenerating && runId) {
      if (!filesPollRef.current) {
        const fetchFiles = () =>
          getRunFiles(runId)
            .then(setRunFiles)
            .catch(() => {});
        fetchFiles();
        filesPollRef.current = setInterval(fetchFiles, 5000);
      }
    } else {
      if (filesPollRef.current) {
        clearInterval(filesPollRef.current);
        filesPollRef.current = null;
      }
      if (!isGenerating) setRunFiles([]);
    }
  }, [runStatus?.status, runStatus?.run_id, currentRun]);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!title.trim() || (!blueprintText.trim() && attachedFiles.length === 0)) {
      setError("Title and blueprint (or at least one attached file) are required.");
      return;
    }
    setError("");
    setSubmitting(true);
    setCurrentRun(null);
    setRunStatus(null);
    try {
      let data;
      const effectiveRepoName = repoName.trim() || toKebab(title);

      if (attachedFiles.length > 0) {
        // Use multipart/form-data endpoint — backend handles all file extraction
        data = await submitBuildWithFiles({
          title: title.trim(),
          blueprint_text: blueprintText.trim(),
          repo_name: effectiveRepoName,
          push_to_github: pushToGithub,
          files: attachedFiles,
        });
      } else {
        // No files attached — use standard JSON endpoint
        data = await submitBuild({
          title: title.trim(),
          blueprint_text: blueprintText.trim(),
          repo_name: effectiveRepoName,
          push_to_github: pushToGithub,
        });
      }

      setCurrentRun(data);
      setRunStatus(data);
      startPolling(data.id || data.run_id);
    } catch (err) {
      setError(`Submission failed: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  function handleReject() {
    setCurrentRun(null);
    setRunStatus(null);
    if (pollRef.current) clearInterval(pollRef.current);
  }

  async function handleDownloadZip() {
    const id = currentRun?.id || currentRun?.run_id;
    if (!id) return;
    try {
      const blob = await getRunPackageBlob(id);
      triggerDownload(blob, `${repoName || "forge-build"}.zip`);
    } catch (err) {
      alert(`Download failed: ${err.message}`);
    }
  }

  const runId = currentRun?.id || currentRun?.run_id;
  const status = runStatus?.status || "";
  const currentStageIdx = stageIndex(status);
  const isRunning = runStatus && !["complete", "failed"].includes(status);
  const specJson = runStatus?.spec_json || {};

  // Common input classes with responsive sizing
  const inputBase = `w-full bg-gray-800 border border-gray-700 rounded-lg text-gray-100 placeholder-gray-600 focus:border-purple-600 focus:outline-none transition-colors ${
    isMobile ? "px-4 py-3 text-base" : "px-4 py-2.5 text-sm"
  }`;

  return (
    <div className={`mx-auto ${isMobile ? "max-w-full px-1" : "max-w-3xl"}`}>
      <h2 className={`font-['Bebas_Neue'] text-gray-100 tracking-widest mb-6 ${
        isMobile ? "text-3xl" : "text-4xl"
      }`}>
        NEW BUILD
      </h2>

      <form onSubmit={handleSubmit} className={`space-y-${isMobile ? "6" : "5"}`}>
        {/* Title */}
        <div>
          <label className={`block text-gray-400 font-medium mb-1.5 ${isMobile ? "text-base" : "text-sm"}`}>
            Build Title <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={title}
            onChange={handleTitleChange}
            placeholder="e.g. BuildRight AI Agent — Sydney Construction Leads"
            className={inputBase}
            required
          />
        </div>

        {/* Repo name */}
        <div>
          <label className={`block text-gray-400 font-medium mb-1.5 ${isMobile ? "text-base" : "text-sm"}`}>
            GitHub Repo Name
          </label>
          <input
            type="text"
            value={repoName}
            onChange={handleRepoChange}
            placeholder="auto-generated from title"
            className={`${inputBase} font-mono`}
          />
        </div>

        {/* Template selector */}
        {templates.length > 0 && (
          <div>
            <label className={`block text-gray-400 font-medium mb-1.5 ${isMobile ? "text-base" : "text-sm"}`}>
              Load Template
            </label>
            <select
              value={selectedTemplate}
              onChange={handleTemplateChange}
              className={inputBase}
            >
              <option value="">— Select a template —</option>
              {templates.map((t) => (
                <option key={t.id} value={String(t.id)}>
                  [{t.category || "General"}] {t.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Blueprint textarea — instructions/prompts only */}
        <div>
          <label className={`block text-gray-400 font-medium mb-1.5 ${isMobile ? "text-base" : "text-sm"}`}>
            Blueprint <span className="text-red-400">*</span>
          </label>
          <textarea
            value={blueprintText}
            onChange={(e) => setBlueprintText(e.target.value)}
            placeholder="Type your instructions, requirements, and prompts here. Attach reference files below — they will be processed server-side..."
            rows={isMobile ? 10 : 14}
            className={`w-full bg-gray-800 border border-gray-700 rounded-lg text-gray-100 placeholder-gray-600 font-['IBM_Plex_Mono'] focus:border-purple-600 focus:outline-none transition-colors resize-y ${
              isMobile
                ? "px-4 py-4 text-base min-h-[200px]"
                : "px-4 py-3 text-sm"
            }`}
            required={attachedFiles.length === 0}
          />
          <p className="text-gray-600 text-xs mt-1">
            Type your instructions and prompts above. Attach supporting files below — the server extracts their content automatically.
          </p>
        </div>

        {/* File attachment area */}
        <FileAttachmentArea
          attachedFiles={attachedFiles}
          onFilesAdded={handleFilesAdded}
          onFileRemoved={handleFileRemoved}
          isMobile={isMobile}
        />

        {/* Push to GitHub toggle */}
        <label className={`flex items-center gap-3 cursor-pointer select-none ${
          isMobile ? "min-h-[44px] py-1" : ""
        }`}>
          <div className="relative">
            <input
              type="checkbox"
              checked={pushToGithub}
              onChange={(e) => setPushToGithub(e.target.checked)}
              className="sr-only"
            />
            <div
              className={`w-11 h-6 rounded-full transition-colors ${
                pushToGithub ? "bg-purple-600" : "bg-gray-700"
              }`}
            />
            <div
              className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                pushToGithub ? "translate-x-5" : "translate-x-0"
              }`}
            />
          </div>
          <span className={`text-gray-300 ${isMobile ? "text-base" : "text-sm"}`}>
            Push to GitHub after build
          </span>
        </label>

        {error && (
          <p className={`text-red-400 bg-red-950/30 border border-red-900 rounded-lg px-4 py-3 ${
            isMobile ? "text-base" : "text-sm"
          }`}>
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting || (isRunning && status !== "confirming")}
          className={`w-full bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-['Bebas_Neue'] tracking-widest rounded-lg transition-colors ${
            isMobile
              ? "text-2xl py-4 min-h-[44px]"
              : "text-xl py-3"
          }`}
        >
          {submitting
            ? attachedFiles.length > 0
              ? "UPLOADING FILES & SUBMITTING..."
              : "SUBMITTING..."
            : "BUILD"}
        </button>
      </form>

      {/* ── Progress Tracker ── */}
      {runStatus && (
        <div className={`mt-8 border border-gray-800 rounded-lg bg-gray-900 ${
          isMobile ? "p-4" : "p-5"
        }`}>
          <div className={`flex items-center justify-between mb-5 ${
            isMobile ? "flex-col items-start gap-2" : ""
          }`}>
            <h3 className="font-['Bebas_Neue'] text-xl text-gray-100 tracking-wider">
              BUILD PROGRESS
            </h3>
            <span className="text-xs text-gray-500 font-mono">
              ID: {isMobile ? `${String(runId).slice(0, 12)}...` : runId}
            </span>
          </div>

          {/* Stages */}
          <div className="space-y-3">
            {ACTIVE_STAGES.filter((s) => s !== "failed").map((stageKey, i) => {
              const stageLabel = STAGES.find((s) => s.key === stageKey)?.label || stageKey;
              const me = i;
              const cur = currentStageIdx;
              const isDone = me < cur || status === "complete";
              const isActive = me === cur && !["complete", "failed"].includes(status);

              return (
                <div
                  key={stageKey}
                  className={`flex items-center gap-3 px-3 rounded-lg transition-colors ${
                    isMobile ? "py-3" : "py-2"
                  } ${
                    isActive
                      ? "bg-purple-950/40 border border-purple-800"
                      : isDone
                      ? "opacity-70"
                      : "opacity-40"
                  }`}
                >
                  <div className="w-6 flex-shrink-0 flex items-center justify-center">
                    <StageIcon
                      status={status}
                      stageKey={stageKey}
                      currentStatus={status}
                    />
                  </div>
                  <span
                    className={`font-medium ${
                      isMobile ? "text-base" : "text-sm"
                    } ${
                      isActive
                        ? "text-purple-300"
                        : isDone
                        ? "text-green-400"
                        : "text-gray-500"
                    }`}
                  >
                    {stageLabel}
                  </span>
                  {isActive && runStatus?.stage_started_at && !isMobile && (
                    <span className="ml-auto text-xs text-gray-600 font-mono">
                      {new Date(runStatus.stage_started_at).toLocaleTimeString()}
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          {/* File generation progress */}
          {status === "generating" && runStatus?.file_count > 0 && (
            <div className="mt-5">
              <div className="flex items-center justify-between text-sm mb-2">
                <span className="text-gray-400">Files generated</span>
                <span className="text-gray-300 font-mono">
                  {runStatus.files_complete ?? 0} / {runStatus.file_count}
                </span>
              </div>
              <div className="h-2 bg-gray-800 rounded-full overflow-hidden mb-4">
                <div
                  className="h-full bg-purple-600 rounded-full transition-all duration-500"
                  style={{
                    width: `${
                      ((runStatus.files_complete ?? 0) / runStatus.file_count) * 100
                    }%`,
                  }}
                />
              </div>
              {runFiles.length > 0 && (
                <div className="space-y-1 max-h-64 overflow-y-auto pr-1">
                  {runFiles.map((f) => {
                    const done = f.status === "complete";
                    const failed = f.status === "generation_failed";
                    const active = !done && !failed && f.status === "generating";
                    return (
                      <div key={f.file_path} className="flex items-center gap-2">
                        <div className="w-24 shrink-0">
                          <div className="h-1 bg-gray-800 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all duration-300 ${
                                done
                                  ? "bg-green-500 w-full"
                                  : failed
                                  ? "bg-red-500 w-full"
                                  : active
                                  ? "bg-purple-500 w-1/2 animate-pulse"
                                  : "w-0"
                              }`}
                            />
                          </div>
                        </div>
                        <span
                          className={`text-xs font-mono truncate ${
                            done
                              ? "text-green-400"
                              : failed
                              ? "text-red-400"
                              : active
                              ? "text-purple-300"
                              : "text-gray-600"
                          }`}
                        >
                          {f.file_path}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Spec confirmation */}
          {status === "confirming" && (
            <SpecPanel
              spec={specJson}
              runId={runId}
              onApprove={() => startPolling(runId)}
              onReject={handleReject}
              isMobile={isMobile}
            />
          )}

          {/* Failed */}
          {status === "failed" && (
            <div className="mt-4 bg-red-950/30 border border-red-900 rounded-lg px-4 py-3">
              <p className={`text-red-400 font-medium ${isMobile ? "text-base" : "text-sm"}`}>
                Build Failed
              </p>
              {runStatus?.error_message && (
                <p className={`text-red-300 mt-1 font-mono ${isMobile ? "text-sm" : "text-sm"}`}>
                  {runStatus.error_message}
                </p>
              )}
            </div>
          )}

          {/* Complete */}
          {status === "complete" && (
            <div className="mt-5 bg-green-950/20 border border-green-900 rounded-lg p-4">
              <p className={`text-green-400 font-semibold mb-3 ${isMobile ? "text-lg" : "text-base"}`}>
                Build Complete
              </p>
              <div className={`flex gap-3 ${isMobile ? "flex-col" : "flex-wrap"}`}>
                {runStatus?.package_ready && (
                  <button
                    onClick={handleDownloadZip}
                    className={`bg-green-700 hover:bg-green-600 text-white rounded-lg transition-colors font-medium ${
                      isMobile
                        ? "w-full min-h-[44px] px-4 py-3 text-base"
                        : "px-4 py-2 text-sm"
                    }`}
                  >
                    Download ZIP
                  </button>
                )}
                <button
                  onClick={() => onGoToResults && onGoToResults(runId)}
                  className={`bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg transition-colors ${
                    isMobile
                      ? "w-full min-h-[44px] px-4 py-3 text-base"
                      : "px-4 py-2 text-sm"
                  }`}
                >
                  View in Results
                </button>
                {runStatus?.github_repo_url && (
                  <a
                    href={runStatus.github_repo_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`bg-gray-800 hover:bg-gray-700 text-cyan-400 rounded-lg transition-colors text-center ${
                      isMobile
                        ? "w-full min-h-[44px] px-4 py-3 text-base flex items-center justify-center"
                        : "px-4 py-2 text-sm"
                    }`}
                  >
                    View on GitHub →
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}