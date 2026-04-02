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
  queued:       "tag-gray",
  validating:   "tag-purple",
  parsing:      "tag-purple",
  confirming:   "tag-amber",
  architecting: "tag-violet",
  generating:   "tag-cyan",
  packaging:    "tag-cyan",
  complete:     "tag-green",
  failed:       "tag-red",
};

const PIPELINE_STAGES = [
  { label: "Parse",      icon: "📄", desc: "Blueprint" },
  { label: "Spec",       icon: "📋", desc: "Architecture" },
  { label: "Architect",  icon: "🏗", desc: "Structure" },
  { label: "Generate",   icon: "⚡", desc: "Code Gen" },
  { label: "Secrets",    icon: "🔐", desc: "Config" },
  { label: "README",     icon: "📘", desc: "Docs" },
  { label: "Package",    icon: "📦", desc: "ZIP Output" },
];

function ActivityFeed({ activity, loading }) {
  if (loading) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {[1, 2, 3].map((i) => (
          <div key={i} style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
            <div className="skeleton" style={{ width: 11, height: 11, borderRadius: "50%", flexShrink: 0, marginTop: 3 }} />
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
              <div className="skeleton" style={{ height: 12, width: "60%" }} />
              <div className="skeleton" style={{ height: 10, width: "40%" }} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (activity.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">📡</div>
        <div className="empty-state-title">No activity yet</div>
        <div className="empty-state-sub">Submit your first blueprint to start seeing build events here.</div>
      </div>
    );
  }

  function getEventType(item) {
    if (item.type === "complete" || item.status === "complete") return "complete";
    if (item.type === "failed"   || item.status === "failed")   return "failed";
    if (item.type === "approving") return "approving";
    return "started";
  }

  function getEventLabel(type) {
    if (type === "complete")  return "COMPLETE";
    if (type === "failed")    return "FAILED";
    if (type === "approving") return "APPROVAL";
    return "STARTED";
  }

  return (
    <div className="feed-v2 fade-in">
      {activity.map((item, i) => {
        const evType = getEventType(item);
        return (
          <div key={i} className="feed-v2-item">
            <div className={`feed-v2-dot ${evType}`} />
            <div className="feed-v2-body">
              <div className="feed-v2-header">
                <span className={`feed-v2-badge ${evType}`}>{getEventLabel(evType)}</span>
                <span className="feed-v2-name">{item.title || item.run_id || "Build event"}</span>
                <span className="feed-v2-time">{timeAgo(item.created_at)}</span>
              </div>
              {(item.status || item.message) && (
                <div className="feed-v2-sub">{item.status || item.message}</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function BuildCard({ run }) {
  const tagClass = STATUS_TAG[run.status] || "tag-gray";
  const shortId = run.run_id ? run.run_id.slice(0, 8) + "…" : "—";
  return (
    <Link
      to={`/runs/${run.run_id}`}
      className="build-card fade-in"
    >
      <div className="build-card-status">
        <span className={`ddd-tag ${tagClass}`}>{run.status.toUpperCase()}</span>
      </div>
      <div className="build-card-agent">{run.title || "Untitled Build"}</div>
      <div className="build-card-id" style={{ fontFamily: "var(--fm)" }}>{shortId}</div>
      <div className="build-card-meta">
        <div className="build-card-info">
          {run.files_count != null && <span>📄 {run.files_count} files</span>}
          <span>🕐 {timeAgo(run.created_at)}</span>
        </div>
        <span className="build-card-view">View →</span>
      </div>
    </Link>
  );
}

export default function Command() {
  const [stats, setStats]         = useState(null);
  const [recentRuns, setRecentRuns] = useState([]);
  const [notifications, setNotifications] = useState(null);
  const [loading, setLoading]     = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [statsData, runsData, notifData] = await Promise.allSettled([
          getForgeStats(),
          getRuns(),
          getNotifications(),
        ]);
        if (statsData.status === "fulfilled") setStats(statsData.value);
        if (runsData.status  === "fulfilled") setRecentRuns((runsData.value || []).slice(0, 6));
        if (notifData.status === "fulfilled") setNotifications(notifData.value);
      } finally {
        setLoading(false);
      }
    }
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  const totalRuns   = stats?.total_runs    ?? 0;
  const complete    = stats?.complete      ?? 0;
  const failed      = stats?.failed        ?? 0;
  const active      = stats?.active_builds ?? 0;
  const successRate = totalRuns > 0 ? Math.round((complete / totalRuns) * 100) : 0;
  const pending     = notifications?.pendingApprovals ?? 0;
  const activity    = notifications?.recentActivity   ?? [];

  const isBuilding     = active > 0;
  const statusClass    = isBuilding ? "status-building" : "status-operational";
  const statusLabel    = isBuilding ? "BUILDING"        : "OPERATIONAL";

  return (
    <>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <div className="ddd-hero fade-in">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <div className="hero-eyebrow" style={{ margin: 0 }}>⚒ AI Build Engine</div>
            <span className={`status-pill ${statusClass}`}>
              <span className="status-pill-dot" />
              {statusLabel}
            </span>
            <span className="version-badge">v1</span>
          </div>
          <div className="hero-title">THE FORGE</div>
          <div className="hero-sub">
            Blueprint document → complete deployable codebase in 15–25 minutes.
            AI-powered, production-ready, every time.
          </div>
        </div>

        <div className="hero-stats">
          <div className="hero-stat">
            <div className="hero-stat-val">{loading ? "—" : totalRuns}</div>
            <div className="hero-stat-lbl">Total Builds</div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat-val" style={{ color: "var(--green)" }}>
              {loading ? "—" : `${successRate}%`}
            </div>
            <div className="hero-stat-lbl">Success Rate</div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat-val" style={{ color: active > 0 ? "var(--cyan)" : "var(--t3)" }}>
              {loading ? "—" : active}
            </div>
            <div className="hero-stat-lbl">Active Now</div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat-val" style={{ color: "var(--amber)" }}>
              {loading ? "—" : "~20m"}
            </div>
            <div className="hero-stat-lbl">Avg Build Time</div>
          </div>
        </div>
      </div>

      {/* ── Quick Actions ─────────────────────────────────────────────────── */}
      <div className="quick-actions fade-in">
        <Link to="/build" className="quick-action-btn primary">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          New Build
        </Link>
        <Link to="/approvals" className="quick-action-btn">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
          </svg>
          Check Queue
          {pending > 0 && (
            <span className="quick-action-count" style={{ background: "rgba(255,176,32,0.25)", color: "var(--amber)" }}>
              {pending}
            </span>
          )}
        </Link>
        <Link to="/active" className="quick-action-btn">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          View Active
          {active > 0 && (
            <span className="quick-action-count" style={{ background: "rgba(0,212,255,0.2)", color: "var(--cyan)" }}>
              {active}
            </span>
          )}
        </Link>
        <Link to="/history" className="quick-action-btn">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          All Builds
        </Link>
      </div>

      {/* ── Alerts ─────────────────────────────────────────────────────────── */}
      {pending > 0 && (
        <div className="mb24">
          <div className="ddd-alert amber">
            <span className="alert-icon">⏳</span>
            <div className="alert-body">
              <div className="alert-title">
                {pending} build{pending !== 1 ? "s" : ""} awaiting spec approval
              </div>
              <div className="alert-sub">Review the generated spec and approve to start code generation</div>
            </div>
            <Link to="/approvals" className="ddd-btn btn-amber btn-sm" style={{ flexShrink: 0 }}>
              REVIEW
            </Link>
          </div>
        </div>
      )}
      {active > 0 && (
        <div className="mb24" style={{ marginTop: pending > 0 ? 0 : undefined }}>
          <div className="ddd-alert" style={{ background: "var(--cyan-d)", border: "1px solid rgba(0,212,255,0.2)" }}>
            <span className="alert-icon">⚡</span>
            <div className="alert-body">
              <div className="alert-title">
                {active} build{active !== 1 ? "s" : ""} currently generating code
              </div>
              <div className="alert-sub">AI pipeline running — stay tuned for completion</div>
            </div>
            <Link to="/active" className="ddd-btn btn-ghost btn-sm" style={{ flexShrink: 0 }}>
              WATCH
            </Link>
          </div>
        </div>
      )}

      {/* ── KPI row ────────────────────────────────────────────────────────── */}
      <div className="g6 mb24">
        {/* Total Runs */}
        <div className="ddd-card ddd-kpi kpi-purple">
          <span className="kpi-icon">🔨</span>
          <div className="kpi-label">Total Runs</div>
          <div className="kpi-value purple">{loading ? <span className="skeleton" style={{ display: "inline-block", width: 60, height: 40 }} /> : totalRuns}</div>
          <div className="kpi-sub">All time</div>
        </div>

        {/* Complete */}
        <div className="ddd-card ddd-kpi kpi-green green">
          <span className="kpi-icon">✅</span>
          <div className="kpi-label">Complete</div>
          <div className="kpi-value green">{loading ? "—" : complete}</div>
          <div className="kpi-sub">Ready to deploy</div>
        </div>

        {/* Building */}
        <div className="ddd-card ddd-kpi kpi-cyan">
          <span className="kpi-icon">⚡</span>
          <div className="kpi-label">Building</div>
          <div className="kpi-value cyan">{loading ? "—" : active}</div>
          <div className="kpi-sub">In pipeline</div>
        </div>

        {/* Failed */}
        <div className="ddd-card ddd-kpi kpi-red">
          <span className="kpi-icon">❌</span>
          <div className="kpi-label">Failed</div>
          <div className="kpi-value red">{loading ? "—" : failed}</div>
          <div className="kpi-sub">Needs review</div>
        </div>

        {/* Awaiting */}
        <div className="ddd-card ddd-kpi kpi-amber">
          <span className="kpi-icon">⏳</span>
          <div className="kpi-label">Awaiting</div>
          <div className="kpi-value amber">{loading ? "—" : pending}</div>
          <div className="kpi-sub">Your approval</div>
        </div>

        {/* Success Rate */}
        <div className="ddd-card ddd-kpi" style={{ paddingTop: 18 }}>
          <span className="kpi-icon">📊</span>
          <div className="kpi-label">Success Rate</div>
          <div
            className="kpi-value"
            style={{
              color: successRate >= 80
                ? "var(--green)"
                : successRate >= 60
                ? "var(--amber)"
                : "var(--red)",
            }}
          >
            {loading ? "—" : `${successRate}%`}
          </div>
          <div className="kpi-sub">Complete / total</div>
          {!loading && totalRuns > 0 && (
            <div style={{ marginTop: 8 }}>
              <div className="ddd-prog">
                <div
                  className="ddd-prog-fill"
                  style={{
                    width: `${successRate}%`,
                    background: successRate >= 80
                      ? "var(--green)"
                      : successRate >= 60
                      ? "var(--amber)"
                      : "var(--red)",
                  }}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Activity feed + Recent builds ──────────────────────────────────── */}
      <div className="g2 mb24">
        {/* Activity feed */}
        <div className="ddd-card">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <div className="card-title" style={{ margin: 0 }}>Live Activity Feed</div>
            {activity.length > 0 && (
              <span style={{
                fontFamily: "var(--fm)", fontSize: 9, color: "var(--green)",
                background: "var(--green-d)", border: "1px solid rgba(0,232,122,0.25)",
                padding: "2px 8px", borderRadius: 20, display: "flex", alignItems: "center", gap: 5,
              }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--green)", display: "inline-block", animation: "pulse 2s infinite" }} />
                LIVE
              </span>
            )}
          </div>
          <ActivityFeed activity={activity} loading={loading} />
        </div>

        {/* Recent builds */}
        <div className="ddd-card">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <div className="card-title" style={{ margin: 0 }}>Recent Builds</div>
            <Link to="/history" style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--t3)", textDecoration: "none" }}>
              View all →
            </Link>
          </div>

          {recentRuns.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">🚀</div>
              <div className="empty-state-title">No builds yet</div>
              <div className="empty-state-sub">
                Your builds will appear here once you submit your first blueprint.
              </div>
              <Link to="/build" className="ddd-btn btn-purple btn-sm" style={{ marginTop: 16 }}>
                + Start First Build
              </Link>
            </div>
          ) : (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                {recentRuns.map((run) => (
                  <BuildCard key={run.run_id} run={run} />
                ))}
              </div>
              <div className="ddd-div" />
              <div style={{ display: "flex", gap: 8 }}>
                <Link to="/build" className="ddd-btn btn-purple btn-sm" style={{ flex: 1, justifyContent: "center" }}>
                  + New Build
                </Link>
                <Link to="/history" className="ddd-btn btn-ghost btn-sm" style={{ flex: 1, justifyContent: "center" }}>
                  All Builds
                </Link>
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Pipeline visualization ─────────────────────────────────────────── */}
      <div className="ddd-card mt16 fade-in">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
          <div className="card-title" style={{ margin: 0 }}>7-Stage Build Pipeline</div>
          <span style={{
            fontFamily: "var(--fm)", fontSize: 9, color: "var(--p2)",
            background: "var(--p-d)", border: "1px solid var(--p-g)",
            padding: "2px 8px", borderRadius: 3,
          }}>
            AUTOMATED
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "stretch", gap: 0, overflowX: "auto" }}>
          {PIPELINE_STAGES.map((stage, i, arr) => (
            <div key={stage.label} style={{ display: "flex", alignItems: "center", flex: 1, minWidth: 0 }}>
              <div className="flow-step" style={{ flex: 1, minWidth: 72 }}>
                <span className="flow-step-icon">{stage.icon}</span>
                <div className="flow-step-num">{i + 1}</div>
                <div className="flow-step-label">{stage.label}</div>
                <div style={{ fontFamily: "var(--fm)", fontSize: 8, color: "var(--t4)", marginTop: 3, letterSpacing: "0.06em" }}>
                  {stage.desc}
                </div>
              </div>
              {i < arr.length - 1 && (
                <div style={{ padding: "0 2px", flexShrink: 0 }}>
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ color: "var(--line3)" }}>
                    <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
