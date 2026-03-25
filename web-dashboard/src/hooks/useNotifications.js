import { useState, useEffect, useRef } from "react";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const API_SECRET = import.meta.env.VITE_API_SECRET_KEY || "";

const DEFAULT_STATE = {
  pendingApprovals: 0,
  activeBuilds: 0,
  failedBuilds: 0,
  pendingFeedback: 0,
  recentActivity: [],
  loading: true,
};

export function useNotifications() {
  const [state, setState] = useState(DEFAULT_STATE);
  const intervalRef = useRef(null);
  const mountedRef = useRef(true);

  async function fetchNotifications() {
    try {
      const res = await fetch(`${BASE_URL}/forge/notifications`, {
        headers: {
          Authorization: `Bearer ${API_SECRET}`,
          "Content-Type": "application/json",
        },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (!mountedRef.current) return;
      setState({
        pendingApprovals: data.pending_approvals ?? data.pendingApprovals ?? 0,
        activeBuilds: data.active_builds ?? data.activeBuilds ?? 0,
        failedBuilds: data.failed_builds ?? data.failedBuilds ?? 0,
        pendingFeedback: data.pending_feedback ?? data.pendingFeedback ?? 0,
        recentActivity: data.recent_activity ?? data.recentActivity ?? [],
        loading: false,
      });
    } catch {
      if (!mountedRef.current) return;
      setState((prev) => ({ ...prev, loading: false }));
    }
  }

  useEffect(() => {
    mountedRef.current = true;
    fetchNotifications();
    intervalRef.current = setInterval(fetchNotifications, 15000);
    return () => {
      mountedRef.current = false;
      clearInterval(intervalRef.current);
    };
  }, []);

  return state;
}

export default useNotifications;
