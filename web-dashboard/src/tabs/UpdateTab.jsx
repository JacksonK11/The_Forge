
import { useState, useEffect, useRef, useCallback } from "react";
import { submitUpdate, getUpdate, getUpdates } from "../api.js";

const UPDATE_STAGES = ["queued", "cloning", "analyzing", "generating", "committing", "complete", "failed"];

function stageIndex(status) {
  const idx = UPDATE_STAGES.indexOf(status);
  return idx === -1 ? 0 : idx;
}

function StatusBadge({ status }) {
  const map = {
    complete: "bg-green-900/50 text-green-400 border-green-800",
    failed: "bg-red-900/50 text-red-400 border-red-800",
    queued: "bg-gray-800 text-gray-400 border-gray-700",
    cloning: "bg-blue-900/50 text-blue-400 border-blue-800",
    analyzing: "bg-yellow-900/50 text-yellow-400 border-yellow-800",
    generating: "bg-purple-900/50 text-purple-400 border-purple-800",
    committing: "bg-teal-900/50 text-teal-400 border-teal-800",
  };
  const cls = map[status] || "bg-gray-800 text-gray-400 border-gray-700";
  return (
    <span className={`inline-flex px-2 py-0.5 rounded border text-xs font-medium uppercase tracking-wide ${cls}`}>
      {status}
    </span>
  );
}

