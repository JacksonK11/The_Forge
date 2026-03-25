import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { getPendingRuns, approveRun, getRuns } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";
import ConfirmModal from "../components/ConfirmModal.jsx";

function timeAgo(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function Approvals() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [confirmRun, setConfirmRun] = useState(null);
  const [approving, setApproving] = useState(null);

  const fetchPending = useCallback(async () => {
    try {
      // Try dedicated pending endpoint first, fall back to filtering all runs
      let list;
      try {
        const data = await getPendingRuns();
        list = Array.isArray(data) ? data : data?.runs || [];
      } catch {
        const allRuns = await getRuns();
        list = allRuns.filter(
          (r) => r.status === "spec_ready" || r.status === "confirming" || r.status === "awaiting_approval"
        );
      }
      setRuns(list);
    } catch (err) {
      addToast(err.message || "Failed to load pending approvals.", "error");
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    fetchPending();
    const interval = setInterval(fetchPending, 15000);
    return () => clearInterval(interval);
  }, [fetchPending]);

  async function handleApprove(runId) {
    setApproving(runId);
    try {
      await approveRun(runId);
      addToast("Build approved. Pipeline resuming.", "success");
      setConfirmRun(null);
      // Remove from list optimistically, then refresh
      setRuns((prev) => prev.filter((r) => (r.run_id || r.id) !== runId));
      setTimeout(fetchPending, 2000);
    } catch (err) {
      addToast(err.message || "Approval failed.", "error");
    } finally {
      setApproving(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-['Bebas_Neue'] text-3xl text-white tracking-widest">Approvals</h1>
          <p className="text-gray-500 text-sm mt-1">
            {runs.length} build{runs.length !== 1 ? "s" : ""} awaiting your review
          </p>
        </div>
        <button
          onClick={fetchPending}
          className="rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm flex items-center gap-2"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h5M20 20v-5h-5M4 9a9 9 0 0115 0M20 15a9 9 0 01-15 0" />
          </svg>
          Refresh
        </button>
      </div>

      {runs.length === 0 ? (
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-12 text-center">
          <div className="w-12 h-12 rounded-xl bg-emerald-900/30 border border-emerald-800/50 flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <p className="text-gray-400 text-sm font-medium">All clear</p>
          <p className="text-gray-600 text-xs mt-1">No builds pending approval right now.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {runs.map((run) => (
            <div
              key={run.run_id ?? run.id}
              className="rounded-xl border border-amber-900/40 bg-gray-900 p-5 flex flex-col sm:flex-row sm:items-center gap-4"
            >
              <div className="flex-1 min-w-0 space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-amber-500 flex-shrink-0 animate-pulse" />
                  <p className="text-sm font-medium text-white truncate">{run.title || run.run_id || run.id}</p>
                </div>
                {run.spec_summary && (
                  <p className="text-xs text-gray-500 line-clamp-2 ml-4">{run.spec_summary}</p>
                )}
                <div className="flex items-center gap-3 ml-4 text-xs text-gray-600 font-['IBM_Plex_Mono']">
                  <span>{run.run_id || run.id}</span>
                  <span>{timeAgo(run.created_at)}</span>
                </div>
              </div>

              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={() => navigate(`/runs/${run.run_id || run.id}`)}
                  className="rounded-lg font-medium px-4 py-2 transition-all duration-200 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs"
                >
                  Review Spec
                </button>
                <button
                  onClick={() => setConfirmRun(run)}
                  disabled={approving === run.run_id || run.id}
                  className="rounded-lg font-medium px-4 py-2 transition-all duration-200 bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white text-xs flex items-center gap-1.5"
                >
                  {approving === run.run_id || run.id ? (
                    <>
                      <div className="w-3 h-3 border border-white/40 border-t-white rounded-full animate-spin" />
                      Approving...
                    </>
                  ) : (
                    "Approve"
                  )}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <ConfirmModal
        isOpen={!!confirmRun}
        title="Approve Build"
        message={`Approve "${confirmRun?.title || confirmRun?.run_id || confirmRun?.id}"? The pipeline will resume and generate the full codebase.`}
        confirmText="Approve"
        cancelText="Cancel"
        onConfirm={() => handleApprove(confirmRun?.run_id || confirmRun?.id)}
        onCancel={() => setConfirmRun(null)}
      />
    </div>
  );
}
