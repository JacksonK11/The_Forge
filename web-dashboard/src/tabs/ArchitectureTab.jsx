import { useState } from "react";

const COMPUTE_SERVICES = [
  { name: "the-forge-api", label: "API", region: "syd", desc: "FastAPI · 512MB · performance-cpu-1x", color: "border-purple-800 bg-purple-950/10", badge: "text-purple-300 bg-purple-900/50" },
  { name: "the-forge-worker", label: "Worker", region: "syd", desc: "RQ + Pipeline · 1GB · performance-cpu-4x", color: "border-teal-800 bg-teal-950/10", badge: "text-teal-300 bg-teal-900/50" },
  { name: "the-forge-scheduler", label: "Scheduler", region: "syd", desc: "APScheduler · 256MB · performance-cpu-2x", color: "border-yellow-800 bg-yellow-950/10", badge: "text-yellow-300 bg-yellow-900/50" },
  { name: "the-forge-dashboard", label: "Dashboard", region: "syd", desc: "React + Vite · 256MB · performance-cpu-2x", color: "border-cyan-800 bg-cyan-950/10", badge: "text-cyan-300 bg-cyan-900/50" },
];

const DATA_SERVICES = [
  { name: "the-forge-db", label: "PostgreSQL", desc: "Fly Managed · pgvector enabled · 2GB", icon: "🗄️", color: "border-blue-800 bg-blue-950/10" },
  { name: "the-forge-redis", label: "Redis", desc: "Fly Managed · 256MB · RQ queue backend", icon: "🔴", color: "border-red-800 bg-red-950/10" },
];

const EXTERNAL_SERVICES = [
  { name: "Anthropic API", key: "ANTHROPIC_API_KEY (the-forge)", icon: "🤖", color: "border-gray-700" },
  { name: "OpenAI Embeddings", key: "OPENAI_API_KEY", icon: "🔵", color: "border-gray-700" },
  { name: "Tavily Search", key: "TAVILY_API_KEY", icon: "🔍", color: "border-gray-700" },
  { name: "GitHub", key: "GITHUB_TOKEN", icon: "🐙", color: "border-gray-700" },
  { name: "Telegram Bot", key: "TELEGRAM_BOT_TOKEN", icon: "✈️", color: "border-gray-700" },
];

const DB_TABLES = [
  { name: "forge_runs", desc: "Build job records", layer: "core" },
  { name: "forge_files", desc: "Generated file contents", layer: "core" },
  { name: "forge_templates", desc: "Reusable blueprint templates", layer: "core" },
  { name: "forge_updates", desc: "Repo update job records", layer: "core" },
  { name: "agents_registry", desc: "Registered agent endpoints", layer: "core" },
  { name: "kb_records", desc: "Knowledge base outcomes", layer: "intelligence" },
  { name: "meta_rules", desc: "Auto-extracted operational rules", layer: "intelligence" },
  { name: "knowledge_articles", desc: "Scraped + summarised articles", layer: "knowledge" },
  { name: "knowledge_chunks", desc: "Embedding chunks (pgvector)", layer: "knowledge" },
  { name: "performance_metrics", desc: "KPI snapshots every 6h", layer: "monitoring" },
];

const FLY_SERVICES = [
  { app: "the-forge-api", type: "API", region: "syd", size: "performance-cpu-1x", ram: "512MB", cost: "~A$18/mo" },
  { app: "the-forge-worker", type: "Worker", region: "syd", size: "performance-cpu-4x", ram: "1GB", cost: "~A$37/mo" },
  { app: "the-forge-dashboard", type: "Dashboard", region: "syd", size: "performance-cpu-2x", ram: "256MB", cost: "~A$9/mo" },
  { app: "the-forge-scheduler", type: "Scheduler", region: "syd", size: "performance-cpu-2x", ram: "256MB", cost: "~A$9/mo" },
  { app: "the-forge-db", type: "Postgres", region: "syd", size: "HA Managed", ram: "2GB", cost: "~A$63/mo" },
  { app: "the-forge-redis", type: "Redis", region: "syd", size: "Managed", ram: "256MB", cost: "~A$30/mo" },
];

const tableLayerColors = {
  core: "text-purple-300 bg-purple-900/30",
  intelligence: "text-teal-300 bg-teal-900/30",
  knowledge: "text-cyan-300 bg-cyan-900/30",
  monitoring: "text-yellow-300 bg-yellow-900/30",
};

const INTELLIGENCE_ITEMS = [
  { name: "KbRecord", desc: "Outcome memory" },
  { name: "MetaRule", desc: "Auto-extracted rules" },
  { name: "context_assembler", desc: "Optimal context builder" },
  { name: "evaluator", desc: "Output quality scorer" },
  { name: "verifier", desc: "Adversarial reviewer" },
];