function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function UpdateTab({ isMobile = false }) {
  const [repoUrl, setRepoUrl] = useState("");
  const [changeDescription, setChangeDescription] = useState("");
  const [updateTitle, setUpdateTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [currentUpdate, setCurrentUpdate] = useState(null);
  const [currentStatus, setCurrentStatus] = useState(null);
  const [pastUpdates, setPastUpdates] = useState([]);
  const [error, setError] = useState("");
  const pollRef = useRef(null);

  useEffect(() => {
    loadPastUpdates();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  async function loadPastUpdates() {
    try {
      const data = await getUpdates();
      setPastUpdates(Array.isArray(data) ? data.slice(0, 10) : []);
    } catch {
      // non-fatal
    }
  }

  const startPolling = useCallback((updateId) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const data = await getUpdate(updateId);
        setCurrentStatus(data);
        if (["complete", "failed"].includes(data.status)) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          loadPastUpdates();
        }
      } catch {
        // keep polling
      }
    }, 3000);
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!repoUrl.trim() || !changeDescription.trim()) {
      setError("Repo URL and change description are required.");
      return;
    }
    setError("");
    setSubmitting(true);
    setCurrentUpdate(null);
    setCurrentStatus(null);
    try {
      const data = await submitUpdate({
        github_repo_url: repoUrl.trim(),
        change_description: changeDescription.trim(),
        title: updateTitle.trim() || undefined,
      });
      setCurrentUpdate(data);
      setCurrentStatus(data);
      startPolling(data.id || data.update_id);
    } catch (err) {
      setError(`Submission failed: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  const updateId = currentUpdate?.id || currentUpdate?.update_id;
  const status = currentStatus?.status || "";
  const curIdx = stageIndex(status);
  const PROGRESS_STAGES = UPDATE_STAGES.filter((s) => s !== "failed");

  return (
    <div className={`${isMobile ? "w-full px-1" : "max-w-3xl mx-auto"}`}>
      <h2 className={`font-['Bebas_Neue'] text-gray-100 tracking-widest mb-6 ${isMobile ? "text-3xl" : "text-4xl"}`}>
        UPDATE AGENT
      </h2>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className={`block text-gray-400 font-medium mb-1.5 ${isMobile ? "text-base" : "text-sm"}`}>
            GitHub Repo URL <span className="text-red-400">*</span>
          </label>
          <input
            type="url"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            placeholder="https://github.com/user/repo"
            className={`w-full bg-gray-800 border border-gray-700 rounded-lg text-gray-100 placeholder-gray-600 font-mono focus:border-purple-600 focus:outline-none transition-colors ${
              isMobile ? "px-4 py-3 text-base min-h-[44px]" : "px-4 py-2.5 text-sm"
            }`}
            required
          />
        </div>

        <div>
          <label className={`block text-gray-400 font-medium mb-1.5 ${isMobile ? "text-base" : "text-sm"}`}>
            Update Title <span className={`text-gray-600 ${isMobile ? "text-sm" : "text-xs"}`}>(optional, for tracking)</span>
          </label>
          <input
            type="text"
            value={updateTitle}
            onChange={(e) => setUpdateTitle(e.target.value)}
            placeholder="e.g. Add rate limiting to API endpoints"
            className={`w-full bg-gray-800 border border-gray-700 rounded-lg text-gray-100 placeholder-gray-600 focus:border-purple-600 focus:outline-none transition-colors ${
              isMobile ? "px-4 py-3 text-base min-h-[44px]" : "px-4 py-2.5 text-sm"
            }`}
          />
        </div>

        <div>
          <label className={`block text-gray-400 font-medium mb-1.5 ${isMobile ? "text-base" : "text-sm"}`}>
            Change Description <span className="text-red-400">*</span>
          </label>
          <textarea
            value={changeDescription}
            onChange={(e) => setChangeDescription(e.target.value)}
            placeholder="Describe what you want to change. Be specific. E.g.: 'Add rate limiting to all API endpoints, 5 req/sec per IP. Use slowapi library.'"
            rows={isMobile ? 8 : 10}
            className={`w-full bg-gray-800 border border-gray-700 rounded-lg text-gray-100 placeholder-gray-600 font-['IBM_Plex_Mono'] focus:border-purple-600 focus:outline-none transition-colors resize-y ${
              isMobile ? "px-4 py-3 text-base" : "px-4 py-3 text-sm"
            }`}
            required
          />
        </div>

        {error && (
          <p className={`text-red-400 bg-red-950/30 border border-red-900 rounded-lg px-4 py-3 ${isMobile ? "text-base" : "text-sm"}`}>
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting || (status && !["complete", "failed"].includes(status))}
          className={`w-full bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-['Bebas_Neue'] tracking-widest rounded-lg transition-colors ${
            isMobile ? "text-xl py-4 min-h-[48px]" : "text-xl py-3"
          }`}
        >
          {submitting ? "SUBMITTING..." : "UPDATE"}
        </button>
      </form>

      {/* Progress */}
      {currentStatus && (
        <div className={`mt-8 border border-gray-800 rounded-lg bg-gray-900 ${isMobile ? "p-4" : "p-5"}`}>
          <div className={`flex items-center justify-between mb-5 ${isMobile ? "flex-col items-start gap-2" : ""}`}>
            <h3 className={`font-['Bebas_Neue'] text-gray-100 tracking-wider ${isMobile ? "text-lg" : "text-xl"}`}>
              UPDATE PROGRESS
            </h3>
            {updateId && (
              <span className="text-xs text-gray-500 font-mono truncate max-w-full">ID: {updateId}</span>
            )}
          </div>

          <div className="space-y-3">
            {PROGRESS_STAGES.map((stageKey, i) => {
              const isDone = i < curIdx || status === "complete";
              const isActive = i === curIdx && !["complete", "failed"].includes(status);
              const isPending = i > curIdx;
              const label = stageKey.charAt(0).toUpperCase() + stageKey.slice(1);

              return (
                <div
                  key={stageKey}
                  className={`flex items-center gap-3 px-3 rounded-lg transition-colors ${
                    isMobile ? "py-3 min-h-[44px]" : "py-2"
                  } ${
                    isActive
                      ? "bg-purple-950/40 border border-purple-800"
                      : isDone
                      ? "opacity-70"
                      : "opacity-40"
                  }`}
                >
                  <div className="w-6 flex-shrink-0 flex items-center justify-center">
                    {isDone ? (
                      <span className="text-green-400">✓</span>
                    ) : isActive ? (
                      <span className="inline-block w-5 h-5 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <span className="inline-block w-4 h-4 rounded-full border border-gray-600" />
                    )}
                  </div>
                  <span
                    className={`font-medium ${isMobile ? "text-base" : "text-sm"} ${
                      isActive ? "text-purple-300" : isDone ? "text-green-400" : "text-gray-500"
                    }`}
                  >
                    {label}
                  </span>
                </div>
              );
            })}
          </div>

          {status === "failed" && (
            <div className="mt-4 bg-red-950/30 border border-red-900 rounded-lg px-4 py-3">
              <p className={`text-red-400 font-medium ${isMobile ? "text-base" : "text-sm"}`}>Update Failed</p>
              {currentStatus?.error_message && (
                <p className={`text-red-300 mt-1 font-mono ${isMobile ? "text-sm" : "text-sm"}`}>{currentStatus.error_message}</p>
              )}
            </div>
          )}

          {status === "complete" && (
            <div className="mt-5 bg-green-950/20 border border-green-900 rounded-lg p-4">
              <p className={`text-green-400 font-semibold mb-3 ${isMobile ? "text-base" : ""}`}>Update Complete</p>
              <div className={`grid gap-4 mb-3 ${isMobile ? "grid-cols-3" : "grid-cols-3"}`}>
                <div className="text-center">
                  <p className={`text-yellow-400 font-bold font-mono ${isMobile ? "text-2xl" : "text-xl"}`}>
                    {currentStatus.files_modified ?? 0}
                  </p>
                  <p className={`text-gray-500 ${isMobile ? "text-sm" : "text-xs"}`}>Modified</p>
                </div>
                <div className="text-center">
                  <p className={`text-green-400 font-bold font-mono ${isMobile ? "text-2xl" : "text-xl"}`}>
                    {currentStatus.files_created ?? 0}
                  </p>
                  <p className={`text-gray-500 ${isMobile ? "text-sm" : "text-xs"}`}>Created</p>
                </div>
                <div className="text-center">
                  <p className={`text-red-400 font-bold font-mono ${isMobile ? "text-2xl" : "text-xl"}`}>
                    {currentStatus.files_deleted ?? 0}
                  </p>
                  <p className={`text-gray-500 ${isMobile ? "text-sm" : "text-xs"}`}>Deleted</p>
                </div>
              </div>
              {currentStatus?.github_repo_url && (
                <a
                  href={currentStatus.github_repo_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`text-cyan-400 hover:text-cyan-300 transition-colors ${isMobile ? "text-base min-h-[44px] inline-flex items-center" : "text-sm"}`}
                >
                  View changes on GitHub →
                </a>
              )}
            </div>
          )}
        </div>
      )}

      {/* Past updates */}
      {pastUpdates.length > 0 && (
        <div className="mt-8">
          <h3 className={`font-['Bebas_Neue'] text-gray-300 tracking-wider mb-4 ${isMobile ? "text-xl" : "text-2xl"}`}>
            RECENT UPDATES
          </h3>
          <div className={`${isMobile ? "space-y-4" : "space-y-3"}`}>
            {pastUpdates.map((u) => (
              <div
                key={u.id || u.update_id}
                className={`border border-gray-800 rounded-lg bg-gray-900 w-full ${isMobile ? "px-4 py-4" : "px-4 py-3"}`}
              >
                <div className={`${isMobile ? "flex flex-col gap-2" : "flex items-start justify-between gap-3"}`}>
                  <div className="min-w-0">
                    <p className={`text-gray-200 font-medium truncate ${isMobile ? "text-base" : "text-sm"}`}>
                      {u.title || u.github_repo_url || "Untitled Update"}
                    </p>
                    <p className={`text-gray-500 font-mono mt-0.5 truncate ${isMobile ? "text-sm" : "text-xs"}`}>
                      {u.github_repo_url}
                    </p>
                  </div>
                  <div className={`flex items-center gap-3 ${isMobile ? "" : "flex-shrink-0"}`}>
                    <StatusBadge status={u.status} />
                    <span className={`text-gray-600 font-mono whitespace-nowrap ${isMobile ? "text-sm" : "text-xs"}`}>
                      {formatDate(u.created_at)}
                    </span>
                  </div>
                </div>
                {u.status === "complete" && (
                  <div className={`mt-2 flex gap-4 text-gray-500 ${isMobile ? "text-sm" : "text-xs"}`}>
                    <span className="text-yellow-500">{u.files_modified ?? 0} modified</span>
                    <span className="text-green-500">{u.files_created ?? 0} created</span>
                    <span className="text-red-500">{u.files_deleted ?? 0} deleted</span>
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