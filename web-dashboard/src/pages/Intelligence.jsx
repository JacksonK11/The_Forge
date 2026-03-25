import { useState, useEffect } from "react";
import { getIntelligenceStats } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

function StatCard({ label, value, sub, color = "text-purple-400" }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-5">
      <p className="text-xs text-gray-500 uppercase tracking-widest mb-2">{label}</p>
      <p className={`font-['Bebas_Neue'] text-3xl ${color}`}>{value ?? "—"}</p>
      {sub && <p className="text-xs text-gray-600 mt-1">{sub}</p>}
    </div>
  );
}

export default function Intelligence() {
  const { addToast } = useToast();
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchStats() {
      try {
        const data = await getIntelligenceStats();
        setStats(data);
      } catch (err) {
        addToast(err.message || "Failed to load intelligence stats.", "error");
      } finally {
        setLoading(false);
      }
    }
    fetchStats();
  }, [addToast]);

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="font-['Bebas_Neue'] text-3xl text-white tracking-widest">Intelligence</h1>
        <p className="text-gray-500 text-sm mt-1">
          Knowledge base, meta-rules, and self-improvement metrics.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-12">
          <div className="w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : !stats ? (
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-8 text-center">
          <p className="text-gray-500 text-sm">Intelligence stats unavailable.</p>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="KB Records"
              value={stats.knowledge_base_records ?? stats.kb_records}
              sub="Stored outcomes"
              color="text-purple-400"
            />
            <StatCard
              label="Meta Rules"
              value={stats.meta_rules_count ?? stats.meta_rules}
              sub="Auto-extracted rules"
              color="text-cyan-400"
            />
            <StatCard
              label="Avg Score"
              value={stats.avg_eval_score != null ? `${(stats.avg_eval_score * 100).toFixed(0)}%` : null}
              sub="Evaluator pass rate"
              color="text-emerald-400"
            />
            <StatCard
              label="Builds Improved"
              value={stats.builds_improved}
              sub="Via self-learning"
              color="text-amber-400"
            />
          </div>

          {stats.recent_rules && stats.recent_rules.length > 0 && (
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
              <h2 className="font-['Bebas_Neue'] text-xl text-white tracking-widest mb-4">
                Recent Meta Rules
              </h2>
              <div className="space-y-3">
                {stats.recent_rules.map((rule, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <span className="flex-shrink-0 w-5 h-5 rounded-full bg-purple-900/50 border border-purple-700/50 flex items-center justify-center text-xs text-purple-400 font-bold">
                      {i + 1}
                    </span>
                    <p className="text-sm text-gray-300 leading-relaxed">{rule.rule || rule}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {stats.performance_trend && (
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
              <h2 className="font-['Bebas_Neue'] text-xl text-white tracking-widest mb-3">
                Performance Trend
              </h2>
              <p className="text-sm text-gray-400">{stats.performance_trend}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
