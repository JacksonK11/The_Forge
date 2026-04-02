import { useState, useRef } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useNotifications } from "../hooks/useNotifications.js";

// ── Nav item definitions ──────────────────────────────────────────────────────

const PRIMARY_NAV = [
  {
    label: "New Build",
    path: "/",
    exact: true,
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    ),
  },
  {
    label: "Approvals",
    path: "/approvals",
    badgeKey: "pendingApprovals",
    badgeColor: "bg-amber-500",
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    label: "Upgrade Agent",
    path: "/upgrade",
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h5M20 20v-5h-5M4 9a9 9 0 0115 0M20 15a9 9 0 01-15 0" />
      </svg>
    ),
  },
  {
    label: "My Agents",
    path: "/agents",
    badgeKey: "pendingFeedback",
    badgeColor: "bg-purple-500",
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    ),
  },
  {
    label: "Build History",
    path: "/history",
    badgeKey: "failedBuilds",
    badgeColor: "bg-red-500",
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
      </svg>
    ),
  },
];

const SECONDARY_NAV = [
  {
    label: "Intelligence",
    path: "/intelligence",
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    ),
  },
  {
    label: "Templates",
    path: "/templates",
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
      </svg>
    ),
  },
  {
    label: "Settings",
    path: "/settings",
    icon: (
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
  },
];

