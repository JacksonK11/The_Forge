const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const API_SECRET = import.meta.env.VITE_API_SECRET_KEY || "";

function authHeaders(extra = {}) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${API_SECRET}`,
    ...extra,
  };
}

async function request(method, path, body = null, extraHeaders = {}) {
  const opts = {
    method,
    headers: authHeaders(extraHeaders),
  };
  if (body !== null) {
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${BASE_URL}${path}`, opts);
  if (!res.ok) {
    let errMsg = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      errMsg = data.detail || data.message || errMsg;
    } catch {
      // ignore parse error
    }
    throw new Error(errMsg);
  }
  return res.json();
}

async function requestBlob(path) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: {
      Authorization: `Bearer ${API_SECRET}`,
    },
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.blob();
}

// ─── Health ───────────────────────────────────────────────────────────────────

export async function getHealth() {
  return request("GET", "/health");
}

// ─── Templates ────────────────────────────────────────────────────────────────

export async function getTemplates() {
  return request("GET", "/templates");
}

// ─── Forge Runs ───────────────────────────────────────────────────────────────

export async function submitBuild(payload) {
  return request("POST", "/forge/submit", payload);
}

export async function getRun(runId) {
  return request("GET", `/forge/runs/${runId}`);
}

export async function getRuns() {
  return request("GET", "/forge/runs");
}

export async function approveRun(runId) {
  return request("POST", `/forge/runs/${runId}/approve`);
}

export async function getRunPackageBlob(runId) {
  return requestBlob(`/forge/runs/${runId}/package`);
}

export async function registerAgent(payload) {
  return request("POST", "/forge/register-agent", payload);
}

// ─── Forge Updates ────────────────────────────────────────────────────────────

export async function submitUpdate(payload) {
  return request("POST", "/forge/update", payload);
}

export async function getUpdate(updateId) {
  return request("GET", `/forge/updates/${updateId}`);
}

export async function getUpdates() {
  return request("GET", "/forge/updates");
}

// ─── Agents Registry ──────────────────────────────────────────────────────────

export async function getAgents() {
  return request("GET", "/forge/agents");
}

// ─── Chat ─────────────────────────────────────────────────────────────────────

export async function sendChatMessage(messages, memoryNotes, filesContext) {
  return request("POST", "/forge/chat", {
    messages,
    memory_notes: memoryNotes,
    files_context: filesContext,
  });
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

export function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

export { BASE_URL };
