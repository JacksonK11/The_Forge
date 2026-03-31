import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { sendChatMessageStream } from "../api.js";

const STORAGE_KEY = "forge_chat";
const FILES_KEY = "forge_files";
const MEMORY_KEY = "forge_memory";

const QUICK_STARTS = [
  "What can The Forge build?",
  "What should I upgrade in my agents?",
  "What's in my current build?",
  "Suggest improvements to my latest agent",
];

// Parse ```upgrade {...} ``` blocks from assistant message content.
// Returns { suggestions: [{run_id, description}], cleanContent: string }
function parseUpgradeBlocks(content) {
  const suggestions = [];
  const cleaned = content.replace(/```upgrade\n([\s\S]*?)```/g, (_, json) => {
    try {
      const parsed = JSON.parse(json.trim());
      if (parsed.run_id && parsed.description) {
        suggestions.push(parsed);
      }
    } catch {
      // malformed JSON — skip
    }
    return ""; // remove block from displayed text
  }).trim();
  return { suggestions, cleanContent: cleaned };
}

function loadMessages() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveMessages(msgs) {
  try {
    // Keep last 100 messages to avoid filling storage
    const trimmed = msgs.slice(-100);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch {
    // storage full
  }
}

function getMemoryContext() {
  try {
    const raw = localStorage.getItem(MEMORY_KEY);
    const notes = raw ? JSON.parse(raw) : [];
    if (notes.length === 0) return "";
    return notes.map((n) => n.text).join("\n\n");
  } catch {
    return "";
  }
}

function getFilesContext() {
  try {
    const raw = localStorage.getItem(FILES_KEY);
    const files = raw ? JSON.parse(raw) : [];
    if (files.length === 0) return "";
    return files
      .map((f) => `- ${f.name} (${f.type || "unknown"})${f.description ? `: ${f.description}` : ""}`)
      .join("\n");
  } catch {
    return "";
  }
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 px-4 py-3">
      <div className="w-2 h-2 bg-gray-500 rounded-full typing-dot" />
      <div className="w-2 h-2 bg-gray-500 rounded-full typing-dot" />
      <div className="w-2 h-2 bg-gray-500 rounded-full typing-dot" />
    </div>
  );
}

