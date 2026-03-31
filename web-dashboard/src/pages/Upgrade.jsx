import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { planIncrementalChange, getTemplates } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

export default function Upgrade() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { addToast } = useToast();
  const [agentId, setAgentId] = useState(searchParams.get("run_id") || "");
  const [changeText, setChangeText] = useState(searchParams.get("description") || "");
  const [files, setFiles] = useState([]);
  const [inputMode, setInputMode] = useState("text");
  const [repoName, setRepoName] = useState("");
  const [pushToGithub, setPushToGithub] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!agentId.trim()) { addToast("Agent ID is required.", "warning"); return; }
    if (inputMode === "text" && changeText.trim().length < 20) {
      addToast("Change description must be at least 20 characters.", "warning"); return;
    }
    setSubmitting(true);
    try {
      const result = await planIncrementalChange({
        run_id: agentId.trim(),
        action: "modify",
        description: inputMode === "text" ? changeText.trim() : "",
        repo_name: repoName.trim(),
        push_to_github: pushToGithub,
        files: inputMode === "file" ? files : [],
      });
      addToast("Upgrade plan created — pipeline starting.", "success");
      navigate(`/runs/${result.run_id || result.id}`);
    } catch (err) {
      addToast(err.message || "Failed to plan upgrade.", "error");
      setSubmitting(false);
    }
  }

  return (
    <>
      <div className="sec-title">Upgrade</div>
      <div className="sec-sub">Describe a change → <span>targeted incremental update to an existing deployed agent</span></div>

      {/* Pre-filled from chat banner */}
      {searchParams.get("run_id") && (
        <div style={{ marginBottom: "1rem", padding: "0.75rem 1rem", background: "rgba(126,34,206,0.15)", border: "1px solid rgba(126,34,206,0.4)", borderRadius: "0.75rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span style={{ color: "#c084fc", fontSize: "0.875rem" }}>⚡ Pre-filled from Forge Assistant — review and submit when ready.</span>
        </div>
      )}

      {/* ── Form ── */}
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

            <div className="form-row" style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                onClick={() => setInputMode("text")}
                className={`ddd-btn ${inputMode === "text" ? "btn-purple" : "btn-ghost"}`}
                style={{ flex: 1, justifyContent: "center" }}
              >
                PASTE TEXT
              </button>
              <button
                type="button"
                onClick={() => setInputMode("file")}
                className={`ddd-btn ${inputMode === "file" ? "btn-purple" : "btn-ghost"}`}
                style={{ flex: 1, justifyContent: "center" }}
              >
                UPLOAD FILES
              </button>
            </div>

            {inputMode === "text" ? (
              <div className="form-row">
                <label className="ddd-lbl">Change Description *</label>
                <textarea
                  className="ddd-textarea"
                  value={changeText}
                  onChange={(e) => setChangeText(e.target.value)}
                  placeholder="Describe what you want to change or add. Be specific about which files or features should be modified, and what the expected behaviour should be after the change..."
                  rows={16}
                />
                <div style={{ textAlign: "right", fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginTop: 4 }}>
                  {changeText.length} chars
                </div>
              </div>
            ) : (
              <div className="form-row">
                <label className="ddd-lbl">Change Spec Files (.docx / .pdf / .txt)</label>
                <div
                  className="file-drop-zone"
                  onClick={() => document.getElementById("upgrade-file-input").click()}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => { e.preventDefault(); setFiles(Array.from(e.dataTransfer.files)); }}
                >
                  <div className="drop-zone-icon" style={{ fontSize: 32, marginBottom: 8 }}>📎</div>
                  <div className="drop-zone-text">
                    {files.length > 0 ? `${files.length} file${files.length !== 1 ? "s" : ""} selected` : "Drag & drop or click to select files"}
                  </div>
                  <div className="drop-zone-hint">.docx, .pdf, .txt, .html, or source code files</div>
                  <input
                    id="upgrade-file-input"
                    type="file"
                    multiple
                    accept=".docx,.pdf,.txt,.html,.py,.js,.jsx,.ts,.tsx,.md"
                    onChange={(e) => setFiles(Array.from(e.target.files))}
                    style={{ display: "none" }}
                  />
                </div>
              </div>
            )}

            <div className="form-row">
              <label className="ddd-lbl">GitHub Repo Name (optional)</label>
              <input
                className="ddd-input"
                type="text"
                value={repoName}
                onChange={(e) => setRepoName(e.target.value)}
                placeholder="e.g. buildright-ai-agent"
              />
            </div>

            <div className="form-row" style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <input
                type="checkbox"
                id="upgrade-push-github"
                checked={pushToGithub}
                onChange={(e) => setPushToGithub(e.target.checked)}
                style={{ accentColor: "var(--p)", width: 14, height: 14, cursor: "pointer" }}
              />
              <label htmlFor="upgrade-push-github" style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t2)", letterSpacing: "0.05em", cursor: "pointer" }}>
                PUSH TO GITHUB AFTER UPGRADE
              </label>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="ddd-btn btn-purple"
              style={{ width: "100%", justifyContent: "center", padding: "12px 16px", fontSize: 12, marginTop: 8 }}
            >
              {submitting ? "⚡ PLANNING UPGRADE..." : "🔧 PLAN UPGRADE →"}
            </button>
          </div>
        </form>

        {/* ── Sidebar info ── */}
        <div className="gcol">
          <div className="ddd-card">
            <div className="card-title">What Upgrades Can Change</div>
            {[
              ["API Endpoints", "Add, modify, or remove FastAPI routes"],
              ["Database Schema", "New tables, columns, pgvector fields"],
              ["Worker Logic", "RQ workers, pipeline nodes, schedulers"],
              ["Web Dashboard", "New pages, components, data views"],
              ["Intelligence Layer", "KB rules, meta-rules, evaluator criteria"],
              ["Integrations", "Webhooks, third-party APIs, Telegram"],
              ["Deployment", "Fly.io config, GitHub Actions, secrets"],
            ].map(([label, desc]) => (
              <div key={label} className="stat-row">
                <span className="stat-label">{label}</span>
                <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", textAlign: "right", maxWidth: 130 }}>{desc}</span>
              </div>
            ))}
          </div>

          <div className="ddd-card green">
            <div className="card-title">Upgrade Pipeline</div>
            <div className="ddd-flow" style={{ flexDirection: "column", gap: 6 }}>
              {["1. Parse Change Request", "2. Analyse Existing Code", "3. Confirm Change Spec", "4. Generate Delta Files", "5. Secrets Check", "6. Update README", "7. Package ZIP"].map((s) => (
                <div key={s} style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t2)", padding: "4px 0", borderBottom: "1px solid var(--line)" }}>{s}</div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
