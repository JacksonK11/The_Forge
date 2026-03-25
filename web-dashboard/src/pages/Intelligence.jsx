import { useState, useEffect } from "react";
import { getIntelligenceStats, getAgentRegistry } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

export default function Intelligence() {
  const { addToast } = useToast();
  const [stats, setStats] = useState(null);
  const [registry, setRegistry] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [statsData, regData] = await Promise.allSettled([
          getIntelligenceStats(),
          getAgentRegistry(),
        ]);
        if (statsData.status === "fulfilled") setStats(statsData.value);
        if (regData.status === "fulfilled") setRegistry(Array.isArray(regData.value) ? regData.value : []);
      } catch (err) {
        addToast(err.message || "Failed to load intelligence data.", "error");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [addToast]);

  return (
    <>
      <div className="sec-title">Intelligence</div>
      <div className="sec-sub">Knowledge base, meta-rules, and model routing — <span>The Forge learns from every build</span></div>

      {/* ── KPI row ── */}
      <div className="g5 mb24">
        {[
          ["KB Records",    stats?.knowledge_base_records ?? "—", "purple",  "Architecture patterns & outcomes"],
          ["Meta Rules",    stats?.meta_rules             ?? "—", "violet",  "Auto-extracted operational rules"],
          ["Build Templates",stats?.build_templates       ?? "—", "cyan",    "Reusable blueprint templates"],
          ["Error Patterns",stats?.error_fix_pairs        ?? "—", "amber",   "Known errors + confirmed fixes"],
          ["Agent Versions",stats?.agent_versions         ?? "—", "green",   "Deployed agent snapshots"],
        ].map(([label, value, color, sub]) => (
          <div key={label} className={`ddd-card ddd-kpi ${color}`}>
            <div className="kpi-label">{label}</div>
            <div className={`kpi-value ${color}`}>{loading ? "…" : value}</div>
            <div className="kpi-sub">{sub}</div>
          </div>
        ))}
      </div>

      {/* ── Intelligence pipeline ── */}
      <div className="ddd-card mb24 purple">
        <div className="card-title">Intelligence Layer — 7 Files</div>
        <div className="ddd-flow">
          {[
            ["model_config", "Routes Claude calls"],
            ["knowledge_base", "Stores outcomes"],
            ["meta_rules", "Weekly extraction"],
            ["context_assembler", "Optimal context"],
            ["evaluator", "Scores every output"],
            ["verifier", "Adversarial review"],
            ["performance_monitor", "KPI tracking"],
          ].map(([name, desc], i, arr) => (
            <div key={name} style={{ display: "flex", alignItems: "center", flex: 1 }}>
              <div className="flow-step" style={{ flex: 1, minWidth: 90 }}>
                <div className="flow-step-num" style={{ fontSize: 16 }}>{name.split("_").map(w => w[0].toUpperCase()).join("")}</div>
                <div className="flow-step-label" style={{ fontSize: 8 }}>{desc}</div>
              </div>
              {i < arr.length - 1 && <div className="flow-arrow">›</div>}
            </div>
          ))}
        </div>
      </div>

      {/* ── Model routing ── */}
      <div className="g3 mb24">
        <div className="ddd-card">
          <div className="card-title">Model Routing</div>
          {[
            ["Opus 4.6",    "claude-opus-4-6",              "Reasoning, complex generation"],
            ["Sonnet 4.6",  "claude-sonnet-4-6",            "Research, synthesis, analysis"],
            ["Haiku 4.5",   "claude-haiku-4-5-20251001",    "Classification, scoring, eval"],
          ].map(([name, model, use]) => (
            <div key={name} className="stat-row">
              <div>
                <div className="stat-label">{name}</div>
                <div style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--t3)" }}>{model}</div>
              </div>
              <span className="ddd-tag tag-gray" style={{ fontSize: 9, maxWidth: 120, textAlign: "right", whiteSpace: "normal" }}>{use}</span>
            </div>
          ))}
        </div>

        <div className="ddd-card">
          <div className="card-title">Knowledge Engine — 5 Files</div>
          {[
            ["collector",  "Tavily + RSS + YouTube sweeps"],
            ["embedder",   "400-token chunks + OpenAI embeds"],
            ["retriever",  "Top 8 semantic chunks per call"],
            ["live_search","Real-time Tavily for recency"],
            ["config",     "Domains, queries, schedules"],
          ].map(([name, desc]) => (
            <div key={name} className="stat-row">
              <span className="stat-label">{name}</span>
              <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--t3)", textAlign: "right", maxWidth: 140 }}>{desc}</span>
            </div>
          ))}
        </div>

        <div className="ddd-card">
          <div className="card-title">Embedding Model</div>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginBottom: 4 }}>PROVIDER</div>
            <div className="ddd-tag tag-green">OpenAI</div>
          </div>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginBottom: 4 }}>MODEL</div>
            <div style={{ fontFamily: "var(--fm)", fontSize: 11, color: "var(--t1)" }}>text-embedding-3-small</div>
          </div>
          <div>
            <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)", marginBottom: 4 }}>VECTOR STORE</div>
            <div className="ddd-tag tag-purple">pgvector</div>
          </div>
        </div>
      </div>

      {/* ── Agent registry ── */}
      {registry.length > 0 && (
        <div className="ddd-card">
          <div className="card-title">Agent Registry</div>
          <table className="ddd-tbl">
            <thead>
              <tr>
                <th>Agent Name</th>
                <th>Version</th>
                <th>Status</th>
                <th>Stack</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {registry.map((agent, i) => (
                <tr key={i}>
                  <td><strong>{agent.agent_name || agent.name}</strong></td>
                  <td><span className="ddd-tag tag-purple">{agent.version || "v1"}</span></td>
                  <td><span className="ddd-tag tag-green">{agent.status || "deployed"}</span></td>
                  <td style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t2)" }}>{agent.tech_stack || "FastAPI + React"}</td>
                  <td style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--t3)" }}>{agent.deployed_at ? new Date(agent.deployed_at).toLocaleDateString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
