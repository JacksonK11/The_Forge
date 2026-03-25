import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { submitBuildWithFiles, getTemplates } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

export default function Build() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [title, setTitle] = useState("");
  const [blueprintText, setBlueprintText] = useState("");
  const [files, setFiles] = useState([]);
  const [inputMode, setInputMode] = useState("text");
  const [templates, setTemplates] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [pushToGithub, setPushToGithub] = useState(false);
  const [repoName, setRepoName] = useState("");

  useEffect(() => {
    getTemplates()
      .then((data) => setTemplates(Array.isArray(data) ? data.slice(0, 6) : []))
      .catch(() => {});
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!title.trim()) { addToast("Agent name is required.", "warning"); return; }
    if (inputMode === "text" && blueprintText.trim().length < 50) {
      addToast("Blueprint must be at least 50 characters.", "warning"); return;
    }
    setSubmitting(true);
    try {
      const result = await submitBuildWithFiles({
        title: title.trim(),
        blueprint_text: inputMode === "text" ? blueprintText.trim() : "",
        repo_name: repoName.trim(),
        push_to_github: pushToGithub,
        files: inputMode === "file" ? files : [],
      });
      addToast("Build submitted — pipeline starting.", "success");
      navigate(`/runs/${result.run_id}`);
    } catch (err) {
      addToast(err.message || "Submission failed.", "error");
      setSubmitting(false);
    }
  }

  return (
    <>
      <div className="sec-title">Build</div>
      <div className="sec-sub">Submit a blueprint document → <span>get a complete deployable codebase in 15–25 minutes</span></div>

      {/* ── Templates ── */}
      {templates.length > 0 && (
        <div className="mb24">
          <div className="card-title">Start from a Template</div>
          <div className="g3">
            {templates.map((t) => (
              <button
                key={t.id}
                onClick={() => { setTitle(t.name || t.title || ""); setBlueprintText(t.blueprint_text || t.content || ""); setInputMode("text"); }}
                className="ddd-card"
                style={{ cursor: "pointer", textAlign: "left", border: "1px solid var(--line2)", background: "var(--bg3)" }}
              >
                <div style={{ fontFamily: "var(--fm)", fontSize: 11, fontWeight: 700, color: "var(--p2)", marginBottom: 4 }}>
                  {t.name || t.title}
                </div>
                <div style={{ fontSize: 11, color: "var(--t3)", overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
                  {t.description}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── Form ── */}
      <div className="g2" style={{ gridTemplateColumns: "1.6fr 1fr" }}>
        <form onSubmit={handleSubmit}>
          <div className="ddd-card">
            <div className="card-title">Blueprint Submission</div>

            <div className="form-row">
              <label className="ddd-lbl">Agent Name *</label>
              <input
                className="ddd-input"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. BuildRight AI Agent"
                required
              />
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
                <label className="ddd-lbl">Blueprint Document *</label>
                <textarea
                  className="ddd-textarea"
                  value={blueprintText}
                  onChange={(e) => setBlueprintText(e.target.value)}
                  placeholder="Paste your blueprint here. Describe what the agent does, its database schema, API routes, dashboard screens, and required services..."
                  rows={16}
                />
                <div style={{ textAlign: "right", fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginTop: 4 }}>
                  {blueprintText.length} chars
                </div>
              </div>
            ) : (
              <div className="form-row">
                <label className="ddd-lbl">Blueprint Files (.docx / .pdf / .txt)</label>
                <div
                  className="file-drop-zone"
                  onClick={() => document.getElementById("blueprint-file-input").click()}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => { e.preventDefault(); setFiles(Array.from(e.dataTransfer.files)); }}
                >
                  <div className="drop-zone-icon" style={{ fontSize: 32, marginBottom: 8 }}>📎</div>
                  <div className="drop-zone-text">
                    {files.length > 0 ? `${files.length} file${files.length !== 1 ? "s" : ""} selected` : "Drag & drop or click to select files"}
                  </div>
                  <div className="drop-zone-hint">.docx, .pdf, .txt, or source code files</div>
                  <input
                    id="blueprint-file-input"
                    type="file"
                    multiple
                    accept=".docx,.pdf,.txt,.py,.js,.jsx,.ts,.tsx,.md"
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
                id="push-github"
                checked={pushToGithub}
                onChange={(e) => setPushToGithub(e.target.checked)}
                style={{ accentColor: "var(--p)", width: 14, height: 14, cursor: "pointer" }}
              />
              <label htmlFor="push-github" style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t2)", letterSpacing: "0.05em", cursor: "pointer" }}>
                PUSH TO GITHUB AFTER BUILD
              </label>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="ddd-btn btn-purple"
              style={{ width: "100%", justifyContent: "center", padding: "12px 16px", fontSize: 12, marginTop: 8 }}
            >
              {submitting ? "⚡ STARTING PIPELINE..." : "⚒ START BUILD →"}
            </button>
          </div>
        </form>

        {/* ── Sidebar info ── */}
        <div className="gcol">
          <div className="ddd-card">
            <div className="card-title">What The Forge Builds</div>
            {[
              ["Database Schema", "SQLAlchemy models, migrations, pgvector"],
              ["Infrastructure", "Docker, docker-compose, requirements.txt"],
              ["Backend API", "FastAPI routes, middleware, auth, services"],
              ["Worker Logic", "RQ workers, pipeline nodes, schedulers"],
              ["Web Dashboard", "React + Vite + Tailwind SPA"],
              ["Deployment", "fly.toml, GitHub Actions CI/CD"],
              ["Documentation", "README, FLY_SECRETS.txt, .env.example"],
            ].map(([label, desc]) => (
              <div key={label} className="stat-row">
                <span className="stat-label">{label}</span>
                <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", textAlign: "right", maxWidth: 130 }}>{desc}</span>
              </div>
            ))}
          </div>

          <div className="ddd-card green">
            <div className="card-title">Pipeline Stages</div>
            <div className="ddd-flow" style={{ flexDirection: "column", gap: 6 }}>
              {["1. Parse Blueprint", "2. Confirm Spec", "3. Architecture", "4. Generate Code", "5. Secrets Setup", "6. README", "7. Package ZIP"].map((s) => (
                <div key={s} style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t2)", padding: "4px 0", borderBottom: "1px solid var(--line)" }}>{s}</div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