// Mobile bottom tab definitions (5 tabs)
export const MOBILE_TABS = [
  { label: "Build",     path: "/",           exact: true,  badgeKey: null },
  { label: "Approvals", path: "/approvals",               badgeKey: "pendingApprovals", badgeColor: "bg-amber-500" },
  { label: "Agents",    path: "/agents",                  badgeKey: "pendingFeedback",  badgeColor: "bg-purple-500" },
  { label: "History",   path: "/history",                 badgeKey: "failedBuilds",     badgeColor: "bg-red-500" },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(dateStr) {
  if (!dateStr) return "";
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
  if (diff < 60)    return `${Math.floor(diff)}s ago`;
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ── Desktop Sidebar ───────────────────────────────────────────────────────────

export function DesktopSidebar() {
  const notifications = useNotifications();
  const location      = useLocation();
  const navigate      = useNavigate();
  const searchRef     = useRef(null);

  function handleSearchClick() {
    searchRef.current?.focus();
    window.dispatchEvent(
      new KeyboardEvent("keydown", { key: "k", metaKey: true, ctrlKey: false, bubbles: true })
    );
  }

  function isActive(path, exact) {
    if (exact) return location.pathname === path;
    return location.pathname.startsWith(path);
  }

  const isOperational = notifications.activeBuilds !== undefined && !notifications.loading;
  const isBuilding    = (notifications.activeBuilds ?? 0) > 0;

  return (
    <aside className="w-[220px] flex-shrink-0 flex flex-col h-full overflow-hidden"
      style={{ background: "#070b18", borderRight: "1px solid #0f1c35" }}>

      {/* ── Logo ── */}
      <div style={{
        padding: "16px 16px 14px",
        borderBottom: "1px solid #0f1c35",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8, flexShrink: 0,
            background: "rgba(124,58,237,0.15)",
            border: "1px solid rgba(124,58,237,0.35)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <span style={{ fontSize: 16 }}>⚒</span>
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <p style={{
                fontFamily: "'Bebas Neue', sans-serif",
                fontSize: 18, letterSpacing: "0.1em",
                color: "#a78bfa", lineHeight: 1,
                background: "linear-gradient(135deg, #c4b5fd, #a78bfa)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}>
                THE FORGE
              </p>
              <span className="sidebar-logo-glow" />
            </div>
            <p style={{ fontFamily: "'Space Mono', monospace", fontSize: 9, color: "#3a5a78", letterSpacing: "0.1em", marginTop: 2 }}>
              AI BUILD ENGINE
            </p>
          </div>
        </div>
      </div>

      {/* ── Search ── */}
      <div style={{ padding: "10px 12px", flexShrink: 0 }}>
        <div
          onClick={handleSearchClick}
          style={{
            display: "flex", alignItems: "center", gap: 8,
            background: "rgba(15,28,53,0.8)",
            border: "1px solid #162440",
            borderRadius: 8, padding: "8px 10px",
            cursor: "text", transition: "border-color 0.15s",
          }}
          onMouseEnter={(e) => e.currentTarget.style.borderColor = "#7c3aed"}
          onMouseLeave={(e) => e.currentTarget.style.borderColor = "#162440"}
        >
          <svg style={{ width: 13, height: 13, color: "#3a5a78", flexShrink: 0 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={searchRef}
            type="text"
            placeholder="Search builds..."
            style={{
              flex: 1, minWidth: 0, background: "transparent",
              fontSize: 12, color: "#7a9ab8",
              border: "none", outline: "none",
              fontFamily: "'Outfit', sans-serif",
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && e.currentTarget.value.trim()) {
                navigate(`/history?q=${encodeURIComponent(e.currentTarget.value.trim())}`);
                e.currentTarget.value = "";
              }
            }}
          />
          <span style={{ fontFamily: "'Space Mono', monospace", fontSize: 8, color: "#1e3448", flexShrink: 0 }}>⌘K</span>
        </div>
      </div>

      {/* ── Nav ── */}
      <nav style={{ flex: 1, overflowY: "auto", padding: "4px 8px 8px" }}>
        {/* Primary group */}
        <div style={{ marginBottom: 4 }}>
          {PRIMARY_NAV.map((item) => {
            const active     = isActive(item.path, item.exact);
            const badgeCount = item.badgeKey ? (notifications[item.badgeKey] ?? 0) : 0;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.exact}
                className={`sidebar-nav-item no-select${active ? " active" : ""}`}
                style={{ marginBottom: 2 }}
              >
                <span style={{ flexShrink: 0, color: active ? "#a78bfa" : "#3a5a78", transition: "color 0.15s" }}>
                  {item.icon}
                </span>
                <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontFamily: "'Outfit', sans-serif", fontSize: 13 }}>
                  {item.label}
                </span>
                {badgeCount > 0 && (
                  <span
                    className={`sidebar-badge scale-in ${item.badgeColor || "bg-gray-600"}`}
                    style={{ position: "relative" }}
                  >
                    {badgeCount > 99 ? "99+" : badgeCount}
                    {/* Notification glow */}
                    <span style={{
                      position: "absolute", inset: -1, borderRadius: "50%",
                      boxShadow: item.badgeColor?.includes("amber")
                        ? "0 0 6px rgba(255,176,32,0.5)"
                        : item.badgeColor?.includes("red")
                        ? "0 0 6px rgba(255,58,92,0.5)"
                        : "0 0 6px rgba(167,139,250,0.5)",
                      pointerEvents: "none",
                    }} />
                  </span>
                )}
              </NavLink>
            );
          })}
        </div>

        {/* Separator */}
        <div style={{ height: 1, background: "#0f1c35", margin: "8px 4px" }} />

        {/* Secondary group */}
        <div style={{ marginBottom: 4 }}>
          {SECONDARY_NAV.map((item) => {
            const active = isActive(item.path, false);
            return (
              <NavLink
                key={item.path}
                to={item.path}
                className={`sidebar-nav-item no-select${active ? " active" : ""}`}
                style={{ marginBottom: 2 }}
              >
                <span style={{ flexShrink: 0, color: active ? "#a78bfa" : "#3a5a78", transition: "color 0.15s" }}>
                  {item.icon}
                </span>
                <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", fontFamily: "'Outfit', sans-serif", fontSize: 13 }}>
                  {item.label}
                </span>
              </NavLink>
            );
          })}
        </div>

        {/* Separator */}
        <div style={{ height: 1, background: "#0f1c35", margin: "8px 4px" }} />

        {/* Recent activity */}
        <div style={{ padding: "4px 4px 0" }}>
          <p style={{
            fontFamily: "'Space Mono', monospace", fontSize: 9,
            color: "#3a5a78", letterSpacing: "0.12em", textTransform: "uppercase",
            marginBottom: 6, paddingLeft: 4,
          }}>
            Recent Activity
          </p>
          {notifications.recentActivity && notifications.recentActivity.length > 0 ? (
            notifications.recentActivity.slice(0, 3).map((event, idx) => (
              <button
                key={event.run_id || idx}
                onClick={() => navigate(`/runs/${event.run_id}`)}
                style={{
                  width: "100%", textAlign: "left", display: "flex", alignItems: "flex-start", gap: 8,
                  padding: "6px 8px", borderRadius: 8, background: "none", border: "none",
                  cursor: "pointer", transition: "background 0.12s", marginBottom: 2,
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
                onMouseLeave={(e) => e.currentTarget.style.background = "none"}
                className="group"
              >
                <span style={{ marginTop: 5, flexShrink: 0, width: 6, height: 6, borderRadius: "50%", background: "#a78bfa", boxShadow: "0 0 6px rgba(167,139,250,0.4)", display: "inline-block", animation: "pulse 2s infinite" }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontSize: 11, color: "#7a9ab8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 1 }}>
                    {event.text || event.message || event.title || `Run ${event.run_id}`}
                  </p>
                  <p style={{ fontFamily: "'Space Mono', monospace", fontSize: 9, color: "#1e3448" }}>
                    {timeAgo(event.created_at || event.timestamp)}
                  </p>
                </div>
              </button>
            ))
          ) : (
            <p style={{ fontSize: 11, color: "#1e3448", padding: "4px 8px" }}>No recent activity</p>
          )}
        </div>
      </nav>

      {/* ── Footer ── */}
      <div style={{ flexShrink: 0, borderTop: "1px solid #0f1c35", padding: "10px 12px" }}>
        {/* API status */}
        <div className="sidebar-api-status" style={{ marginBottom: 8 }}>
          {notifications.loading ? (
            <>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#3a5a78", flexShrink: 0 }} />
              <span style={{ fontSize: 10, color: "#3a5a78" }}>Checking API...</span>
            </>
          ) : isOperational ? (
            <>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--green)", boxShadow: "0 0 6px rgba(0,232,122,0.4)", flexShrink: 0, animation: "pulse 2s infinite" }} />
              <span style={{ fontSize: 10, color: "var(--green)" }}>
                {isBuilding ? `${notifications.activeBuilds} building` : "All systems go"}
              </span>
            </>
          ) : (
            <>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--red)", flexShrink: 0 }} />
              <span style={{ fontSize: 10, color: "var(--red)" }}>API unreachable</span>
            </>
          )}
          <span style={{ marginLeft: "auto", fontFamily: "'Space Mono', monospace", fontSize: 9, color: "#1e3448" }}>v1.0</span>
        </div>

        {/* Settings shortcut */}
        <NavLink
          to="/settings"
          className="sidebar-nav-item no-select"
          style={{ padding: "7px 10px", fontSize: 12 }}
        >
          <svg style={{ width: 13, height: 13, flexShrink: 0, color: "#3a5a78" }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          <span style={{ fontFamily: "'Outfit', sans-serif", fontSize: 12, color: "#3a5a78" }}>Settings</span>
        </NavLink>
      </div>
    </aside>
  );
}

// ── Mobile Bottom Tab Bar ─────────────────────────────────────────────────────

export function MobileTabBar() {
  const notifications = useNotifications();
  const location      = useLocation();
  const navigate      = useNavigate();
  const [moreOpen, setMoreOpen] = useState(false);

  function isTabActive(path, exact) {
    if (exact) return location.pathname === path;
    return location.pathname.startsWith(path);
  }

  const moreItems = [
    { label: "Upgrade Agent", path: "/upgrade" },
    { label: "Intelligence",  path: "/intelligence" },
    { label: "Templates",     path: "/templates" },
    { label: "Settings",      path: "/settings" },
  ];

  const isMoreActive = moreItems.some((i) => location.pathname.startsWith(i.path));

  return (
    <>
      {/* Bottom tab bar */}
      <nav className="fixed bottom-0 inset-x-0 z-40 pb-safe flex items-stretch"
        style={{ background: "rgba(7,11,24,0.97)", borderTop: "1px solid #0f1c35", backdropFilter: "blur(16px)" }}>
        {MOBILE_TABS.map((tab) => {
          const active     = isTabActive(tab.path, tab.exact);
          const badgeCount = tab.badgeKey ? (notifications[tab.badgeKey] ?? 0) : 0;
          return (
            <button
              key={tab.path}
              onClick={() => navigate(tab.path)}
              className={`flex-1 flex flex-col items-center justify-center py-2 relative no-select transition-colors ${
                active ? "text-purple-400" : "text-gray-500"
              }`}
              style={{ background: "none", border: "none", cursor: "pointer" }}
            >
              {active && (
                <span className="absolute top-0 left-1/4 right-1/4 h-0.5 rounded-b"
                  style={{ background: "linear-gradient(90deg, #7c3aed, #a855f7)" }} />
              )}
              <MobileTabIcon label={tab.label} active={active} />
              <span className="text-[10px] mt-0.5 font-medium">{tab.label}</span>
              {badgeCount > 0 && (
                <span
                  className={`absolute top-1 right-1/4 scale-in inline-flex items-center justify-center rounded-full w-4 h-4 text-[9px] font-bold text-white ${tab.badgeColor || "bg-gray-600"}`}
                  style={{
                    boxShadow: tab.badgeColor?.includes("amber")
                      ? "0 0 6px rgba(255,176,32,0.5)"
                      : tab.badgeColor?.includes("red")
                      ? "0 0 6px rgba(255,58,92,0.5)"
                      : "0 0 6px rgba(167,139,250,0.5)",
                  }}
                >
                  {badgeCount > 9 ? "9+" : badgeCount}
                </span>
              )}
            </button>
          );
        })}

        {/* More tab */}
        <button
          onClick={() => setMoreOpen(true)}
          className={`flex-1 flex flex-col items-center justify-center py-2 relative no-select transition-colors ${
            isMoreActive ? "text-purple-400" : "text-gray-500"
          }`}
          style={{ background: "none", border: "none", cursor: "pointer" }}
        >
          {isMoreActive && (
            <span className="absolute top-0 left-1/4 right-1/4 h-0.5 rounded-b"
              style={{ background: "linear-gradient(90deg, #7c3aed, #a855f7)" }} />
          )}
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 12h.01M12 12h.01M19 12h.01" />
          </svg>
          <span className="text-[10px] mt-0.5 font-medium">More</span>
        </button>
      </nav>

      {/* Slide-up sheet */}
      {moreOpen && (
        <div
          className="fixed inset-0 z-50 flex items-end"
          style={{ background: "rgba(0,0,0,0.6)" }}
          onClick={() => setMoreOpen(false)}
        >
          <div
            className="slide-up w-full rounded-t-2xl pb-safe"
            style={{ background: "#070b18", borderTop: "1px solid #162440" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 16px 10px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <h3 style={{ fontFamily: "'Bebas Neue', sans-serif", fontSize: 20, color: "#a78bfa", letterSpacing: "0.08em" }}>
                  More
                </h3>
                <span style={{ fontFamily: "'Space Mono', monospace", fontSize: 8, color: "#3a5a78", letterSpacing: "0.08em" }}>
                  THE FORGE
                </span>
              </div>
              <button
                onClick={() => setMoreOpen(false)}
                style={{ width: 32, height: 32, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 8, color: "#3a5a78", background: "rgba(255,255,255,0.03)", border: "1px solid #0f1c35", cursor: "pointer" }}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div style={{ padding: "0 12px 24px", display: "flex", flexDirection: "column", gap: 4 }}>
              {moreItems.map((item) => {
                const isItemActive = location.pathname.startsWith(item.path);
                return (
                  <button
                    key={item.path}
                    onClick={() => { navigate(item.path); setMoreOpen(false); }}
                    style={{
                      width: "100%", display: "flex", alignItems: "center", gap: 12,
                      padding: "12px 16px", borderRadius: 12, fontSize: 14, fontWeight: 500,
                      background: isItemActive ? "rgba(124,58,237,0.12)" : "transparent",
                      color: isItemActive ? "#a78bfa" : "#7a9ab8",
                      border: "none", cursor: "pointer", fontFamily: "'Outfit', sans-serif",
                      transition: "background 0.12s, color 0.12s",
                      borderLeft: isItemActive ? "2px solid #7c3aed" : "2px solid transparent",
                      textAlign: "left",
                    }}
                  >
                    {item.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// Mobile tab icons
function MobileTabIcon({ label, active }) {
  const cls = `w-5 h-5 ${active ? "text-purple-400" : "text-gray-500"}`;
  switch (label) {
    case "Build":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
      );
    case "Approvals":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      );
    case "Agents":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
      );
    case "History":
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        </svg>
      );
    default:
      return (
        <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      );
  }
}
