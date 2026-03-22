import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { listRuns } from "../api/client.js";

const STATUS_BADGE = {
  queued: "bg-gray-700 text-gray-300",
  validating: "bg-blue-900 text-blue-300",
  parsing: "bg-blue-900 text-blue-300",
  confirming: "bg-yellow-900 text-yellow-300",
  architecting: "bg-purple-900 text-purple-300",
  generating: "bg-indigo-900 text-indigo-300",
  packaging: "bg-teal-900 text-teal-300",
  complete: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
};

function timeAgo(isoString) {
  const diff = Date.now() - new Date(isoString).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function History() {
  const [runs, setRuns] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    listRuns(page, 20, statusFilter || null)
      .then((data) => {
        setRuns(data.runs);
        setTotal(data.total);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [page, statusFilter]);

  const totalPages = Math.ceil(total / 20);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Build History</h1>
          <p className="text-gray-400 text-sm mt-1">{total} total runs</p>
        </div>
        <div className="flex gap-2">
          {["", "complete", "failed", "generating", "confirming"].map((s) => (
            <button
              key={s}
              onClick={() => { setStatusFilter(s); setPage(1); }}
              className={`px-3 py-1.5 text-xs rounded transition-colors ${
                statusFilter === s
                  ? "bg-forge-accent text-white"
                  : "bg-forge-700 text-gray-400 hover:text-white"
              }`}
            >
              {s || "All"}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg px-4 py-3 text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-gray-400 text-center py-12">Loading...</div>
      ) : runs.length === 0 ? (
        <div className="text-center py-16 text-gray-500">
          <div className="text-4xl mb-3">🔨</div>
          <div className="text-lg font-medium text-gray-400 mb-2">No builds yet</div>
          <Link to="/" className="text-forge-accent hover:underline text-sm">
            Submit your first blueprint →
          </Link>
        </div>
      ) : (
        <div className="space-y-2">
          {runs.map((run) => (
            <Link
              key={run.run_id}
              to={`/runs/${run.run_id}`}
              className="block border border-forge-600 bg-forge-800 hover:bg-forge-700 hover:border-forge-accent rounded-xl px-5 py-4 transition-all"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div>
                    <div className="text-white font-medium text-sm">{run.title}</div>
                    <div className="text-gray-500 text-xs font-mono mt-0.5">
                      {run.run_id.slice(0, 8)}…
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  {run.file_count > 0 && (
                    <div className="text-gray-400 text-xs text-right">
                      <div className="text-white font-medium">
                        {run.files_complete}/{run.file_count}
                      </div>
                      <div>files</div>
                    </div>
                  )}
                  <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${STATUS_BADGE[run.status] || "bg-gray-700 text-gray-300"}`}>
                    {run.status}
                  </span>
                  <div className="text-gray-500 text-xs w-16 text-right">
                    {timeAgo(run.created_at)}
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1.5 bg-forge-700 text-gray-300 rounded text-sm disabled:opacity-40 hover:bg-forge-600 transition-colors"
          >
            ←
          </button>
          <span className="text-gray-400 text-sm">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-3 py-1.5 bg-forge-700 text-gray-300 rounded text-sm disabled:opacity-40 hover:bg-forge-600 transition-colors"
          >
            →
          </button>
        </div>
      )}
    </div>
  );
}
