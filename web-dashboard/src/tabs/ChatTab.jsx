import { useState, useEffect, useRef, useCallback } from "react";
import { sendChatMessage } from "../api.js";

const STORAGE_KEY = "forge_chat";
const FILES_KEY = "forge_files";
const MEMORY_KEY = "forge_memory";

const QUICK_STARTS = [
  "What can The Forge build?",
  "How do I deploy to Fly.io?",
  "What's in my current build?",
  "Explain the 7-stage pipeline",
];

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

function MessageBubble({ msg }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-purple-800 flex items-center justify-center text-xs font-bold text-purple-200 flex-shrink-0 mr-2 mt-0.5">
          F
        </div>
      )}
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm ${
          isUser
            ? "bg-purple-700 text-white rounded-tr-sm"
            : "bg-gray-800 text-gray-200 rounded-tl-sm"
        }`}
      >
        <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
        {msg.timestamp && (
          <p className={`text-xs mt-1 ${isUser ? "text-purple-300" : "text-gray-500"}`}>
            {new Date(msg.timestamp).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </p>
        )}
      </div>
    </div>
  );
}

export default function ChatTab() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    setMessages(loadMessages());
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

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

      try {
        const memoryNotes = getMemoryContext();
        const filesContext = getFilesContext();

        // Build message history for API (exclude local metadata)
        const apiMessages = updated.map((m) => ({
          role: m.role,
          content: m.content,
        }));

        const response = await sendChatMessage(apiMessages, memoryNotes, filesContext);
        const assistantContent =
          response?.content ||
          response?.message ||
          response?.response ||
          "I received your message but couldn't parse the response.";

        const assistantMsg = {
          id: `${Date.now()}-assistant`,
          role: "assistant",
          content: assistantContent,
          timestamp: new Date().toISOString(),
        };
        persistMessages([...updated, assistantMsg]);
      } catch (err) {
        let content;
        if (err.message.includes("404")) {
          content =
            "The /forge/chat endpoint is not yet implemented on the backend. Once deployed, I'll be able to answer questions about The Forge, your builds, and the full agent portfolio.";
        } else {
          content = `Error: ${err.message}. Make sure the API is running and VITE_API_SECRET_KEY is set.`;
        }
        const errMsg = {
          id: `${Date.now()}-error`,
          role: "assistant",
          content,
          timestamp: new Date().toISOString(),
        };
        persistMessages([...updated, errMsg]);
      } finally {
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
    <div className="flex flex-col h-full -m-6 min-h-0">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between flex-shrink-0">
        <div>
          <h2 className="font-['Bebas_Neue'] text-2xl text-gray-100 tracking-widest">
            FORGE ASSISTANT
          </h2>
          <p className="text-gray-500 text-xs mt-0.5">
            Specialist in The Forge pipeline and The Office agent portfolio
          </p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clearChat}
            className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
          >
            Clear history
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-6 text-center">
            <div className="w-16 h-16 rounded-2xl bg-purple-900/30 border border-purple-800 flex items-center justify-center">
              <span className="text-3xl">⚒</span>
            </div>
            <div>
              <p className="text-gray-300 font-semibold text-lg mb-1">Forge Assistant</p>
              <p className="text-gray-500 text-sm max-w-xs">
                Ask me anything about The Forge, your builds, or the agent portfolio.
              </p>
            </div>

            {/* Quick-start buttons */}
            <div className="grid grid-cols-2 gap-2 max-w-sm w-full">
              {QUICK_STARTS.map((q) => (
                <button
                  key={q}
                  onClick={() => sendMessage(q)}
                  className="text-left px-3 py-2.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-gray-600 rounded-xl text-gray-400 hover:text-gray-200 text-xs transition-colors leading-snug"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}

        {loading && (
          <div className="flex justify-start mb-3">
            <div className="w-7 h-7 rounded-full bg-purple-800 flex items-center justify-center text-xs font-bold text-purple-200 flex-shrink-0 mr-2 mt-0.5">
              F
            </div>
            <div className="bg-gray-800 rounded-2xl rounded-tl-sm">
              <TypingIndicator />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="flex-shrink-0 px-6 py-4 border-t border-gray-800">
        {messages.length > 0 && (
          <div className="flex gap-2 mb-3 overflow-x-auto pb-1">
            {QUICK_STARTS.map((q) => (
              <button
                key={q}
                onClick={() => sendMessage(q)}
                disabled={loading}
                className="flex-shrink-0 text-xs px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-400 hover:text-gray-200 rounded-full transition-colors disabled:opacity-50"
              >
                {q}
              </button>
            ))}
          </div>
        )}

        <div className="flex items-end gap-3">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message Forge Assistant... (Enter to send, Shift+Enter for newline)"
            rows={1}
            className="flex-1 bg-gray-800 border border-gray-700 rounded-2xl px-4 py-3 text-gray-100 placeholder-gray-600 text-sm focus:border-purple-600 focus:outline-none transition-colors resize-none max-h-32 overflow-y-auto"
            style={{ minHeight: "48px" }}
            onInput={(e) => {
              e.target.style.height = "auto";
              e.target.style.height = Math.min(e.target.scrollHeight, 128) + "px";
            }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || loading}
            className="w-12 h-12 bg-purple-600 hover:bg-purple-700 disabled:opacity-40 disabled:cursor-not-allowed rounded-2xl flex items-center justify-center transition-colors flex-shrink-0"
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
