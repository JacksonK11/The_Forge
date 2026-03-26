import { useState, useEffect, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { getRun, getRunFiles, approveRun, getRunPackageBlob, getDeployStatus, triggerDownload, BASE_URL } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

const STATUS_CONFIG = {
  queued:      { label: "Queued",              tag: "tag-gray",   icon: "⏳" },
  validating:  { label: "Validating Blueprint",tag: "tag-purple", icon: "🔍" },
  parsing:     { label: "Parsing Blueprint",   tag: "tag-purple", icon: "📖" },
  confirming:  { label: "Awaiting Approval",   tag: "tag-amber",  icon: "✋" },
  architecting:{ label: "Mapping Architecture",tag: "tag-violet", icon: "🗺" },
  generating:  { label: "Generating Code",     tag: "tag-cyan",   icon: "⚡" },
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

export default function RunStatus() {
  const { runId } = useParams();
  const { addToast } = useToast();
  const [run, setRun] = useState(null);
  const [files, setFiles] = useState([]);
  const [deployStatus, setDeployStatus] = useState(null);
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
