import { useState, useEffect, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { getRun, getRunFiles, approveRun, getRunPackageBlob, getDeployStatus, triggerDownload, getRunReport, setRunSecrets, BASE_URL } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

const STATUS_CONFIG = {
  queued:      { label: "Queued",              tag: "tag-gray",   icon: "⏳" },
  validating:  { label: "Validating Blueprint",tag: "tag-purple", icon: "🔍" },
  parsing:     { label: "Parsing Blueprint",   tag: "tag-purple", icon: "📖" },
  confirming:  { label: "Awaiting Approval",   tag: "tag-amber",  icon: "✋" },
  architecting:{ label: "Mapping Architecture",tag: "tag-violet", icon: "🗺" },
  generating:  { label: "Generating Code",     tag: "tag-cyan",   icon: "⚡" },
  build_qa:    { label: "QA & Auto-Fix",       tag: "tag-violet", icon: "🎯" },
  packaging:   { label: "Packaging",           tag: "tag-cyan",   icon: "📦" },
  complete:    { label: "Complete",            tag: "tag-green",  icon: "✅" },
  failed:      { label: "Failed",              tag: "tag-red",    icon: "❌" },
  planning:    { label: "Planning",            tag: "tag-purple", icon: "🧠" },
  ready:       { label: "Ready to Execute",    tag: "tag-amber",  icon: "▶" },
  executing:   { label: "Executing",           tag: "tag-cyan",   icon: "⚡" },
};

const LAYER_NAMES = {
  1: "Database Schema",
  2: "Infrastructure",
  3: "Backend API",
  4: "Worker / Agent Logic",
  5: "Web Dashboard",
  6: "Deployment",
  7: "Documentation",
};

const ACTIVE_STATUSES = new Set(["queued", "validating", "parsing", "architecting", "generating", "packaging", "planning", "executing"]);

function BuildQAPanel({ qa, runId, title }) {
  const [copied, setCopied] = useState(false);
  const score = qa.total_score ?? 0;
  const passed = qa.passed;
  const scoreColor = score >= 95 ? "var(--green)" : score >= 85 ? "var(--amber)" : "var(--red)";
  const band = score >= 95 ? "PASS" : score >= 85 ? "GOOD" : score >= 70 ? "WARNING" : "POOR";
  const bandTag = score >= 95 ? "tag-green" : score >= 85 ? "tag-amber" : "tag-red";
  const categories = qa.categories ?? {};
  const issues = qa.issues ?? [];
  const critical = issues.filter((i) => i.severity === "critical");
  const warnings = issues.filter((i) => i.severity === "warning");

  function buildFixPrompt() {
    if (critical.length === 0) return "";
    const lines = critical.map((issue, i) => {
      const cat = (issue.category || "").toUpperCase();
      const fp = issue.file ? `${issue.file}: ` : "";
      const hint = issue.fix_hint ? ` — ${issue.fix_hint}` : "";
      return `${i + 1}. [${cat}] ${fp}${issue.description}${hint}`;
    });
    return (
      `Fix the following QA issues in this build (run_id: ${runId}, agent: ${title}):\n\n` +
      lines.join("\n") +
      `\n\nFix every issue listed above so the build scores 100/100.`
    );
  }

  function handleCopyPrompt() {
    const prompt = buildFixPrompt();
    if (!prompt) return;
    navigator.clipboard.writeText(prompt).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    });
  }

  const cats = [
    { key: "api",            label: "API Completeness",    max: 25 },
    { key: "wiring",         label: "Cross-System Wiring", max: 25 },
    { key: "intelligence",   label: "Intelligence Layer",  max: 25 },
    { key: "infrastructure", label: "Infrastructure",      max: 15 },
    { key: "code_quality",   label: "Code Quality",        max: 10 },
  ];

  return (
    <div className="ddd-card mb24" style={{ borderColor: passed ? "var(--green)" : score >= 85 ? "var(--amber)" : "var(--red)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div className="card-title">Build QA Score</div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {qa.score_history?.length > 1 && (
            <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>
              {qa.score_history.join(" → ")}
            </span>
          )}
          <span className={`ddd-tag ${bandTag}`}>{band}</span>
        </div>
      </div>

      {/* Big score */}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 8, marginBottom: 20 }}>
        <span style={{ fontFamily: "var(--fd)", fontSize: 64, lineHeight: 1, color: scoreColor }}>{score}</span>
        <span style={{ fontFamily: "var(--fd)", fontSize: 28, color: "var(--t3)", paddingBottom: 4 }}>/100</span>
        <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", paddingBottom: 8, marginLeft: 4 }}>
          {qa.iteration > 1 ? `after ${qa.iteration} QA iteration${qa.iteration !== 1 ? "s" : ""}` : ""}
        </span>
      </div>

      {/* Category bars */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
        {cats.map(({ key, label, max }) => {
          const val = categories[key]?.score ?? 0;
          const pct = Math.round((val / max) * 100);
          const barColor = val === max ? "var(--green)" : val >= max * 0.8 ? "var(--amber)" : "var(--red)";
          return (
            <div key={key}>
              <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--fm)", fontSize: 10, color: "var(--t2)", marginBottom: 4 }}>
                <span>{label}</span>
                <span style={{ color: barColor, fontWeight: 700 }}>{val}/{max}</span>
              </div>
              <div className="ddd-prog">
                <div className="ddd-prog-fill" style={{ width: `${pct}%`, background: barColor, transition: "width 0.4s ease" }} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Issues */}
      {critical.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--red)", letterSpacing: "0.08em", marginBottom: 6 }}>
            {critical.length} CRITICAL ISSUE{critical.length !== 1 ? "S" : ""} FOUND & FIXED
          </div>
          {critical.slice(0, 5).map((issue, i) => (
            <div key={i} style={{ padding: "6px 10px", background: "var(--bg4)", border: "1px solid var(--line2)", borderRadius: 4, marginBottom: 4 }}>
              <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t2)" }}>
                <span style={{ color: "var(--red)", marginRight: 6 }}>●</span>
                {issue.file && <span style={{ color: "var(--p2)", marginRight: 6 }}>{issue.file}</span>}
                {issue.description}
              </div>
            </div>
          ))}
          {critical.length > 5 && (
            <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", paddingLeft: 10 }}>
              +{critical.length - 5} more fixed
            </div>
          )}
        </div>
      )}
      {warnings.length > 0 && (
        <div style={{ marginTop: 8, fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>
          {warnings.length} warning{warnings.length !== 1 ? "s" : ""} noted
        </div>
      )}
      {critical.length === 0 && warnings.length === 0 && (
        <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--green)" }}>
          ✓ No issues found — build is clean across all categories
        </div>
      )}

      {/* Copy Fix Prompt button — only shown when there are remaining issues */}
      {critical.length > 0 && (
        <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--line2)" }}>
          <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginBottom: 8 }}>
            Paste this prompt into the Upgrade page or Claude Code to fix everything:
          </div>
          <button
            onClick={handleCopyPrompt}
            className="ddd-btn btn-purple"
            style={{ width: "100%", justifyContent: "center", padding: "10px 16px" }}
          >
            {copied ? "✓ COPIED TO CLIPBOARD" : `📋 COPY FIX PROMPT (${critical.length} issue${critical.length !== 1 ? "s" : ""})`}
          </button>
          <div style={{ marginTop: 8, fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>
            The prompt includes every issue, which file it's in, and exactly how to fix it.
            Paste into <b style={{ color: "var(--t2)" }}>Upgrade</b> with this run's ID, or drop directly into Claude Code.
          </div>
        </div>
      )}
    </div>
  );
}

