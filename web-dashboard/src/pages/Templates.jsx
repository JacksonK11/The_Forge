import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getBuildTemplates, getBuildTemplate } from "../api.js";
import { useToast } from "../context/ToastContext.jsx";

const CATEGORY_COLORS = {
  api: "bg-blue-900/50 text-blue-300 border-blue-800",
  worker: "bg-purple-900/50 text-purple-300 border-purple-800",
  dashboard: "bg-cyan-900/50 text-cyan-300 border-cyan-800",
  fullstack: "bg-emerald-900/50 text-emerald-300 border-emerald-800",
  default: "bg-gray-800 text-gray-400 border-gray-700",
};

export default function Templates() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => {
    async function fetchTemplates() {
      try {
        const data = await getBuildTemplates();
        setTemplates(Array.isArray(data) ? data : data?.templates || []);
      } catch (err) {
        addToast(err.message || "Failed to load templates.", "error");
      } finally {
        setLoading(false);
      }
    }
    fetchTemplates();
  }, [addToast]);

  async function handleSelectTemplate(id) {
    setLoadingDetail(true);
    try {
      const detail = await getBuildTemplate(id);
      setSelected(detail);
    } catch (err) {
      addToast(err.message || "Failed to load template.", "error");
    } finally {
      setLoadingDetail(false);
    }
  }

  function handleUseTemplate() {
    if (!selected) return;
    const bp = selected.blueprint_text || selected.blueprint || "";
    navigate(`/?template=${encodeURIComponent(selected.id)}&blueprint=${encodeURIComponent(bp)}`);
  }

  const filtered = templates.filter(
    (t) =>
      !search ||
      (t.name || t.title || "").toLowerCase().includes(search.toLowerCase()) ||
      (t.description || "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="font-['Bebas_Neue'] text-3xl text-white tracking-widest">Templates</h1>
        <p className="text-gray-500 text-sm mt-1">
          Pre-built blueprints to start a new agent faster.
        </p>
      </div>

      <div className="mb-4">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search templates..."
          className="w-full max-w-sm bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500 transition-colors"
        />
      </div>

      {loading ? (
        <div className="flex items-center justify-center p-12">
          <div className="w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-12 text-center">
          <p className="text-gray-500 text-sm">No templates found.</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((tpl) => {
            const catCls = CATEGORY_COLORS[tpl.category] || CATEGORY_COLORS.default;
            return (
              <button
                key={tpl.id}
                onClick={() => handleSelectTemplate(tpl.id)}
                className="text-left rounded-xl border border-gray-800 bg-gray-900 p-5 hover:border-purple-700/50 hover:bg-purple-900/10 transition-all duration-150 space-y-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-white leading-snug">
                    {tpl.name || tpl.title || tpl.id}
                  </p>
                  {tpl.category && (
                    <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium flex-shrink-0 ${catCls}`}>
                      {tpl.category}
                    </span>
                  )}
                </div>
                {tpl.description && (
                  <p className="text-xs text-gray-500 line-clamp-2">{tpl.description}</p>
                )}
                {tpl.stack && (
                  <p className="text-xs text-gray-600 font-['IBM_Plex_Mono']">{tpl.stack}</p>
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* Detail panel */}
      {(selected || loadingDetail) && (
        <div
          className="fixed inset-0 z-50 bg-black/60 flex items-end sm:items-center justify-center p-4"
          onClick={() => setSelected(null)}
        >
          <div
            className="slide-up sm:slide-up-none w-full sm:max-w-lg bg-gray-900 rounded-xl border border-gray-800 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {loadingDetail ? (
              <div className="flex items-center justify-center p-12">
                <div className="w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
              </div>
            ) : selected ? (
              <>
                <div className="px-6 pt-6 pb-4 border-b border-gray-800">
                  <div className="flex items-start justify-between gap-4">
                    <h2 className="font-['Bebas_Neue'] text-xl text-white tracking-widest">
                      {selected.name || selected.title || selected.id}
                    </h2>
                    <button
                      onClick={() => setSelected(null)}
                      className="w-7 h-7 flex items-center justify-center rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors flex-shrink-0"
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                  {selected.description && (
                    <p className="text-sm text-gray-400 mt-2">{selected.description}</p>
                  )}
                </div>
                {selected.blueprint_text && (
                  <div className="px-6 py-4 max-h-64 overflow-y-auto">
                    <pre className="font-['IBM_Plex_Mono'] text-xs text-gray-400 whitespace-pre-wrap">{selected.blueprint_text}</pre>
                  </div>
                )}
                <div className="px-6 pb-6 pt-4 flex gap-3">
                  <button
                    onClick={() => setSelected(null)}
                    className="flex-1 rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm"
                  >
                    Close
                  </button>
                  <button
                    onClick={handleUseTemplate}
                    className="flex-1 rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-purple-600 hover:bg-purple-500 text-white text-sm"
                  >
                    Use Template
                  </button>
                </div>
              </>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
