import { useState, useEffect, useCallback } from "react";
import { getAgents, getAgentHealth, restartAgent, submitFeedback, getAgentRegistry } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";
import ConfirmModal from "../components/ConfirmModal.jsx";

function StatusDot({ status }) {
  const cls =
    status === "healthy" || status === "running"
      ? "bg-emerald-500 animate-pulse"
      : status === "degraded" || status === "warning"
      ? "bg-amber-500"
      : "bg-red-500";
  return <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${cls}`} />;
}

export default function MyAgents() {
  const { addToast } = useToast();
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [confirmRestart, setConfirmRestart] = useState(null);
  const [feedbackOpen, setFeedbackOpen] = useState(null);
  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackRating, setFeedbackRating] = useState(5);
  const [submittingFeedback, setSubmittingFeedback] = useState(false);
  const [restarting, setRestarting] = useState(null);

  const fetchAgents = useCallback(async () => {
    try {
      const [agentsData, registry] = await Promise.allSettled([getAgents(), getAgentRegistry()]);
      const list =
        agentsData.status === "fulfilled"
          ? Array.isArray(agentsData.value)
            ? agentsData.value
            : agentsData.value?.agents || []
          : [];
      setAgents(list);
    } catch {
      // silent fail — show empty state
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAgents();
    const interval = setInterval(fetchAgents, 30000);
    return () => clearInterval(interval);
  }, [fetchAgents]);

  async function handleRestart(agentId) {
    setRestarting(agentId);
    try {
      await restartAgent(agentId);
      addToast(`Agent ${agentId} restart triggered.`, "success");
      setTimeout(fetchAgents, 2000);
    } catch (err) {
      addToast(err.message || "Failed to restart agent.", "error");
    } finally {
      setRestarting(null);
      setConfirmRestart(null);
    }
  }

  async function handleFeedbackSubmit() {
    if (!feedbackText.trim()) {
      addToast("Feedback message is required.", "warning");
      return;
    }
    setSubmittingFeedback(true);
    try {
      await submitFeedback({
        agent_id: feedbackOpen,
        message: feedbackText.trim(),
        rating: feedbackRating,
      });
      addToast("Feedback submitted.", "success");
      setFeedbackOpen(null);
      setFeedbackText("");
      setFeedbackRating(5);
    } catch (err) {
      addToast(err.message || "Failed to submit feedback.", "error");
    } finally {
      setSubmittingFeedback(false);
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
          <h1 className="font-['Bebas_Neue'] text-3xl text-white tracking-widest">My Agents</h1>
          <p className="text-gray-500 text-sm mt-1">
            {agents.length} agent{agents.length !== 1 ? "s" : ""} registered
          </p>
        </div>
        <button
          onClick={fetchAgents}
          className="rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm flex items-center gap-2"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h5M20 20v-5h-5M4 9a9 9 0 0115 0M20 15a9 9 0 01-15 0" />
          </svg>
          Refresh
        </button>
      </div>

      {agents.length === 0 ? (
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-12 text-center">
          <div className="w-12 h-12 rounded-xl bg-gray-800 border border-gray-700 flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          </div>
          <p className="text-gray-500 text-sm">No agents registered yet.</p>
          <p className="text-gray-600 text-xs mt-1">Build your first agent to see it here.</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {agents.map((agent) => (
            <div key={agent.id || agent.agent_id} className="rounded-xl border border-gray-800 bg-gray-900 p-5 flex flex-col gap-3">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <StatusDot status={agent.status || agent.health} />
                  <p className="text-sm font-medium text-white truncate">{agent.name || agent.id || agent.agent_id}</p>
                </div>
                <span className="text-xs px-2 py-0.5 rounded-full bg-gray-800 text-gray-400 flex-shrink-0 capitalize">
                  {agent.type || agent.agent_type || "agent"}
                </span>
              </div>

              {agent.description && (
                <p className="text-xs text-gray-500 line-clamp-2">{agent.description}</p>
              )}

              <div className="flex items-center gap-2 flex-wrap text-xs text-gray-600 font-['IBM_Plex_Mono']">
                {agent.version && <span>v{agent.version}</span>}
                {agent.last_run && <span>Last run: {new Date(agent.last_run).toLocaleDateString()}</span>}
              </div>

              <div className="flex items-center gap-2 mt-auto pt-1">
                <button
                  onClick={() => setFeedbackOpen(agent.id || agent.agent_id)}
                  className="flex-1 rounded-lg font-medium px-3 py-2 transition-all duration-200 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs"
                >
                  Feedback
                </button>
                <button
                  onClick={() => setConfirmRestart(agent.id || agent.agent_id)}
                  disabled={restarting === (agent.id || agent.agent_id)}
                  className="flex-1 rounded-lg font-medium px-3 py-2 transition-all duration-200 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs disabled:opacity-50"
                >
                  {restarting === (agent.id || agent.agent_id) ? "Restarting..." : "Restart"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Restart confirmation */}
      <ConfirmModal
        isOpen={!!confirmRestart}
        title="Restart Agent"
        message={`Restart agent "${confirmRestart}"? Active jobs may be interrupted.`}
        confirmText="Restart"
        cancelText="Cancel"
        danger
        onConfirm={() => handleRestart(confirmRestart)}
        onCancel={() => setConfirmRestart(null)}
      />

      {/* Feedback modal */}
      {feedbackOpen && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 max-w-sm w-full">
            <h3 className="font-['Bebas_Neue'] text-xl text-white tracking-widest mb-4">
              Agent Feedback
            </h3>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1.5 tracking-widest uppercase">
                  Rating (1–10)
                </label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={feedbackRating}
                  onChange={(e) => setFeedbackRating(Number(e.target.value))}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-gray-200 focus:outline-none focus:border-purple-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1.5 tracking-widest uppercase">
                  Notes
                </label>
                <textarea
                  value={feedbackText}
                  onChange={(e) => setFeedbackText(e.target.value)}
                  rows={4}
                  placeholder="What worked well? What needs improvement?"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500 resize-none"
                />
              </div>
            </div>
            <div className="flex gap-3 mt-5">
              <button
                onClick={() => { setFeedbackOpen(null); setFeedbackText(""); }}
                className="flex-1 rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm"
              >
                Cancel
              </button>
              <button
                onClick={handleFeedbackSubmit}
                disabled={submittingFeedback}
                className="flex-1 rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white text-sm"
              >
                {submittingFeedback ? "Submitting..." : "Submit"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
