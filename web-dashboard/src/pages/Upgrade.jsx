import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { planIncrementalChange } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

export default function Upgrade() {
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
      navigate(`/runs/${result.run_id || result.id}`);
    } catch (err) {
      addToast(err.message || "Failed to plan incremental change.", "error");
      setSubmitting(false);
    }
  }

  return (
    <>
      <div className="sec-title">Upgrade</div>
      <div className="sec-sub">Plan and execute an incremental change to an <span>existing deployed agent</span></div>

      <div className="g2" style={{ gridTemplateColumns: "1.6fr 1fr" }}>
        <form onSubmit={handleSubmit}>
          <div className="ddd-card">
            <div className="card-title">Incremental Change Request</div>

            <div className="form-row">
              <label className="ddd-lbl">Agent ID *</label>
              <input
                className="ddd-input"
                type="text"
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                placeholder="e.g. buildright-ai-agent or run UUID"
                required
              />
              <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginTop: 4 }}>
                The run_id or agent identifier from the original build
              </div>
            </div>

            <div className="form-row">
              <label className="ddd-lbl">Change Description *</label>
              <textarea
                className="ddd-textarea"
                value={changeDescription}
                onChange={(e) => setChangeDescription(e.target.value)}
                placeholder="Describe what you want to change or add. Be specific about which files or features should be modified, and what the expected behaviour should be after the change..."
                rows={12}
              />
              <div style={{ textAlign: "right", fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginTop: 4 }}>
                {changeDescription.length} chars
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="ddd-btn btn-violet"
              style={{ width: "100%", justifyContent: "center", padding: "12px 16px", fontSize: 12, background: "var(--violet)", color: "white" }}
            >
              {submitting ? "⚡ PLANNING CHANGE..." : "🔧 PLAN UPGRADE →"}
            </button>
          </div>
        </form>

        <div className="gcol">
          <div className="ddd-card violet">
            <div className="card-title">How Upgrades Work</div>
            {[
              ["1. Plan", "AI analyses the existing codebase and your change request"],
              ["2. Spec", "Generates a targeted change spec — review before executing"],
              ["3. Execute", "Applies changes to specific files only — minimal blast radius"],
              ["4. Review", "Download the modified files and deploy the delta"],
            ].map(([step, desc]) => (
              <div key={step} className="stat-row">
                <span style={{ fontFamily: "var(--fm)", fontSize: 11, color: "var(--violet)", fontWeight: 700 }}>{step}</span>
                <span style={{ fontSize: 11, color: "var(--t2)", maxWidth: 160, textAlign: "right" }}>{desc}</span>
              </div>
            ))}
          </div>

          <div className="ddd-card">
            <div className="card-title">Good Change Requests</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {[
                "Add a new API endpoint for bulk lead import",
                "Add pgvector similarity search to the KB retriever",
                "Add Telegram notification when a build completes",
                "Change the dashboard colour scheme to match brand",
                "Add rate limiting to the /forge/submit endpoint",
              ].map((ex) => (
                <div
                  key={ex}
                  onClick={() => setChangeDescription(ex)}
                  style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", padding: "6px 10px", background: "var(--bg4)", borderRadius: 4, cursor: "pointer", border: "1px solid var(--line2)", transition: "border-color 0.15s" }}
                  onMouseEnter={(e) => e.currentTarget.style.borderColor = "var(--violet)"}
                  onMouseLeave={(e) => e.currentTarget.style.borderColor = "var(--line2)"}
                >
                  {ex}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
