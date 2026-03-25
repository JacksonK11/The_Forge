import { useState, useEffect, useRef, useCallback } from "react";

const PERMISSION_ASKED_KEY = "notification_permission_asked";
const RUN_STATES_KEY = "forge_run_states";

function getStoredRunStates() {
  try {
    const raw = localStorage.getItem(RUN_STATES_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveRunStates(states) {
  try {
    localStorage.setItem(RUN_STATES_KEY, JSON.stringify(states));
  } catch {
    // storage unavailable
  }
}

function buildNotificationPayload(run, newStatus) {
  switch (newStatus) {
    case "spec_ready":
      return {
        title: `Build Ready for Review: ${run.name || run.title || run.id}`,
        body: "Tap to review",
        url: `/runs/${run.id}`,
      };
    case "complete":
      return {
        title: `Build Complete: ${run.name || run.title || run.id}`,
        body: `${run.file_count ?? run.fileCount ?? 0} files ready`,
        url: `/runs/${run.id}`,
      };
    case "failed":
      return {
        title: `Build Failed: ${run.name || run.title || run.id}`,
        body: "Check build for details",
        url: `/runs/${run.id}`,
      };
    default:
      return null;
  }
}

const NOTIFY_STATES = new Set(["spec_ready", "complete", "failed"]);

export function useBrowserNotifications(runs = [], navigate = null) {
  const [permission, setPermission] = useState(
    typeof Notification !== "undefined" ? Notification.permission : "default"
  );
  const prevStatesRef = useRef(getStoredRunStates());
  const initializedRef = useRef(false);

  const requestPermission = useCallback(async () => {
    if (typeof Notification === "undefined") return "denied";
    if (Notification.permission !== "default") {
      setPermission(Notification.permission);
      return Notification.permission;
    }
    const result = await Notification.requestPermission();
    setPermission(result);
    localStorage.setItem(PERMISSION_ASKED_KEY, "true");
    return result;
  }, []);

  // Ask once on first visit
  useEffect(() => {
    if (typeof Notification === "undefined") return;
    const alreadyAsked = localStorage.getItem(PERMISSION_ASKED_KEY);
    if (!alreadyAsked && Notification.permission === "default") {
      // Slight delay so we don't block the initial render
      const timer = setTimeout(() => {
        requestPermission();
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [requestPermission]);

  // Watch for run state transitions
  useEffect(() => {
    if (!runs || runs.length === 0) return;

    // On first run we just populate the stored state without firing notifications
    if (!initializedRef.current) {
      const initial = {};
      runs.forEach((run) => {
        initial[run.id] = run.status;
      });
      prevStatesRef.current = initial;
      saveRunStates(initial);
      initializedRef.current = true;
      return;
    }

    if (typeof Notification === "undefined") return;
    if (Notification.permission !== "granted") return;

    const prev = prevStatesRef.current;
    const next = { ...prev };
    let changed = false;

    runs.forEach((run) => {
      const prevStatus = prev[run.id];
      const newStatus = run.status;

      if (prevStatus !== newStatus && NOTIFY_STATES.has(newStatus)) {
        const payload = buildNotificationPayload(run, newStatus);
        if (payload) {
          try {
            const notif = new Notification(payload.title, {
              body: payload.body,
              icon: "/pwa-192x192.png",
              badge: "/pwa-192x192.png",
              tag: `forge-run-${run.id}`,
            });
            notif.onclick = () => {
              window.focus();
              if (navigate) {
                navigate(payload.url);
              } else {
                window.location.href = payload.url;
              }
              notif.close();
            };
          } catch {
            // Notification API unavailable in this context
          }
        }
      }

      next[run.id] = newStatus;
      if (prevStatus !== newStatus) changed = true;
    });

    if (changed) {
      prevStatesRef.current = next;
      saveRunStates(next);
    }
  }, [runs, navigate]);

  return { permission, requestPermission };
}

export default useBrowserNotifications;
