import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { getRuns } from "../api.js";

const ACTIVE_STATUSES = new Set(["queued", "validating", "parsing", "architecting", "generating", "packaging"]);

const STATUS_CONFIG = {
  queued:      { label: "Queued",         tag: "tag-gray",   icon: "⏳" },
  validating:  { label: "Validating",     tag: "tag-purple", icon: "🔍" },
  parsing:     { label: "Parsing",        tag: "tag-purple", icon: "📖" },
  architecting:{ label: "Architecting",   tag: "tag-violet", icon: "🗺" },
  generating:  { label: "Generating",     tag: "tag-cyan",   icon: "⚡" },
  packaging:   { label: "Packaging",      tag: "tag-green",  icon: "📦" },
};

function timeAgo(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export default function Active() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const all = await getRuns();
        setRuns((all || []).filter((r) => ACTIVE_STATUSES.has(r.status)));
      } catch (err) {
        console.error("Active fetch failed:", err);
      } finally {
        setLoading(false);
      }
    }
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <>
      <div className="sec-title">Active</div>
      <div className="sec-sub">Builds currently in the pipeline · <span>auto-refreshes every 5s</span></div>

      {loading ? (
        <div style={{ color: "var(--t3)", fontFamily: "var(--fm)", fontSize: 11, padding: "40px 0", textAlign: "center" }}>Loading...</div>
      ) : runs.length === 0 ? (
        <div className="ddd-card" style={{ textAlign: "center", padding: "48px" }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>😴</div>
          <div style={{ fontFamily: "var(--fd)", fontSize: 28, color: "var(--t2)", marginBottom: 8 }}>Pipeline Idle</div>
          <div style={{ fontFamily: "var(--fm)", fontSize: 11, color: "var(--t3)", marginBottom: 16 }}>No builds running right now.</div>
          <Link to="/build" className="ddd-btn btn-purple btn-sm" style={{ display: "inline-flex" }}>+ START A BUILD</Link>
        </div>
      ) : (
        <>
          <div className="g4 mb24">
            {Object.entries(STATUS_CONFIG).map(([status, cfg]) => {
              const count = runs.filter((r) => r.status === status).length;
              return (
                <div key={status} className={`ddd-card ddd-kpi${count > 0 ? " purple" : ""}`}>
                  <div className="kpi-label">{cfg.icon} {cfg.label}</div>
                  <div className={`kpi-value${count > 0 ? " purple" : ""}`}>{count}</div>
                </div>
              );
            })}
          </div>

          <div className="gcol">
            {runs.map((run) => {
              const cfg = STATUS_CONFIG[run.status] || { label: run.status, tag: "tag-gray", icon: "⚙" };
              const progressPct = run.file_count > 0
                ? Math.round((run.files_complete / run.file_count) * 100)
                : 0;
              return (
                <Link
                  key={run.run_id}
                  to={`/runs/${run.run_id}`}
                  className="ddd-card"
                  style={{ textDecoration: "none", display: "block" }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontSize: 18 }}>{cfg.icon}</span>
                      <div>
                        <div style={{ fontWeight: 600, color: "var(--t1)", fontSize: 13 }}>{run.title}</div>
                        <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>{run.run_id.slice(0, 12)}… · {timeAgo(run.created_at)}</div>
                      </div>
                    </div>
                    <span className={`ddd-tag ${cfg.tag}`}>{cfg.label.toUpperCase()}</span>
                  </div>

                  {run.status === "generating" && run.file_count > 0 && (
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginBottom: 4 }}>
                        <span>{run.files_complete}/{run.file_count} files</span>
                        <span>{progressPct}%</span>
                      </div>
                      <div className="ddd-prog">
                        <div className="ddd-prog-fill" style={{ width: `${progressPct}%`, background: "linear-gradient(90deg, var(--p), var(--p2))" }} />
                      </div>
                    </div>
                  )}
                </Link>
              );
            })}
          </div>
        </>
      )}
    </>
  );
}
