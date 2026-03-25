import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { getRuns } from "../api.js";

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

const FILTERS = ["", "complete", "failed", "confirming", "generating"];

function timeAgo(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function History() {
  const [allRuns, setAllRuns] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const pageSize = 20;

  useEffect(() => {
    setLoading(true);
    getRuns()
      .then((data) => setAllRuns(data || []))
      .catch((err) => console.error("History fetch:", err))
      .finally(() => setLoading(false));
  }, []);

  const filtered = statusFilter ? allRuns.filter((r) => r.status === statusFilter) : allRuns;
  const total = filtered.length;
  const totalPages = Math.ceil(total / pageSize);
  const runs = filtered.slice((page - 1) * pageSize, page * pageSize);

  function handleFilter(f) { setStatusFilter(f); setPage(1); }

  return (
    <>
      <div className="sec-title">History</div>
      <div className="sec-sub">All builds · <span>{total} runs{statusFilter ? ` (${statusFilter})` : ""}</span></div>

      {/* ── Filters ── */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20, flexWrap: "wrap" }}>
        {FILTERS.map((f) => (
          <button
            key={f || "all"}
            onClick={() => handleFilter(f)}
            className={`ddd-btn btn-sm ${statusFilter === f ? "btn-purple" : "btn-ghost"}`}
          >
            {f || "ALL"}
          </button>
        ))}
        {statusFilter && (
          <button onClick={() => handleFilter("")} className="ddd-btn btn-sm btn-ghost" style={{ marginLeft: "auto" }}>
            ✕ CLEAR
          </button>
        )}
      </div>

      {loading ? (
        <div style={{ color: "var(--t3)", fontFamily: "var(--fm)", fontSize: 11, padding: "40px 0", textAlign: "center" }}>Loading history...</div>
      ) : runs.length === 0 ? (
        <div className="ddd-card" style={{ textAlign: "center", padding: "48px" }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>🔨</div>
          <div style={{ fontFamily: "var(--fd)", fontSize: 28, color: "var(--t2)", marginBottom: 8 }}>No Builds Yet</div>
          <Link to="/build" className="ddd-btn btn-purple btn-sm" style={{ display: "inline-flex" }}>Submit your first blueprint →</Link>
        </div>
      ) : (
        <div className="ddd-card" style={{ padding: 0, overflow: "hidden" }}>
          <table className="ddd-tbl">
            <thead>
              <tr>
                <th>Agent Name</th>
                <th>Run ID</th>
                <th>Status</th>
                <th>Files</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.run_id}>
                  <td>
                    <div style={{ fontWeight: 600, color: "var(--t1)" }}>{run.title}</div>
                  </td>
                  <td>
                    <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>
                      {run.run_id.slice(0, 12)}…
                    </span>
                  </td>
                  <td>
                    <span className={`ddd-tag ${STATUS_TAG[run.status] || "tag-gray"}`}>
                      {run.status.toUpperCase()}
                    </span>
                  </td>
                  <td>
                    {run.file_count > 0 ? (
                      <span style={{ fontFamily: "var(--fm)", fontSize: 11 }}>
                        {run.files_complete}/{run.file_count}
                      </span>
                    ) : "—"}
                  </td>
                  <td>
                    <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>
                      {timeAgo(run.created_at)}
                    </span>
                  </td>
                  <td>
                    <Link to={`/runs/${run.run_id}`} className="ddd-btn btn-ghost btn-sm">
                      VIEW →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Pagination ── */}
      {totalPages > 1 && (
        <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 12, marginTop: 20 }}>
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="ddd-btn btn-ghost btn-sm"
          >
            ← PREV
          </button>
          <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>
            PAGE {page} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="ddd-btn btn-ghost btn-sm"
          >
            NEXT →
          </button>
        </div>
      )}
    </>
  );
}
