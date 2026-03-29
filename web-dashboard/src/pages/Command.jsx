import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { getForgeStats, getRuns, getNotifications } from "../api.js";

function timeAgo(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

const STATUS_TAG = {
  queued:      "tag-gray",
  validating:  "tag-purple",
  parsing:     "tag-purple",
  confirming:  "tag-amber",
  architecting:"tag-violet",
  generating:  "tag-cyan",
  packaging:   "tag-cyan",
  complete:    "tag-green",
  failed:      "tag-red",
};

export default function Command() {
  const [stats, setStats] = useState(null);
  const [recentRuns, setRecentRuns] = useState([]);
  const [notifications, setNotifications] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [statsData, runsData, notifData] = await Promise.allSettled([
          getForgeStats(),
          getRuns(),
          getNotifications(),
        ]);
        if (statsData.status === "fulfilled") setStats(statsData.value);
        if (runsData.status === "fulfilled") setRecentRuns((runsData.value || []).slice(0, 6));
        if (notifData.status === "fulfilled") setNotifications(notifData.value);
      } finally {
        setLoading(false);
      }
    }
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  const totalRuns   = stats?.total_runs   ?? 0;
  const complete    = stats?.complete     ?? 0;
  const failed      = stats?.failed       ?? 0;
  const active      = stats?.active_builds ?? 0;
  const successRate = totalRuns > 0 ? Math.round((complete / totalRuns) * 100) : 0;
  const pending     = notifications?.pendingApprovals ?? 0;
  const activity    = notifications?.recentActivity   ?? [];

  return (
    <>
      {/* ── Hero ── */}
      <div className="ddd-hero">
        <div>
          <div className="hero-eyebrow">⚒ AI Build Engine · Sydney, AUS</div>
          <div className="hero-title">THE FORGE<br/>DASHBOARD V11</div>
          <div className="hero-sub">Blueprint document → complete deployable codebase in 15–25 minutes. AI-powered, production-ready, every time.</div>
        </div>
        <div className="hero-stats">
          <div className="hero-stat">
            <div className="hero-stat-val">{totalRuns}</div>
            <div className="hero-stat-lbl">Total Builds</div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat-val" style={{ color: "var(--green)" }}>{complete}</div>
            <div className="hero-stat-lbl">Deployed</div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat-val" style={{ color: active > 0 ? "var(--cyan)" : "var(--t3)" }}>{active}</div>
            <div className="hero-stat-lbl">Building Now</div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat-val" style={{ color: "var(--p2)" }}>{successRate}%</div>
            <div className="hero-stat-lbl">Success Rate</div>
          </div>
        </div>
      </div>

      {/* ── Alerts ── */}
      {pending > 0 && (
        <div className="mb24">
          <div className="ddd-alert amber">
            <span className="alert-icon">⏳</span>
            <div className="alert-body">
              <div className="alert-title">{pending} build{pending !== 1 ? "s" : ""} awaiting spec approval</div>
              <div className="alert-sub">Review the generated spec and approve to start code generation</div>
            </div>
            <Link to="/queue" className="ddd-btn btn-amber btn-sm" style={{ flexShrink: 0 }}>REVIEW</Link>
          </div>
        </div>
      )}
      {active > 0 && (
        <div className="mb24" style={{ marginTop: pending > 0 ? 0 : undefined }}>
          <div className="ddd-alert" style={{ background: "var(--cyan-d)", border: "1px solid rgba(0,212,255,0.2)" }}>
            <span className="alert-icon">⚡</span>
            <div className="alert-body">
              <div className="alert-title">{active} build{active !== 1 ? "s" : ""} currently generating code</div>
              <div className="alert-sub">AI pipeline running — stay tuned for completion</div>
            </div>
            <Link to="/active" className="ddd-btn btn-ghost btn-sm" style={{ flexShrink: 0 }}>WATCH</Link>
          </div>
        </div>
      )}

      {/* ── KPI row ── */}
      <div className="g6 mb24">
        <div className="ddd-card ddd-kpi purple">
          <div className="kpi-label">Total Runs</div>
          <div className="kpi-value purple">{totalRuns}</div>
          <div className="kpi-sub">All time</div>
        </div>
        <div className="ddd-card ddd-kpi green">
          <div className="kpi-label">Complete</div>
          <div className="kpi-value green">{complete}</div>
          <div className="kpi-sub">Ready to deploy</div>
        </div>
        <div className="ddd-card ddd-kpi">
          <div className="kpi-label">Building</div>
          <div className="kpi-value cyan">{active}</div>
          <div className="kpi-sub">In pipeline</div>
        </div>
        <div className="ddd-card ddd-kpi">
          <div className="kpi-label">Failed</div>
          <div className="kpi-value red">{failed}</div>
          <div className="kpi-sub">Needs review</div>
        </div>
        <div className="ddd-card ddd-kpi">
          <div className="kpi-label">Awaiting</div>
          <div className="kpi-value amber">{pending}</div>
          <div className="kpi-sub">Your approval</div>
        </div>
        <div className="ddd-card ddd-kpi">
          <div className="kpi-label">Success Rate</div>
          <div className="kpi-value" style={{ color: successRate >= 80 ? "var(--green)" : successRate >= 60 ? "var(--amber)" : "var(--red)" }}>{successRate}%</div>
          <div className="kpi-sub">Complete / total</div>
        </div>
      </div>

      {/* ── Activity feed + Recent builds ── */}
      <div className="g2">
        <div className="ddd-card">
          <div className="card-title">Live Activity Feed</div>
          {loading ? (
            <div style={{ color: "var(--t3)", fontFamily: "var(--fm)", fontSize: 11, padding: "20px 0" }}>Loading...</div>
          ) : activity.length === 0 ? (
            <div style={{ color: "var(--t3)", fontFamily: "var(--fm)", fontSize: 11, padding: "20px 0" }}>No activity yet — submit your first blueprint to get started.</div>
          ) : (
            activity.map((item, i) => (
              <div key={i} className="feed-item">
                <div className="feed-icon" style={{ background: "var(--p-d)" }}>
                  {item.type === "complete" ? "✅" : item.type === "failed" ? "❌" : item.type === "approving" ? "⏳" : "⚡"}
                </div>
                <div className="feed-body">
                  <div className="feed-title">{item.title || item.run_id}</div>
                  <div className="feed-sub">{item.status || item.message}</div>
                </div>
                <div className="feed-time">{timeAgo(item.created_at)}</div>
              </div>
            ))
          )}
        </div>

        <div className="ddd-card">
          <div className="card-title">Recent Builds</div>
          {recentRuns.length === 0 ? (
            <div style={{ color: "var(--t3)", fontFamily: "var(--fm)", fontSize: 11, padding: "20px 0" }}>
              No builds yet. <Link to="/build" style={{ color: "var(--p2)" }}>Start your first →</Link>
            </div>
          ) : (
            recentRuns.map((run) => (
              <Link
                key={run.run_id}
                to={`/runs/${run.run_id}`}
                className="pipe-card"
                style={{ textDecoration: "none", display: "block" }}
              >
                <div className="pipe-card-name">{run.title}</div>
                <div className="pipe-card-meta">
                  <span className={`ddd-tag ${STATUS_TAG[run.status] || "tag-gray"}`}>
                    {run.status.toUpperCase()}
                  </span>
                  <span className="pipe-card-age">{timeAgo(run.created_at)}</span>
                </div>
              </Link>
            ))
          )}
          <div className="ddd-div" />
          <div style={{ display: "flex", gap: 8 }}>
            <Link to="/build" className="ddd-btn btn-purple btn-sm" style={{ flex: 1, justifyContent: "center" }}>+ NEW BUILD</Link>
            <Link to="/history" className="ddd-btn btn-ghost btn-sm" style={{ flex: 1, justifyContent: "center" }}>ALL BUILDS</Link>
          </div>
        </div>
      </div>

      {/* ── Pipeline stages ── */}
      <div className="ddd-card mt16">
        <div className="card-title">7-Stage Build Pipeline</div>
        <div className="ddd-flow">
          {["Parse", "Spec", "Architect", "Generate", "Secrets", "README", "Package"].map((stage, i, arr) => (
            <div key={stage} style={{ display: "flex", alignItems: "center", flex: 1 }}>
              <div className="flow-step" style={{ flex: 1 }}>
                <div className="flow-step-num">{i + 1}</div>
                <div className="flow-step-label">{stage}</div>
              </div>
              {i < arr.length - 1 && <div className="flow-arrow">›</div>}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