const KNOWLEDGE_ITEMS = [
  { name: "KnowledgeArticle", desc: "Scraped + summarised" },
  { name: "KnowledgeChunk", desc: "400-token embeddings" },
  { name: "collector.py", desc: "Tavily + RSS + YouTube" },
  { name: "embedder.py", desc: "text-embedding-3-small" },
  { name: "retriever.py", desc: "Top-8 similarity search" },
];

function CollapsibleSection({ title, subtitle, defaultOpen = true, children, borderColor = "border-gray-800" }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`border ${borderColor} rounded-xl overflow-hidden`}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 min-h-[44px] bg-gray-800/30 active:bg-gray-800/50 transition-colors"
      >
        <div className="text-left">
          <p className="text-xs text-gray-400 uppercase tracking-widest font-medium">{title}</p>
          {subtitle && <p className="text-gray-600 text-xs mt-0.5">{subtitle}</p>}
        </div>
        <span className={`text-gray-500 text-sm transition-transform ${open ? "rotate-180" : ""}`}>
          ▾
        </span>
      </button>
      {open && <div>{children}</div>}
    </div>
  );
}

function SectionHeader({ label }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <span className="text-xs text-gray-500 uppercase tracking-widest font-medium">
        {label}
      </span>
      <div className="flex-1 h-px bg-gray-800" />
    </div>
  );
}

