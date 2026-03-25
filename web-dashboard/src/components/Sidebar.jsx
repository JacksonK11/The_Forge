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
        <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
  },
];

// Mobile bottom tab definitions (5 tabs)
export const MOBILE_TABS = [
  { label: "Build", path: "/", exact: true, badgeKey: null },
  { label: "Approvals", path: "/approvals", badgeKey: "pendingApprovals", badgeColor: "bg-amber-500" },
  { label: "Agents", path: "/agents", badgeKey: "pendingFeedback", badgeColor: "bg-purple-500" },
  { label: "History", path: "/history", badgeKey: "failedBuilds", badgeColor: "bg-red-500" },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(dateStr) {
  if (!dateStr) return "";
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ── Desktop Sidebar ───────────────────────────────────────────────────────────

export function DesktopSidebar() {
  const notifications = useNotifications();
  const location = useLocation();
  const navigate = useNavigate();
  const searchRef = useRef(null);

  function handleSearchClick() {
    searchRef.current?.focus();
    // Fire synthetic Cmd+K event for any listener
    window.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "k",
        metaKey: true,
        ctrlKey: false,
        bubbles: true,
      })
    );
  }

  function isActive(path, exact) {
    if (exact) return location.pathname === path;
    return location.pathname.startsWith(path);
  }

  function navItemClass(active) {
    return `relative w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all duration-150 text-left no-select ${
      active
        ? "bg-purple-900/30 border-l-2 border-purple-500 text-white pl-[10px]"
        : "text-gray-500 hover:text-gray-300 hover:bg-gray-800 border-l-2 border-transparent"
    }`;
  }

  return (
    <aside className="w-[220px] flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col h-full overflow-hidden">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-4 py-4 border-b border-gray-800 flex-shrink-0">
        <div className="w-8 h-8 rounded-lg bg-purple-800/30 border border-purple-700/50 flex items-center justify-center flex-shrink-0">
          <span className="text-purple-300 text-base leading-none">⚒</span>
        </div>
        <div className="min-w-0">
          <p className="font-['Bebas_Neue'] text-lg text-purple-400 tracking-widest leading-none whitespace-nowrap">
            THE FORGE
          </p>
          <p className="text-gray-500 text-xs tracking-widest whitespace-nowrap">AI BUILD ENGINE</p>
        </div>
      </div>

      {/* Search */}
      <div className="px-3 py-3 flex-shrink-0">
        <div
          className="flex items-center gap-2 bg-gray-800 rounded-lg px-3 py-2 cursor-text"
          onClick={handleSearchClick}
        >
          <svg className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            ref={searchRef}
            type="text"
            placeholder="Search builds... (⌘K)"
            className="flex-1 min-w-0 bg-transparent text-sm text-gray-400 placeholder-gray-600 outline-none"
            onKeyDown={(e) => {
              if (e.key === "Enter" && e.currentTarget.value.trim()) {
                navigate(`/history?q=${encodeURIComponent(e.currentTarget.value.trim())}`);
                e.currentTarget.value = "";
              }
            }}
          />
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5">
        {/* Primary group */}
        {PRIMARY_NAV.map((item) => {
          const active = isActive(item.path, item.exact);
          const badgeCount = item.badgeKey ? notifications[item.badgeKey] : 0;
          return (
            <NavLink key={item.path} to={item.path} end={item.exact} className={() => navItemClass(active)}>
              <span className={`flex-shrink-0 ${active ? "text-purple-400" : "text-gray-600"}`}>
                {item.icon}
              </span>
              <span className="flex-1 whitespace-nowrap overflow-hidden text-ellipsis">{item.label}</span>
              {badgeCount > 0 && (
                <span className={`scale-in flex-shrink-0 inline-flex items-center justify-center rounded-full w-5 h-5 text-xs font-bold text-white ${item.badgeColor || "bg-gray-600"}`}>
                  {badgeCount > 99 ? "99+" : badgeCount}
                </span>
              )}
            </NavLink>
          );
        })}

        {/* Separator */}
        <div className="my-2 border-t border-gray-800" />

        {/* Secondary group */}
        {SECONDARY_NAV.map((item) => {
          const active = isActive(item.path, false);
          return (
            <NavLink key={item.path} to={item.path} className={() => navItemClass(active)}>
              <span className={`flex-shrink-0 ${active ? "text-purple-400" : "text-gray-600"}`}>
                {item.icon}
              </span>
              <span className="flex-1 whitespace-nowrap overflow-hidden text-ellipsis">{item.label}</span>
            </NavLink>
          );
        })}

        {/* Separator */}
        <div className="my-2 border-t border-gray-800" />

        {/* Activity section */}
        <div className="px-1 pt-1">
          <p className="text-xs text-gray-500 tracking-widest uppercase mb-2 px-2">Activity</p>
          {notifications.recentActivity && notifications.recentActivity.length > 0 ? (
            notifications.recentActivity.slice(0, 3).map((event, idx) => (
              <button
                key={event.run_id || idx}
                onClick={() => navigate(`/runs/${event.run_id}`)}
                className="w-full text-left flex items-start gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-800 transition-colors group"
              >
                <span className="mt-1.5 flex-shrink-0 w-1.5 h-1.5 rounded-full bg-purple-500 animate-pulse" />
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-400 group-hover:text-gray-300 truncate transition-colors">
                    {event.text || event.message || event.title || `Run ${event.run_id}`}
                  </p>
                  <p className="text-xs text-gray-600">{timeAgo(event.created_at || event.timestamp)}</p>
                </div>
              </button>
            ))
          ) : (
            <p className="text-xs text-gray-700 px-2 py-1">No recent activity</p>
          )}
        </div>
      </nav>

      {/* System health footer */}
      <div className="px-4 py-3 border-t border-gray-800 flex-shrink-0 flex items-center gap-2">
        {notifications.loading ? (
          <>
            <span className="w-2 h-2 rounded-full bg-gray-600 flex-shrink-0" />
            <span className="text-xs text-gray-600">Checking...</span>
          </>
        ) : notifications.activeBuilds !== undefined ? (
          <>
            <span className="w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0 animate-pulse" />
            <span className="text-xs text-gray-500">System Healthy</span>
          </>
        ) : (
          <>
            <span className="w-2 h-2 rounded-full bg-red-500 flex-shrink-0" />
            <span className="text-xs text-red-400">System Down</span>
          </>
        )}
        <span className="ml-auto text-xs text-gray-700 font-['IBM_Plex_Mono']">v1.0</span>
      </div>
    </aside>
  );
}

