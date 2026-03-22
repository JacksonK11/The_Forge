/**
 * api/client.js
 * API client for The Forge backend.
 * All requests include Bearer token auth.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const API_KEY = import.meta.env.VITE_API_SECRET_KEY || "";

async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${API_KEY}`,
    ...options.headers,
  };

  const response = await fetch(url, { ...options, headers });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response;
}

// ── Forge builds ──────────────────────────────────────────────────────────────

export async function submitBlueprint(title, blueprintText) {
  return request("/forge/submit", {
    method: "POST",
    body: JSON.stringify({ title, blueprint_text: blueprintText }),
  });
}

export async function submitBlueprintFile(title, file) {
  const formData = new FormData();
  formData.append("title", title);
  formData.append("file", file);
  return request("/forge/submit-file", {
    method: "POST",
    headers: { Authorization: `Bearer ${API_KEY}` },
    body: formData,
  });
}

export async function approveSpec(runId) {
  return request(`/forge/runs/${runId}/approve`, { method: "POST" });
}

export async function regenerateFile(runId, filePath) {
  return request(`/forge/runs/${runId}/regenerate/${filePath}`, {
    method: "POST",
  });
}

export function getPackageDownloadUrl(runId) {
  return `${API_BASE}/forge/runs/${runId}/package`;
}

// ── Runs ──────────────────────────────────────────────────────────────────────

export async function listRuns(page = 1, pageSize = 20, status = null) {
  const params = new URLSearchParams({ page, page_size: pageSize });
  if (status) params.set("status", status);
  return request(`/forge/runs?${params}`);
}

export async function getRun(runId) {
  return request(`/forge/runs/${runId}`);
}

export async function getRunFiles(runId, includeContent = false, layer = null) {
  const params = new URLSearchParams({ include_content: includeContent });
  if (layer !== null) params.set("layer", layer);
  return request(`/forge/runs/${runId}/files?${params}`);
}

export async function getFileContent(runId, filePath) {
  return request(`/forge/runs/${runId}/files/${filePath}`);
}

// ── Templates ─────────────────────────────────────────────────────────────────

export async function listTemplates() {
  return request("/templates");
}

export async function getTemplate(templateId) {
  return request(`/templates/${templateId}`);
}
