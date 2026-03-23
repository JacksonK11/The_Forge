import { useState, useEffect } from "react";

const STORAGE_KEY = "forge_memory";

function loadNotes() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveNotes(notes) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notes));
  } catch {
    // storage full
  }
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

const PLACEHOLDER_TEXT = `My Fly.io region: syd (Sydney, Australia)
Agent naming convention: kebab-case with "the-" prefix e.g. the-forge, the-buildright
Preferred Claude model for reasoning: claude-opus-4-6
Preferred Claude model for classification: claude-haiku-4-5-20251001
Embeddings: text-embedding-3-small (OpenAI)
All agents deployed to Fly.io, GitHub org: jacksonkhoury-ai
Telegram notifications: @jackson_khoury
Timezone: Australia/Sydney`;

export default function MemoryTab({ isMobile = false }) {
  const [notes, setNotes] = useState([]);
  const [inputText, setInputText] = useState(PLACEHOLDER_TEXT);

  useEffect(() => {
    setNotes(loadNotes());
  }, []);

  function persistNotes(updated) {
    setNotes(updated);
    saveNotes(updated);
  }

  function handleSave() {
    const text = inputText.trim();
    if (!text) return;
    const note = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      text,
      createdAt: new Date().toISOString(),
    };
    persistNotes([note, ...loadNotes()]);
    setInputText("");
  }

  function deleteNote(id) {
    persistNotes(notes.filter((n) => n.id !== id));
  }

  function clearAll() {
    if (confirm("Clear all memory notes? This cannot be undone.")) {
      persistNotes([]);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      handleSave();
    }
  }

  return (
    <div className={isMobile ? "w-full px-2" : "max-w-3xl mx-auto"}>
      <div className={`flex items-start justify-between ${isMobile ? "mb-4" : "mb-6"}`}>
        <div className={isMobile ? "flex-1 min-w-0 mr-2" : ""}>
          <h2 className={`font-['Bebas_Neue'] text-gray-100 tracking-widest ${isMobile ? "text-3xl" : "text-4xl"}`}>
            MEMORY
          </h2>
          <p className={`text-gray-500 mt-1 ${isMobile ? "text-xs leading-relaxed" : "text-sm"}`}>
            Notes are injected into every AI conversation. Use for: your Fly.io region, naming
            conventions, deployed agent URLs, preferences.
          </p>
        </div>
        {notes.length > 0 && (
          <button
            onClick={clearAll}
            className={`text-xs text-red-500 hover:text-red-400 border border-red-900 hover:border-red-700 rounded-lg transition-colors flex-shrink-0 ${
              isMobile ? "px-3 py-2 min-h-[44px] min-w-[44px] flex items-center justify-center" : "px-3 py-1.5"
            }`}
          >
            Clear All
          </button>
        )}
      </div>

      {/* Input area */}
      <div className={`bg-gray-900 border border-gray-800 rounded-lg overflow-hidden ${isMobile ? "mb-4" : "mb-6"}`}>
        <div className="px-4 pt-3 pb-1">
          <p className="text-gray-600 text-xs font-medium uppercase tracking-wider">
            {isMobile ? "New Note — tap Save" : "New Note — Ctrl+Enter to save"}
          </p>
        </div>
        <textarea
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Enter a memory note..."
          rows={isMobile ? 6 : 8}
          className={`w-full bg-transparent px-4 py-3 text-gray-200 font-['IBM_Plex_Mono'] placeholder-gray-700 focus:outline-none resize-y ${
            isMobile ? "text-base leading-relaxed" : "text-sm"
          }`}
        />
        <div className="px-4 py-3 border-t border-gray-800 flex items-center justify-between">
          <span className="text-gray-600 text-xs">
            {inputText.trim().split("\n").filter(Boolean).length} lines
          </span>
          <button
            onClick={handleSave}
            disabled={!inputText.trim()}
            className={`bg-purple-600 hover:bg-purple-700 disabled:opacity-40 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors ${
              isMobile
                ? "px-5 py-2.5 text-base min-h-[44px]"
                : "px-4 py-1.5 text-sm"
            }`}
          >
            Save Note
          </button>
        </div>
      </div>

      {/* Notes list */}
      {notes.length === 0 ? (
        <div className={`text-center text-gray-600 text-sm ${isMobile ? "py-6" : "py-8"}`}>
          No memory notes saved yet. Add your first note above.
        </div>
      ) : (
        <div className="space-y-3">
          {notes.map((note) => (
            <div
              key={note.id}
              className="border border-gray-800 rounded-lg bg-gray-900 overflow-hidden"
            >
              <div className={`flex items-center justify-between border-b border-gray-800 ${
                isMobile ? "px-3 py-3" : "px-4 py-2.5"
              }`}>
                <span className={`text-gray-500 font-mono ${isMobile ? "text-xs" : "text-xs"}`}>
                  {formatDate(note.createdAt)}
                </span>
                <button
                  onClick={() => deleteNote(note.id)}
                  className={`text-gray-600 hover:text-red-400 transition-colors ${
                    isMobile
                      ? "text-sm min-h-[44px] min-w-[44px] flex items-center justify-center -mr-1"
                      : "text-xs"
                  }`}
                >
                  Delete
                </button>
              </div>
              <pre className={`font-['IBM_Plex_Mono'] whitespace-pre-wrap text-gray-300 ${
                isMobile ? "px-3 py-3 text-sm leading-relaxed" : "px-4 py-3 text-sm"
              }`}>
                {note.text}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}