// ── Mobile Bottom Tab Bar ─────────────────────────────────────────────────────

export function MobileTabBar() {
  const notifications = useNotifications();
  const location = useLocation();
  const navigate = useNavigate();
  const [moreOpen, setMoreOpen] = useState(false);

  function isTabActive(path, exact) {
    if (exact) return location.pathname === path;
    return location.pathname.startsWith(path);
  }

  const moreItems = [
    { label: "Upgrade Agent", path: "/upgrade" },
    { label: "Intelligence", path: "/intelligence" },
    { label: "Templates", path: "/templates" },
    { label: "Settings", path: "/settings" },
  ];

  const isMoreActive = moreItems.some((i) => location.pathname.startsWith(i.path));

  return (
    <>
      {/* Bottom tab bar */}
      <nav className="fixed bottom-0 inset-x-0 z-40 bg-gray-900 border-t border-gray-800 pb-safe flex items-stretch">
        {MOBILE_TABS.map((tab) => {
          const active = isTabActive(tab.path, tab.exact);
          const badgeCount = tab.badgeKey ? notifications[tab.badgeKey] : 0;
          return (
            <button
              key={tab.path}
              onClick={() => navigate(tab.path)}
              className={`flex-1 flex flex-col items-center justify-center py-2 relative no-select transition-colors ${
                active ? "text-purple-400" : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {active && (
                <span className="absolute top-0 left-1/4 right-1/4 h-0.5 bg-gradient-to-r from-purple-600 to-purple-400 rounded-b" />
              )}
              <MobileTabIcon label={tab.label} active={active} />
              <span className="text-[10px] mt-0.5 font-medium">{tab.label}</span>
              {badgeCount > 0 && (
                <span className={`absolute top-1 right-1/4 scale-in inline-flex items-center justify-center rounded-full w-4 h-4 text-[9px] font-bold text-white ${tab.badgeColor || "bg-gray-600"}`}>
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
            isMoreActive ? "text-purple-400" : "text-gray-500 hover:text-gray-300"
          }`}
        >
          {isMoreActive && (
            <span className="absolute top-0 left-1/4 right-1/4 h-0.5 bg-gradient-to-r from-purple-600 to-purple-400 rounded-b" />
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
          className="fixed inset-0 z-50 bg-black/50 flex items-end"
          onClick={() => setMoreOpen(false)}
        >
          <div
            className="slide-up w-full bg-gray-900 rounded-t-xl border-t border-gray-800 pb-safe"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 pt-4 pb-2">
              <h3 className="font-['Bebas_Neue'] text-lg text-purple-400 tracking-widest">More</h3>
              <button
                onClick={() => setMoreOpen(false)}
                className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="px-4 pb-6 space-y-1">
              {moreItems.map((item) => (
                <button
                  key={item.path}
                  onClick={() => {
                    navigate(item.path);
                    setMoreOpen(false);
                  }}
                  className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-colors ${
                    location.pathname.startsWith(item.path)
                      ? "bg-purple-900/30 text-purple-300"
                      : "text-gray-400 hover:text-white hover:bg-gray-800"
                  }`}
                >
                  {item.label}
                </button>
              ))}
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
