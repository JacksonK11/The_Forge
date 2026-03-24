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

export async function getDetailedHealth() {
  return request("GET", "/system/health/detailed");
}

export async function getRecentLogs({ limit = 100, level = "", module = "", run_id = "" } = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  if (level) params.set("level", level);
  if (module) params.set("module", module);
  if (run_id) params.set("run_id", run_id);
  return request("GET", `/system/logs/recent?${params.toString()}`);
}

// ─── Templates ────────────────────────────────────────────────────────────────

export async function getTemplates() {
  return request("GET", "/templates");
}

// ─── Forge Runs ───────────────────────────────────────────────────────────────

export async function submitBuild(payload) {
  return request("POST", "/forge/submit", payload);
}

export async function submitBuildWithFiles({ title, blueprint_text, repo_name, push_to_github, files }) {
  const formData = new FormData();
  formData.append("title", title || "");
  formData.append("blueprint_text", blueprint_text || "");
  formData.append("repo_name", repo_name || "");
  formData.append("push_to_github", push_to_github !== false ? "true" : "false");
  if (files && files.length > 0) {
    for (const file of files) {
      formData.append("files", file);
    }
  }
  const res = await fetch(`${BASE_URL}/forge/submit-with-files`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_SECRET}`,
    },
    body: formData,
  });
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

export async function getRun(runId) {
  return request("GET", `/forge/runs/${runId}`);
}

export async function getRuns() {
  const data = await request("GET", "/forge/runs");
  // API returns RunListResponse {runs: [...], total, page, page_size} — unwrap the array
  return Array.isArray(data) ? data : (data?.runs || []);
}

export async function getRunFiles(runId, includeContent = false) {
  return request("GET", `/forge/runs/${runId}/files?include_content=${includeContent}`);
}

export async function getForgeStats() {
  return request("GET", "/forge/stats");
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

export async function resumeRun(runId) {
  return request("POST", `/forge/runs/${runId}/resume`);
}

export async function forceFailRun(runId) {
  return request("POST", `/forge/runs/${runId}/force-fail`);
}

// ─── File Upload (Server-side text extraction) ────────────────────────────────

export async function submitFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${BASE_URL}/forge/submit-file`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${API_SECRET}`,
    },
    body: formData,
  });
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

// ─── Deploy Status & Secrets ──────────────────────────────────────────────────

export async function getDeployStatus(runId) {
  return request("GET", `/forge/runs/${runId}/deploy-status`);
}

export async function setRunSecrets(runId, secrets) {
  return request("POST", `/forge/runs/${runId}/set-secrets`, { secrets });
}

// ─── Chat ─────────────────────────────────────────────────────────────────────

export async function sendChatMessage(messages, memoryNotes, filesContext) {
  return request("POST", "/forge/chat", {
    messages,
    memory_notes: memoryNotes,
    files_context: filesContext,
  });
}

// ─── Analytics & Settings ─────────────────────────────────────────────────────

export async function getAnalytics() {
  return request("GET", "/forge/runs/analytics");
}

export async function getSettings() {
  return request("GET", "/settings");
}

export async function saveSettings(data) {
  return request("PUT", "/settings", data);
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