function SecretsSetupPanel({ run }) {
  const envVars = run.spec_json?.environment_variables || [];
  const required = envVars.filter((v) => v.required !== false);
  const optional = envVars.filter((v) => v.required === false);
  const [values, setValues] = useState({});
  const [show, setShow] = useState({});
  const [saving, setSaving] = useState(false);
  const [applied, setApplied] = useState(false);
  const { addToast } = useToast();

  if (envVars.length === 0) return null;

  function setValue(name, val) {
    setValues((prev) => ({ ...prev, [name]: val }));
    if (applied) setApplied(false);
  }

  function toggleShow(name) {
    setShow((prev) => ({ ...prev, [name]: !prev[name] }));
  }

  async function handleApply() {
    const secrets = Object.fromEntries(
      Object.entries(values).filter(([, v]) => v && v.trim())
    );
    if (Object.keys(secrets).length === 0) {
      addToast("Enter at least one secret before applying.", "error");
      return;
    }
    setSaving(true);
    try {
      await setRunSecrets(run.run_id, secrets);
      setApplied(true);
      addToast(`${Object.keys(secrets).length} secret(s) applied to Fly.io ✓`, "success");
    } catch (err) {
      addToast(err.message || "Failed to apply secrets.", "error");
    } finally {
      setSaving(false);
    }
  }

  const filledCount = Object.values(values).filter((v) => v && v.trim()).length;
  const requiredFilled = required.filter((v) => values[v.name]?.trim()).length;

  function renderVar(v) {
    const filled = !!(values[v.name]?.trim());
    return (
      <div key={v.name} style={{ marginBottom: 14, padding: "12px 14px", background: "var(--bg4)", border: `1px solid ${filled ? "var(--green)" : "var(--line2)"}`, borderRadius: 8 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontFamily: "var(--fm)", fontSize: 11, color: "var(--t1)", fontWeight: 700 }}>{v.name}</span>
            {v.required !== false
              ? <span className="ddd-tag tag-red" style={{ fontSize: 9, padding: "1px 6px" }}>REQUIRED</span>
              : <span className="ddd-tag tag-gray" style={{ fontSize: 9, padding: "1px 6px" }}>OPTIONAL</span>
            }
            {filled && <span style={{ color: "var(--green)", fontSize: 12 }}>✓</span>}
          </div>
        </div>
        {v.description && (
          <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginBottom: 8, lineHeight: 1.5 }}>{v.description}</div>
        )}
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type={show[v.name] ? "text" : "password"}
            placeholder={v.example ? `e.g. ${v.example}` : "Enter value..."}
            value={values[v.name] || ""}
            onChange={(e) => setValue(v.name, e.target.value)}
            style={{ flex: 1, background: "var(--bg3)", border: "1px solid var(--line2)", borderRadius: 6, padding: "8px 12px", fontFamily: "var(--fm)", fontSize: 11, color: "var(--t1)", outline: "none" }}
          />
          <button
            onClick={() => toggleShow(v.name)}
            className="ddd-btn btn-ghost btn-sm"
            style={{ flexShrink: 0, padding: "8px 10px" }}
            title={show[v.name] ? "Hide" : "Show"}
          >
            {show[v.name] ? "🙈" : "👁"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="ddd-card mb24" style={{ borderColor: applied ? "var(--green)" : "var(--line)" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
        <div className="card-title">🔑 Secrets Setup</div>
        <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>
          {requiredFilled}/{required.length} required filled
        </span>
      </div>
      <div style={{ fontFamily: "var(--fm)", fontSize: 11, color: "var(--t2)", marginBottom: 20, lineHeight: 1.6 }}>
        Enter your API keys below. Click <b>Apply to Fly.io</b> and they are set on your live apps automatically — no terminal needed.
      </div>

      {required.length > 0 && (
        <>
          <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", letterSpacing: "0.08em", marginBottom: 10 }}>REQUIRED ACCOUNTS & KEYS</div>
          {required.map(renderVar)}
        </>
      )}

      {optional.length > 0 && (
        <>
          <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", letterSpacing: "0.08em", margin: "16px 0 10px" }}>OPTIONAL</div>
          {optional.map(renderVar)}
        </>
      )}

      <button
        onClick={handleApply}
        disabled={saving || filledCount === 0}
        className={`ddd-btn ${applied ? "btn-green" : "btn-purple"}`}
        style={{ width: "100%", justifyContent: "center", padding: "12px 16px", marginTop: 8, opacity: filledCount === 0 ? 0.5 : 1 }}
      >
        {saving ? "⏳ APPLYING TO FLY.IO..." : applied ? `✓ APPLIED ${filledCount} SECRET${filledCount !== 1 ? "S" : ""}` : `⚡ APPLY ${filledCount > 0 ? filledCount : ""} SECRET${filledCount !== 1 ? "S" : ""} TO FLY.IO`}
      </button>
      <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginTop: 8, textAlign: "center" }}>
        Values are sent directly to Fly.io and never stored in The Forge dashboard.
      </div>
    </div>
  );
}

