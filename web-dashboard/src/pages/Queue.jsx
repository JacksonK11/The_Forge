import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { getPendingRuns, approveRun, getRuns } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

function timeAgo(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function Queue() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState(null);

  const fetchPending = useCallback(async () => {
    try {
      let list;
      try {
        const data = await getPendingRuns();
        list = Array.isArray(data) ? data : data?.runs || [];
      } catch {
        const allRuns = await getRuns();
        list = (allRuns || []).filter(
          (r) => r.status === "spec_ready" || r.status === "confirming" || r.status === "awaiting_approval"
        );
      }
      setRuns(list);
    } catch (err) {
      addToast(err.message || "Failed to load queue.", "error");
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    fetchPending();
    const id = setInterval(fetchPending, 15000);
    return () => clearInterval(id);
  }, [fetchPending]);

  async function handleApprove(runId) {
    setApproving(runId);
    try {
      await approveRun(runId);
      addToast("Build approved — pipeline resuming.", "success");
      setRuns((prev) => prev.filter((r) => (r.run_id || r.id) !== runId));
      setTimeout(fetchPending, 2000);
    } catch (err) {
      addToast(err.message || "Approval failed.", "error");
    } finally {
      setApproving(null);
    }
  }

  return (
    <>
      <div className="sec-title">Queue</div>
      <div className="sec-sub">Builds awaiting your spec review and approval · <span>{runs.length} pending</span></div>

      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
        <button onClick={fetchPending} className="ddd-btn btn-ghost btn-sm">↻ REFRESH</button>
      </div>

      {loading ? (
        <div style={{ color: "var(--t3)", fontFamily: "var(--fm)", fontSize: 11, padding: "40px 0", textAlign: "center" }}>Loading queue...</div>
      ) : runs.length === 0 ? (
        <div className="ddd-card green" style={{ textAlign: "center", padding: "48px" }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>✅</div>
          <div style={{ fontFamily: "var(--fd)", fontSize: 28, color: "var(--green)", marginBottom: 8 }}>All Clear</div>
          <div style={{ fontFamily: "var(--fm)", fontSize: 11, color: "var(--t3)" }}>No builds awaiting approval right now.</div>
        </div>
      ) : (
        <div className="gcol">
          {runs.map((run) => {
            const runId = run.run_id || run.id;
            const isApproving = approving === runId;
            return (
              <div key={runId} className="ddd-card amber">
                <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                      <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--amber)", boxShadow: "0 0 6px var(--amber)", flexShrink: 0, animation: "pulse 2s infinite" }} />
                      <span style={{ fontFamily: "var(--fm)", fontSize: 12, fontWeight: 700, color: "var(--t1)" }}>
                        {run.title || runId}
                      </span>
                      <span className="ddd-tag tag-amber">AWAITING APPROVAL</span>
                    </div>
                    {run.spec_summary && (
                      <div style={{ fontSize: 12, color: "var(--t2)", marginBottom: 8, paddingLeft: 16 }}>
                        {run.spec_summary}
                      </div>
                    )}
                    {run.spec_json && (
                      <div style={{ display: "flex", gap: 16, paddingLeft: 16, marginBottom: 8 }}>
                        {[
                          ["Files", run.spec_json.file_list?.length],
                          ["Tables", run.spec_json.database_tables?.length],
                          ["Routes", run.spec_json.api_routes?.length],
                          ["Services", run.spec_json.fly_services?.length],
                        ].filter(([, v]) => v).map(([label, value]) => (
                          <div key={label} style={{ textAlign: "center" }}>
                            <div style={{ fontFamily: "var(--fd)", fontSize: 20, color: "var(--p2)" }}>{value}</div>
                            <div style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--t3)", textTransform: "uppercase" }}>{label}</div>
                          </div>
                        ))}
                      </div>
                    )}
                    <div style={{ display: "flex", gap: 12, paddingLeft: 16, fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>
                      <span>{runId.slice(0, 12)}…</span>
                      <span>{timeAgo(run.created_at)}</span>
                    </div>
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: 8, flexShrink: 0 }}>
                    <button
                      onClick={() => navigate(`/runs/${runId}`)}
                      className="ddd-btn btn-ghost btn-sm"
                    >
                      REVIEW SPEC
                    </button>
                    <button
                      onClick={() => handleApprove(runId)}
                      disabled={isApproving}
                      className="ddd-btn btn-green btn-sm"
                    >
                      {isApproving ? "⏳ APPROVING..." : "✓ APPROVE"}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
