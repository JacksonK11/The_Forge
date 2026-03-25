import { useState, useEffect, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { getRun, executeIncrementalChange } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

const STATUS_CONFIG = {
  queued: { label: "Queued", color: "bg-gray-700 text-gray-300" },
  planning: { label: "Planning", color: "bg-blue-900 text-blue-300" },
  ready: { label: "Ready to Execute", color: "bg-amber-900 text-amber-300" },
  executing: { label: "Executing", color: "bg-indigo-900 text-indigo-300" },
  complete: { label: "Complete", color: "bg-emerald-900 text-emerald-300" },
  failed: { label: "Failed", color: "bg-red-900 text-red-300" },
};

export default function UpgradeStatus() {
  const { runId } = useParams();
  const { addToast } = useToast();
  const [run, setRun] = useState(null);
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);

  const fetchRun = useCallback(async () => {
    try {
      const data = await getRun(runId);
      setRun(data);
    } catch (err) {
      addToast(err.message || "Failed to load upgrade status.", "error");
    } finally {
      setLoading(false);
    }
  }, [runId, addToast]);

  useEffect(() => {
    fetchRun();
    const interval = setInterval(fetchRun, 5000);
    return () => clearInterval(interval);
  }, [fetchRun]);

  async function handleExecute() {
    setExecuting(true);
    try {
      await executeIncrementalChange(runId);
      addToast("Execution started.", "success");
      fetchRun();
    } catch (err) {
      addToast(err.message || "Failed to execute upgrade.", "error");
    } finally {
      setExecuting(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!run) {
    return (
      <div className="p-6">
        <p className="text-gray-500 text-sm">Upgrade run not found.</p>
        <Link to="/upgrade" className="text-purple-400 text-sm hover:text-purple-300 mt-2 inline-block">
          Back to Upgrade Agent
        </Link>
      </div>
    );
  }

  const statusCfg = STATUS_CONFIG[run.status] || { label: run.status, color: "bg-gray-700 text-gray-300" };

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-4 flex items-center gap-2">
        <Link to="/upgrade" className="text-gray-600 hover:text-gray-400 transition-colors">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </Link>
        <h1 className="font-['Bebas_Neue'] text-2xl text-white tracking-widest">Upgrade Status</h1>
      </div>

      <div className="rounded-xl border border-gray-800 bg-gray-900 p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-white">{run.title || run.agent_id || runId}</p>
            <p className="text-xs text-gray-500 font-['IBM_Plex_Mono'] mt-0.5">{runId}</p>
          </div>
          <span className={`text-xs px-2.5 py-1 rounded-full font-medium flex-shrink-0 ${statusCfg.color}`}>
            {statusCfg.label}
          </span>
        </div>

        {run.change_description && (
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-widest mb-1">Change Description</p>
            <p className="text-sm text-gray-300">{run.change_description}</p>
          </div>
        )}

        {run.plan && (
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-widest mb-2">Plan</p>
            <pre className="font-['IBM_Plex_Mono'] text-xs text-gray-300 bg-gray-950 rounded-lg p-4 overflow-x-auto whitespace-pre-wrap">
              {typeof run.plan === "string" ? run.plan : JSON.stringify(run.plan, null, 2)}
            </pre>
          </div>
        )}

        {run.status === "ready" && (
          <button
            onClick={handleExecute}
            disabled={executing}
            className="w-full rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white text-sm flex items-center justify-center gap-2"
          >
            {executing ? (
              <>
                <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                Executing...
              </>
            ) : (
              "Execute Upgrade"
            )}
          </button>
        )}

        {run.status === "complete" && (
          <Link
            to={`/runs/${runId}`}
            className="block w-full text-center rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-emerald-700 hover:bg-emerald-600 text-white text-sm"
          >
            View Results
          </Link>
        )}
      </div>
    </div>
  );
}