export default function RunStatus() {
  const { runId } = useParams();
  const { addToast } = useToast();
  const [run, setRun] = useState(null);
  const [files, setFiles] = useState([]);
  const [deployStatus, setDeployStatus] = useState(null);
  const [runReport, setRunReport] = useState(null);
  const [approving, setApproving] = useState(false);
  const [expandedLayer, setExpandedLayer] = useState(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);

  const fetchRun = useCallback(async () => {
    try {
      const data = await getRun(runId);
      setRun(data);
      if (["generating", "complete", "packaging"].includes(data.status)) {
        const filesData = await getRunFiles(runId, false);
        setFiles(Array.isArray(filesData) ? filesData : filesData?.files || []);
      }
      if (data.status === "complete") {
        try {
          const ds = await getDeployStatus(runId);
          setDeployStatus(ds);
        } catch { /* non-critical */ }
        try {
          const report = await getRunReport(runId);
          setRunReport(report);
        } catch { /* non-critical */ }
      }
    } catch (err) {
      console.error("Failed to fetch run:", err);
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    fetchRun();
    const id = setInterval(() => {
      setRun((current) => {
        if (current && ACTIVE_STATUSES.has(current.status)) {
          fetchRun();
        }
        return current;
      });
    }, 4000);
    return () => clearInterval(id);
  }, [fetchRun]);

  async function handleApprove() {
    setApproving(true);
    try {
      await approveRun(runId);
      addToast("Build approved — pipeline resuming.", "success");
      await fetchRun();
    } catch (err) {
      addToast(err.message || "Approval failed.", "error");
    } finally {
      setApproving(false);
    }
  }

  async function handleDownload() {
    setDownloading(true);
    try {
      const blob = await getRunPackageBlob(runId);
      triggerDownload(blob, `${run?.title?.replace(/\s+/g, "-").toLowerCase() || runId}.zip`);
    } catch {
      // Fallback: direct link
      window.open(`${BASE_URL}/forge/runs/${runId}/package`, "_blank");
    } finally {
      setDownloading(false);
    }
  }

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: 300 }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ width: 32, height: 32, border: "2px solid var(--p)", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.7s linear infinite", margin: "0 auto 12px" }} />
          <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>Loading run...</span>
        </div>
      </div>
    );
  }

  if (!run) {
    return (
      <div style={{ textAlign: "center", padding: "48px 0" }}>
        <div style={{ fontFamily: "var(--fd)", fontSize: 36, color: "var(--red)", marginBottom: 12 }}>Run Not Found</div>
        <Link to="/history" className="ddd-btn btn-ghost btn-sm">← Back to History</Link>
      </div>
    );
  }

  const cfg = STATUS_CONFIG[run.status] || STATUS_CONFIG.queued;
  const progressPct = run.file_count > 0 ? Math.round((run.files_complete / run.file_count) * 100) : 0;
  const filesByLayer = files.reduce((acc, f) => {
    const k = f.layer; if (!acc[k]) acc[k] = []; acc[k].push(f); return acc;
  }, {});

  return (
    <>
      {/* ── Header ── */}
      <div style={{ marginBottom: 24 }}>
        <Link to="/history" style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", textDecoration: "none", letterSpacing: "0.08em", display: "inline-block", marginBottom: 8 }}>
          ← ALL BUILDS
        </Link>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
          <div>
            <div className="sec-title" style={{ fontSize: 40 }}>{run.title}</div>
            <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginTop: 2 }}>{runId}</div>
          </div>
          <span className={`ddd-tag ${cfg.tag}`} style={{ flexShrink: 0, marginTop: 8, padding: "4px 12px", fontSize: 11 }}>
            {cfg.icon} {cfg.label.toUpperCase()}
          </span>
        </div>
      </div>

      {/* ── Progress ── */}
      {run.status === "generating" && run.file_count > 0 && (
        <div className="ddd-card mb24 purple">
          <div className="card-title">Code Generation Progress</div>
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--fm)", fontSize: 12, marginBottom: 8 }}>
            <span style={{ color: "var(--t2)" }}>{run.files_complete}/{run.file_count} files</span>
            <span style={{ color: "var(--p2)", fontWeight: 700 }}>{progressPct}%</span>
          </div>
          <div className="ddd-prog">
            <div className="ddd-prog-fill" style={{ width: `${progressPct}%`, background: "linear-gradient(90deg, var(--p), var(--p2))" }} />
          </div>
          {run.files_failed > 0 && (
            <div style={{ marginTop: 8, fontFamily: "var(--fm)", fontSize: 10, color: "var(--red)" }}>
              {run.files_failed} file{run.files_failed !== 1 ? "s" : ""} failed
            </div>
          )}
        </div>
      )}

      {/* ── Error ── */}
      {run.error_message && (
        <div className="ddd-alert red mb24">
          <span className="alert-icon">❌</span>
          <div className="alert-body">
            <div className="alert-title">Build Error</div>
            <div className="alert-sub">{run.error_message}</div>
          </div>
        </div>
      )}

      {/* ── Spec approval ── */}
      {(run.status === "confirming" || run.status === "spec_ready") && (
        <div className="ddd-card amber mb24">
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontFamily: "var(--fd)", fontSize: 28, color: "var(--amber)", marginBottom: 4 }}>Spec Ready — Review Before Building</div>
            <div style={{ fontSize: 12, color: "var(--t2)" }}>The Forge has parsed your blueprint. Review the plan below, then approve to start code generation.</div>
          </div>

          {run.spec_json && (
            <>
              <div className="g4 mb24">
                {[
                  ["Files",    run.spec_json.file_list?.length    ?? 0],
                  ["Services", run.spec_json.fly_services?.length ?? 0],
                  ["Tables",   run.spec_json.database_tables?.length ?? 0],
                  ["Routes",   run.spec_json.api_routes?.length   ?? 0],
                ].map(([label, value]) => (
                  <div key={label} className="ddd-card ddd-kpi">
                    <div className="kpi-label">{label}</div>
                    <div className="kpi-value purple">{value}</div>
                  </div>
                ))}
              </div>

              {run.spec_json.fly_services?.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <div className="card-title">Fly.io Services</div>
                  {run.spec_json.fly_services.map((s) => (
                    <div key={s.name} className="stat-row">
                      <span style={{ fontFamily: "var(--fm)", fontSize: 11 }}>{s.name}</span>
                      <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>{s.machine} · {s.memory}</span>
                    </div>
                  ))}
                </div>
              )}

              {run.spec_json.database_tables?.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <div className="card-title">Database Tables</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {run.spec_json.database_tables.map((t) => (
                      <span key={t.name} className="ddd-tag tag-gray" style={{ fontFamily: "var(--fm)", fontSize: 10 }}>{t.name}</span>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          <div style={{ display: "flex", gap: 12, marginTop: 8 }}>
            <button
              onClick={handleApprove}
              disabled={approving}
              className="ddd-btn btn-green"
              style={{ flex: 1, justifyContent: "center", padding: "12px 16px" }}
            >
              {approving ? "⏳ STARTING..." : "✓ APPROVE & BUILD"}
            </button>
            <Link to="/build" className="ddd-btn btn-ghost" style={{ padding: "12px 24px" }}>
              EDIT BLUEPRINT
            </Link>
          </div>
        </div>
      )}

      {/* ── Download ── */}
      {run.status === "complete" && run.package_ready && (
        <div className="ddd-card green mb24">
          <div style={{ fontFamily: "var(--fd)", fontSize: 28, color: "var(--green)", marginBottom: 4 }}>Build Complete</div>
          <div style={{ fontSize: 12, color: "var(--t2)", marginBottom: 20 }}>
            {run.files_complete} files generated{run.files_failed > 0 ? ` · ${run.files_failed} failed` : ""}. Download the ZIP, push to GitHub, run FLY_SECRETS.txt commands, and your agent is live.
          </div>

          {/* ── Links row ── */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 20 }}>
            {/* GitHub link */}
            {(deployStatus?.github_repo_url || run.github_repo_url) && (
              <a
                href={deployStatus?.github_repo_url || run.github_repo_url}
                target="_blank"
                rel="noopener noreferrer"
                className="ddd-btn btn-ghost"
                style={{ padding: "10px 18px", display: "inline-flex", alignItems: "center", gap: 8, textDecoration: "none" }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
                GITHUB REPO
              </a>
            )}

            {/* Fly.io webapp link — constructed from agent_slug or repo_name */}
            {(deployStatus?.agent_slug || run.repo_name) && (
              <a
                href={`https://${deployStatus?.agent_slug || run.repo_name}-api.fly.dev`}
                target="_blank"
                rel="noopener noreferrer"
                className="ddd-btn btn-ghost"
                style={{ padding: "10px 18px", display: "inline-flex", alignItems: "center", gap: 8, textDecoration: "none" }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                LIVE WEBAPP
              </a>
            )}

            {/* Package download */}
            <button
              onClick={handleDownload}
              disabled={downloading}
              className="ddd-btn btn-green"
              style={{ padding: "10px 18px" }}
            >
              {downloading ? "⏳ PREPARING..." : "⬇ DOWNLOAD .ZIP"}
            </button>
          </div>

          {/* ── Link display cards ── */}
          {(deployStatus?.github_repo_url || run.github_repo_url) && (
            <div style={{ background: "var(--bg4)", border: "1px solid var(--line2)", borderRadius: 8, padding: "12px 16px", marginBottom: 8 }}>
              <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginBottom: 4, letterSpacing: "0.08em" }}>GITHUB REPOSITORY</div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                <span style={{ fontFamily: "var(--fm)", fontSize: 12, color: "var(--p2)", wordBreak: "break-all" }}>
                  {deployStatus?.github_repo_url || run.github_repo_url}
                </span>
                <button
                  onClick={() => navigator.clipboard.writeText(deployStatus?.github_repo_url || run.github_repo_url).then(() => addToast("Copied!", "success"))}
                  className="ddd-btn btn-ghost btn-sm"
                  style={{ flexShrink: 0 }}
                >
                  COPY
                </button>
              </div>
            </div>
          )}

          {(deployStatus?.agent_slug || run.repo_name) && (
            <div style={{ background: "var(--bg4)", border: "1px solid var(--line2)", borderRadius: 8, padding: "12px 16px" }}>
              <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginBottom: 4, letterSpacing: "0.08em" }}>LIVE WEBAPP URL (after deploying to Fly.io)</div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                <span style={{ fontFamily: "var(--fm)", fontSize: 12, color: "var(--green)", wordBreak: "break-all" }}>
                  {`https://${deployStatus?.agent_slug || run.repo_name}-api.fly.dev`}
                </span>
                <button
                  onClick={() => navigator.clipboard.writeText(`https://${deployStatus?.agent_slug || run.repo_name}-api.fly.dev`).then(() => addToast("Copied!", "success"))}
                  className="ddd-btn btn-ghost btn-sm"
                  style={{ flexShrink: 0 }}
                >
                  COPY
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Secrets Setup ── */}
      {run.status === "complete" && <SecretsSetupPanel run={run} />}

      {/* ── Build QA Score ── */}
      {runReport?.build_qa && (
        <BuildQAPanel qa={runReport.build_qa} runId={runId} title={run.title} />
      )}

      {/* ── File tree ── */}
      {files.length > 0 && (
        <div className="ddd-card">
          <div className="card-title">Generated Files — {files.length} total</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {Object.entries(filesByLayer)
              .sort(([a], [b]) => Number(a) - Number(b))
              .map(([layer, layerFiles]) => (
                <div key={layer} style={{ border: "1px solid var(--line2)", borderRadius: 6, overflow: "hidden" }}>
                  <button
                    onClick={() => setExpandedLayer(expandedLayer === layer ? null : layer)}
                    style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", background: "var(--bg4)", cursor: "pointer", border: "none", color: "var(--t1)" }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>L{layer}</span>
                      <span style={{ fontWeight: 600, fontSize: 12 }}>{LAYER_NAMES[layer] || `Layer ${layer}`}</span>
                      <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>
                        {layerFiles.filter((f) => f.status === "complete").length}/{layerFiles.length}
                      </span>
                    </div>
                    <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>{expandedLayer === layer ? "▲" : "▼"}</span>
                  </button>
                  {expandedLayer === layer && (
                    <div>
                      {layerFiles.map((f) => (
                        <div key={f.file_id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 14px", borderTop: "1px solid var(--line)", background: "var(--bg3)" }}>
                          <span style={{ fontFamily: "var(--fm)", fontSize: 11, color: "var(--t2)" }}>{f.file_path}</span>
                          <span className={`ddd-tag ${f.status === "complete" ? "tag-green" : f.status === "failed" ? "tag-red" : f.status === "generating" ? "tag-cyan" : "tag-gray"}`}>
                            {f.status}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
          </div>
        </div>
      )}
    </>
  );
}