function MessageBubble({ msg, isMobile, onUpgrade }) {
  const isUser = msg.role === "user";
  const maxWidth = isMobile ? "max-w-[90%]" : "max-w-[75%]";

  const { suggestions, cleanContent } = !isUser
    ? parseUpgradeBlocks(msg.content)
    : { suggestions: [], cleanContent: msg.content };

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-purple-800 flex items-center justify-center text-xs font-bold text-purple-200 flex-shrink-0 mr-2 mt-0.5">
          F
        </div>
      )}
      <div className={`${maxWidth} flex flex-col gap-2`}>
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm ${
            isUser
              ? "bg-purple-700 text-white rounded-tr-sm"
              : "bg-gray-800 text-gray-200 rounded-tl-sm"
          }`}
        >
          <div className="leading-relaxed overflow-x-auto">
            <div className="whitespace-pre-wrap min-w-0">{cleanContent}</div>
          </div>
          {msg.timestamp && (
            <p className={`text-xs mt-1 ${isUser ? "text-purple-300" : "text-gray-500"}`}>
              {new Date(msg.timestamp).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </p>
          )}
        </div>

        {/* Upgrade suggestion buttons */}
        {suggestions.map((s, i) => (
          <button
            key={i}
            onClick={() => onUpgrade(s)}
            className="flex items-start gap-2 bg-purple-900/30 hover:bg-purple-900/50 border border-purple-700/50 hover:border-purple-600 rounded-xl px-3 py-2.5 text-left transition-colors group"
          >
            <span className="text-purple-400 mt-0.5 flex-shrink-0 text-base leading-none">⚡</span>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-purple-300 group-hover:text-purple-200 mb-0.5">
                Send to Upgrade
              </p>
              <p className="text-xs text-gray-400 group-hover:text-gray-300 line-clamp-2 leading-snug">
                {s.description.length > 120 ? s.description.slice(0, 120) + "…" : s.description}
              </p>
            </div>
            <span className="text-purple-500 group-hover:text-purple-300 text-sm ml-auto flex-shrink-0 self-center">→</span>
          </button>
        ))}
      </div>
    </div>
  );
}

const TOOL_LABELS = {
  get_file_content: "Reading file content...",
  search_file_content: "Searching builds...",
};

export default function ChatTab({ isMobile = false }) {
  const navigate = useNavigate();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  // Streaming state: { content: string, toolCalls: string[] } | null
  const [streamingMsg, setStreamingMsg] = useState(null);
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  function handleUpgrade({ run_id, description }) {
    const params = new URLSearchParams({ run_id, description });
    navigate(`/upgrade?${params.toString()}`);
  }

  useEffect(() => {
    setMessages(loadMessages());
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, streamingMsg]);

  function persistMessages(msgs) {
    setMessages(msgs);
    saveMessages(msgs);
  }

  const sendMessage = useCallback(
    async (text) => {
      const userMsg = {
        id: `${Date.now()}-user`,
        role: "user",
        content: text,
        timestamp: new Date().toISOString(),
      };
      const updated = [...messages, userMsg];
      persistMessages(updated);
      setLoading(true);
      setStreamingMsg({ content: "", toolCalls: [] });

      let finalContent = "";

      try {
        const memoryNotes = getMemoryContext();
        const filesContext = getFilesContext();
        const apiMessages = updated.map((m) => ({ role: m.role, content: m.content }));

        await sendChatMessageStream(apiMessages, memoryNotes, filesContext, (event) => {
          if (event.type === "text_delta") {
            finalContent += event.text;
            setStreamingMsg((prev) => prev ? { ...prev, content: prev.content + event.text } : null);
          } else if (event.type === "tool_use") {
            setStreamingMsg((prev) =>
              prev ? { ...prev, toolCalls: [...prev.toolCalls, event.name] } : null
            );
          } else if (event.type === "done" || event.type === "error") {
            // Finalized in the finally block
          }
        });

        const assistantMsg = {
          id: `${Date.now()}-assistant`,
          role: "assistant",
          content: finalContent || "I couldn't generate a response. Please try again.",
          timestamp: new Date().toISOString(),
        };
        persistMessages([...updated, assistantMsg]);
      } catch (err) {
        const content = `Error: ${err.message}. Make sure the API is running and VITE_API_SECRET_KEY is set.`;
        const errMsg = {
          id: `${Date.now()}-error`,
          role: "assistant",
          content,
          timestamp: new Date().toISOString(),
        };
        persistMessages([...updated, errMsg]);
      } finally {
        setStreamingMsg(null);
        setLoading(false);
      }
    },
    [messages]
  );

  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    await sendMessage(text);
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function clearChat() {
    if (confirm("Clear chat history?")) {
      persistMessages([]);
    }
  }

  return (
    <div className={`flex flex-col h-full min-h-0 ${isMobile ? "" : "-m-6"}`}>
      {/* Header */}
      <div className={`${isMobile ? "px-4 py-3" : "px-6 py-4"} border-b border-gray-800 flex items-center justify-between flex-shrink-0`}>
        <div>
          <h2 className={`font-['Bebas_Neue'] text-gray-100 tracking-widest ${isMobile ? "text-xl" : "text-2xl"}`}>
            FORGE ASSISTANT
          </h2>
          <p className={`text-gray-500 mt-0.5 ${isMobile ? "text-[10px]" : "text-xs"}`}>
            {isMobile
              ? "Ask about The Forge & agents"
              : "Specialist in The Forge pipeline and The Office agent portfolio"}
          </p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clearChat}
            className="text-xs text-gray-600 hover:text-gray-400 transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
          >
            Clear
          </button>
        )}
      </div>

      {/* Messages */}
      <div className={`flex-1 overflow-y-auto ${isMobile ? "px-3 py-3" : "px-6 py-4"}`}>
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-6 text-center">
            <div className="w-16 h-16 rounded-2xl bg-purple-900/30 border border-purple-800 flex items-center justify-center">
              <span className="text-3xl">⚒</span>
            </div>
            <div>
              <p className="text-gray-300 font-semibold text-lg mb-1">Forge Assistant</p>
              <p className={`text-gray-500 text-sm ${isMobile ? "max-w-[280px]" : "max-w-xs"}`}>
                Ask me anything about The Forge, your builds, or the agent portfolio.
              </p>
            </div>

            {/* Quick-start buttons */}
            <div className={`gap-2 w-full ${isMobile ? "grid grid-cols-1 max-w-xs" : "grid grid-cols-2 max-w-sm"}`}>
              {QUICK_STARTS.map((q) => (
                <button
                  key={q}
                  onClick={() => sendMessage(q)}
                  className={`text-left bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-gray-600 rounded-xl text-gray-400 hover:text-gray-200 text-xs transition-colors leading-snug ${
                    isMobile ? "px-4 py-3 min-h-[44px]" : "px-3 py-2.5"
                  }`}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} isMobile={isMobile} onUpgrade={handleUpgrade} />
        ))}

        {/* Streaming message — live tokens + tool use indicators */}
        {streamingMsg && (
          <div className="flex justify-start mb-3">
            <div className="w-7 h-7 rounded-full bg-purple-800 flex items-center justify-center text-xs font-bold text-purple-200 flex-shrink-0 mr-2 mt-0.5">
              F
            </div>
            <div className="max-w-[75%]">
              {streamingMsg.toolCalls.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-1.5">
                  {[...new Set(streamingMsg.toolCalls)].map((tc, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 text-[10px] bg-purple-900/40 border border-purple-800/50 text-purple-300 rounded-full px-2.5 py-0.5 font-mono"
                    >
                      <span className="animate-pulse">⚙</span>
                      {TOOL_LABELS[tc] || tc}
                    </span>
                  ))}
                </div>
              )}
              <div className="bg-gray-800 text-gray-200 rounded-2xl rounded-tl-sm px-4 py-2.5 text-sm leading-relaxed">
                {streamingMsg.content ? (
                  <span className="whitespace-pre-wrap">{streamingMsg.content}</span>
                ) : (
                  <TypingIndicator />
                )}
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div
        className={`flex-shrink-0 border-t border-gray-800 ${
          isMobile
            ? "px-3 pt-3"
            : "px-6 py-4"
        }`}
        style={isMobile ? { paddingBottom: 'calc(0.75rem + env(safe-area-inset-bottom, 0px))' } : undefined}
      >
        {messages.length > 0 && (
          <div className={`flex gap-2 mb-3 overflow-x-auto pb-1 ${isMobile ? "-mx-1 px-1" : ""}`}>
            {QUICK_STARTS.map((q) => (
              <button
                key={q}
                onClick={() => sendMessage(q)}
                disabled={loading}
                className={`flex-shrink-0 text-xs bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-400 hover:text-gray-200 rounded-full transition-colors disabled:opacity-50 ${
                  isMobile ? "px-3 py-2 min-h-[36px]" : "px-3 py-1.5"
                }`}
              >
                {q}
              </button>
            ))}
          </div>
        )}

        <div className="flex items-end gap-2 sm:gap-3">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isMobile
                ? "Message Forge Assistant..."
                : "Message Forge Assistant... (Enter to send, Shift+Enter for newline)"
            }
            rows={1}
            className={`flex-1 bg-gray-800 border border-gray-700 rounded-2xl px-4 text-gray-100 placeholder-gray-600 focus:border-purple-600 focus:outline-none transition-colors resize-none max-h-32 overflow-y-auto py-3 ${
              isMobile ? "text-base" : "text-sm"
            }`}
            style={{ minHeight: isMobile ? "44px" : "48px", fontSize: isMobile ? "16px" : undefined }}
            onInput={(e) => {
              e.target.style.height = "auto";
              e.target.style.height = Math.min(e.target.scrollHeight, 128) + "px";
            }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || loading}
            className={`bg-purple-600 hover:bg-purple-700 disabled:opacity-40 disabled:cursor-not-allowed rounded-2xl flex items-center justify-center transition-colors flex-shrink-0 ${
              isMobile ? "w-[44px] h-[44px]" : "w-12 h-12"
            }`}
          >
            <svg
              className="w-5 h-5 text-white"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 19V5m0 0l-7 7m7-7l7 7"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}