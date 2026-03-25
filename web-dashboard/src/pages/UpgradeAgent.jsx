import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { planIncrementalChange } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

export default function UpgradeAgent() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [agentId, setAgentId] = useState("");
  const [changeDescription, setChangeDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!agentId.trim() || !changeDescription.trim()) {
      addToast("Agent ID and change description are required.", "warning");
      return;
    }
    setSubmitting(true);
    try {
      const result = await planIncrementalChange({
        agent_id: agentId.trim(),
        change_description: changeDescription.trim(),
      });
      addToast("Incremental change plan created.", "success");
      navigate(`/upgrade/${result.run_id || result.id}`);
    } catch (err) {
      addToast(err.message || "Failed to plan incremental change.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="font-['Bebas_Neue'] text-3xl text-white tracking-widest">Upgrade Agent</h1>
        <p className="text-gray-500 text-sm mt-1">
          Plan and execute an incremental change to an existing deployed agent.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-6 space-y-5">
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-2 tracking-widest uppercase">
              Agent ID
            </label>
            <input
              type="text"
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              placeholder="e.g. the-forge-api"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500 transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-400 mb-2 tracking-widest uppercase">
              Change Description
            </label>
            <textarea
              value={changeDescription}
              onChange={(e) => setChangeDescription(e.target.value)}
              placeholder="Describe what needs to change — new feature, bug fix, refactor..."
              rows={6}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500 transition-colors resize-none"
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm flex items-center justify-center gap-2"
        >
          {submitting ? (
            <>
              <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              Planning...
            </>
          ) : (
            "Plan Upgrade"
          )}
        </button>
      </form>
    </div>
  );
}