export default function ArchitectureTab({ isMobile = false }) {
  const [expandedSections, setExpandedSections] = useState({
    compute: true,
    data: true,
    intelligence: !isMobile,
    knowledge: !isMobile,
    external: !isMobile,
    dbTables: !isMobile,
    flyServices: !isMobile,
  });

  function toggleSection(key) {
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return (
    <div className={isMobile ? "px-1" : "max-w-4xl mx-auto"}>
      <h2 className={`font-['Bebas_Neue'] text-gray-100 tracking-widest ${isMobile ? "text-3xl mb-5" : "text-4xl mb-8"}`}>
        ARCHITECTURE
      </h2>

      {/* Compute layer */}
      <div className="mb-6">
        {isMobile ? (
          <CollapsibleSection title="Compute Layer — Fly.io Sydney" defaultOpen={expandedSections.compute}>
            <div className="p-3 space-y-3">
              {COMPUTE_SERVICES.map((s) => (
                <div key={s.name} className={`border rounded-xl p-4 ${s.color}`}>
                  <div className="flex items-start justify-between mb-2">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${s.badge}`}>
                      {s.label}
                    </span>
                    <span className="text-gray-600 text-xs font-mono">{s.region}</span>
                  </div>
                  <p className="text-gray-200 text-sm font-semibold font-mono">{s.name}</p>
                  <p className="text-gray-500 text-xs mt-1">{s.desc}</p>
                </div>
              ))}
            </div>
          </CollapsibleSection>
        ) : (
          <>
            <SectionHeader label="Compute Layer — Fly.io Sydney" />
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {COMPUTE_SERVICES.map((s) => (
                <div key={s.name} className={`border rounded-xl p-4 ${s.color}`}>
                  <div className="flex items-start justify-between mb-2">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${s.badge}`}>
                      {s.label}
                    </span>
                    <span className="text-gray-600 text-xs font-mono">{s.region}</span>
                  </div>
                  <p className="text-gray-200 text-sm font-semibold font-mono">{s.name}</p>
                  <p className="text-gray-500 text-xs mt-1">{s.desc}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Connection arrows — desktop only */}
      {!isMobile && (
        <div className="flex justify-center gap-8 mb-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex flex-col items-center">
              <div className="h-6 w-px bg-gray-700" />
              <div className="w-0 h-0 border-l-4 border-r-4 border-t-4 border-l-transparent border-r-transparent border-t-gray-600" />
            </div>
          ))}
        </div>
      )}

      {/* Data layer */}
      <div className="mb-6">
        {isMobile ? (
          <CollapsibleSection title="Data Layer" defaultOpen={expandedSections.data}>
            <div className="p-3 space-y-3">
              {DATA_SERVICES.map((s) => (
                <div key={s.name} className={`border rounded-xl p-4 flex items-start gap-3 ${s.color}`}>
                  <span className="text-2xl">{s.icon}</span>
                  <div>
                    <p className="text-gray-200 text-sm font-semibold">{s.label}</p>
                    <p className="text-gray-200 text-xs font-mono mt-0.5">{s.name}</p>
                    <p className="text-gray-500 text-xs mt-1">{s.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </CollapsibleSection>
        ) : (
          <>
            <SectionHeader label="Data Layer" />
            <div className="grid grid-cols-2 gap-3">
              {DATA_SERVICES.map((s) => (
                <div key={s.name} className={`border rounded-xl p-4 flex items-start gap-3 ${s.color}`}>
                  <span className="text-2xl">{s.icon}</span>
                  <div>
                    <p className="text-gray-200 text-sm font-semibold">{s.label}</p>
                    <p className="text-gray-200 text-xs font-mono mt-0.5">{s.name}</p>
                    <p className="text-gray-500 text-xs mt-1">{s.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Intelligence and Knowledge layers */}
      <div className={`${isMobile ? "space-y-4" : "grid grid-cols-1 lg:grid-cols-2 gap-4"} mb-6`}>
        {/* Intelligence layer */}
        {isMobile ? (
          <CollapsibleSection
            title="Intelligence Layer"
            subtitle="Self-improvement engine"
            defaultOpen={expandedSections.intelligence}
            borderColor="border-teal-900"
          >
            <div className="p-4 space-y-2">
              {INTELLIGENCE_ITEMS.map((item) => (
                <div key={item.name} className="flex items-center gap-2 min-h-[44px]">
                  <div className="w-2 h-2 rounded-full bg-teal-600 flex-shrink-0" />
                  <span className="text-teal-300 text-xs font-mono">{item.name}</span>
                  <span className="text-gray-600 text-xs">— {item.desc}</span>
                </div>
              ))}
            </div>
          </CollapsibleSection>
        ) : (
          <div className="border border-teal-900 rounded-xl overflow-hidden">
            <div className="bg-teal-950/30 px-4 py-3">
              <p className="text-teal-300 text-xs uppercase tracking-widest font-medium">
                Intelligence Layer
              </p>
              <p className="text-teal-600 text-xs mt-0.5">Self-improvement engine</p>
            </div>
            <div className="p-4 space-y-2">
              {INTELLIGENCE_ITEMS.map((item) => (
                <div key={item.name} className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-teal-600 flex-shrink-0" />
                  <span className="text-teal-300 text-xs font-mono">{item.name}</span>
                  <span className="text-gray-600 text-xs">— {item.desc}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Knowledge layer */}
        {isMobile ? (
          <CollapsibleSection
            title="Knowledge Engine"
            subtitle="Continuous learning pipeline"
            defaultOpen={expandedSections.knowledge}
            borderColor="border-cyan-900"
          >
            <div className="p-4 space-y-2">
              {KNOWLEDGE_ITEMS.map((item) => (
                <div key={item.name} className="flex items-center gap-2 min-h-[44px]">
                  <div className="w-2 h-2 rounded-full bg-cyan-600 flex-shrink-0" />
                  <span className="text-cyan-300 text-xs font-mono">{item.name}</span>
                  <span className="text-gray-600 text-xs">— {item.desc}</span>
                </div>
              ))}
            </div>
          </CollapsibleSection>
        ) : (
          <div className="border border-cyan-900 rounded-xl overflow-hidden">
            <div className="bg-cyan-950/20 px-4 py-3">
              <p className="text-cyan-300 text-xs uppercase tracking-widest font-medium">
                Knowledge Engine
              </p>
              <p className="text-cyan-600 text-xs mt-0.5">Continuous learning pipeline</p>
            </div>
            <div className="p-4 space-y-2">
              {KNOWLEDGE_ITEMS.map((item) => (
                <div key={item.name} className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-cyan-600 flex-shrink-0" />
                  <span className="text-cyan-300 text-xs font-mono">{item.name}</span>
                  <span className="text-gray-600 text-xs">— {item.desc}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* External services */}
      <div className="mb-6">
        {isMobile ? (
          <CollapsibleSection title="External Services" defaultOpen={expandedSections.external}>
            <div className="p-3 space-y-3">
              {EXTERNAL_SERVICES.map((s) => (
                <div key={s.name} className={`border ${s.color} rounded-xl p-4 bg-gray-900/50 flex items-start gap-3 min-h-[44px]`}>
                  <span className="text-xl">{s.icon}</span>
                  <div className="min-w-0">
                    <p className="text-gray-200 text-sm font-medium">{s.name}</p>
                    <p className="text-gray-600 text-xs font-mono mt-0.5 break-all">{s.key}</p>
                  </div>
                </div>
              ))}
            </div>
          </CollapsibleSection>
        ) : (
          <>
            <SectionHeader label="External Services" />
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
              {EXTERNAL_SERVICES.map((s) => (
                <div key={s.name} className={`border ${s.color} rounded-xl p-3 bg-gray-900/50 flex items-start gap-3`}>
                  <span className="text-xl">{s.icon}</span>
                  <div>
                    <p className="text-gray-200 text-sm font-medium">{s.name}</p>
                    <p className="text-gray-600 text-xs font-mono mt-0.5">{s.key}</p>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Database tables */}
      <div className="mb-6">
        {isMobile ? (
          <CollapsibleSection title="Database Tables" defaultOpen={expandedSections.dbTables}>
            <div className="p-3 space-y-2">
              {DB_TABLES.map((t) => (
                <div key={t.name} className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 min-h-[44px]">
                  <div className="flex items-start gap-2">
                    <span className={`text-xs px-1.5 py-0.5 rounded font-medium flex-shrink-0 mt-0.5 ${tableLayerColors[t.layer]}`}>
                      {t.layer}
                    </span>
                  </div>
                  <p className="text-gray-200 text-xs font-mono font-medium mt-1.5">{t.name}</p>
                  <p className="text-gray-500 text-xs mt-0.5">{t.desc}</p>
                </div>
              ))}
            </div>
          </CollapsibleSection>
        ) : (
          <>
            <SectionHeader label="Database Tables" />
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
              {DB_TABLES.map((t) => (
                <div key={t.name} className="bg-gray-900 border border-gray-800 rounded-lg px-3 py-2.5">
                  <div className="flex items-start gap-2">
                    <span className={`text-xs px-1.5 py-0.5 rounded font-medium flex-shrink-0 mt-0.5 ${tableLayerColors[t.layer]}`}>
                      {t.layer}
                    </span>
                  </div>
                  <p className="text-gray-200 text-xs font-mono font-medium mt-1.5">{t.name}</p>
                  <p className="text-gray-500 text-xs mt-0.5">{t.desc}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Fly.io services table */}
      <div className="mb-6">
        {isMobile ? (
          <CollapsibleSection title="Fly.io Services" defaultOpen={expandedSections.flyServices}>
            <div className="p-3 space-y-3">
              {FLY_SERVICES.map((s) => (
                <div key={s.app} className="bg-gray-900 border border-gray-800 rounded-lg p-4 min-h-[44px]">
                  <p className="text-gray-200 font-mono text-sm font-medium">{s.app}</p>
                  <div className="mt-2 grid grid-cols-2 gap-y-1.5 gap-x-4 text-xs">
                    <div>
                      <span className="text-gray-600">Type: </span>
                      <span className="text-gray-400">{s.type}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">Region: </span>
                      <span className="text-gray-500 font-mono">{s.region}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">Size: </span>
                      <span className="text-gray-500">{s.size}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">RAM: </span>
                      <span className="text-gray-500">{s.ram}</span>
                    </div>
                    <div className="col-span-2">
                      <span className="text-gray-600">Cost: </span>
                      <span className="text-yellow-400 font-mono">{s.cost}</span>
                    </div>
                  </div>
                </div>
              ))}
              <div className="bg-gray-800/30 border border-gray-800 rounded-lg px-4 py-3 flex justify-between items-center">
                <span className="text-gray-500 text-xs">Total estimated monthly cost</span>
                <span className="text-yellow-400 text-sm font-bold font-mono">~A$166/mo</span>
              </div>
            </div>
          </CollapsibleSection>
        ) : (
          <>
            <SectionHeader label="Fly.io Services" />
            <div className="border border-gray-800 rounded-xl overflow-hidden">
              <div className="grid grid-cols-5 bg-gray-800/50 px-4 py-2.5 text-xs text-gray-500 uppercase tracking-wider font-medium">
                <span>App Name</span>
                <span>Type</span>
                <span>Region</span>
                <span>Size</span>
                <span>Cost</span>
              </div>
              <div className="divide-y divide-gray-800">
                {FLY_SERVICES.map((s) => (
                  <div key={s.app} className="grid grid-cols-5 px-4 py-3 text-sm hover:bg-gray-800/30 transition-colors">
                    <span className="text-gray-200 font-mono text-xs">{s.app}</span>
                    <span className="text-gray-400 text-xs">{s.type}</span>
                    <span className="text-gray-500 text-xs font-mono">{s.region}</span>
                    <span className="text-gray-500 text-xs">{s.size}</span>
                    <span className="text-yellow-400 text-xs font-mono">{s.cost}</span>
                  </div>
                ))}
              </div>
              <div className="px-4 py-3 bg-gray-800/30 border-t border-gray-800 flex justify-between items-center">
                <span className="text-gray-500 text-xs">Total estimated monthly cost</span>
                <span className="text-yellow-400 text-sm font-bold font-mono">~A$166/mo</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}