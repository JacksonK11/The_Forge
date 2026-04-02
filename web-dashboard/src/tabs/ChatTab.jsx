import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { sendChatMessageStream } from "../api.js";

const STORAGE_KEY = "forge_chat";
const FILES_KEY   = "forge_files";
const MEMORY_KEY  = "forge_memory";

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
  const cleaned = content
    .replace(/```upgrade\n([\s\S]*?)```/g, (_, json) => {
      try {
        const parsed = JSON.parse(json.trim());
        if (parsed.run_id && parsed.description) {
          suggestions.push(parsed);
        }
      } catch {
        // malformed JSON — skip
      }
      return "";
    })
    .trim();
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
    const trimmed = msgs.slice(-100);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch {
    // storage full
  }
}

function getMemoryContext() {
  try {
    const raw   = localStorage.getItem(MEMORY_KEY);
    const notes = raw ? JSON.parse(raw) : [];
    if (notes.length === 0) return "";
    return notes.map((n) => n.text).join("\n\n");
  } catch {
    return "";
  }
}

function getFilesContext() {
  try {
    const raw   = localStorage.getItem(FILES_KEY);
    const files = raw ? JSON.parse(raw) : [];
    if (files.length === 0) return "";
    return files
      .map((f) => `- ${f.name} (${f.type || "unknown"})${f.description ? `: ${f.description}` : ""}`)
      .join("\n");
  } catch {
    return "";
  }
}

// Relative time helper
function relTime(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60)    return "just now";
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// Detect if a content block looks like it contains code
function detectCodeBlock(text) {
  const codeBlockMatch = text.match(/```(\w*)\n?([\s\S]*?)```/g);
  return codeBlockMatch;
}

// Render message content with code block detection
function RichContent({ content }) {
  const parts = content.split(/(```[\w]*\n?[\s\S]*?```)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("```")) {
          const langMatch = part.match(/^```(\w*)\n?/);
          const lang      = langMatch?.[1] || "";
          const code      = part.replace(/^```\w*\n?/, "").replace(/```$/, "");
          return (
            <div key={i} style={{ margin: "10px 0", borderRadius: 8, overflow: "hidden", border: "1px solid #162440" }}>
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "6px 12px",
                background: "#070b18",
                borderBottom: "1px solid #0f1c35",
              }}>
                <span style={{ fontFamily: "'Space Mono', monospace", fontSize: 9, color: "#a78bfa", letterSpacing: "0.1em", textTransform: "uppercase" }}>
                  {lang || "code"}
                </span>
                <button
                  onClick={() => navigator.clipboard?.writeText(code)}
                  style={{ fontFamily: "'Space Mono', monospace", fontSize: 9, color: "#3a5a78", background: "none", border: "none", cursor: "pointer", padding: "2px 6px", borderRadius: 4, transition: "color 0.12s" }}
                  onMouseEnter={(e) => e.currentTarget.style.color = "#a78bfa"}
                  onMouseLeave={(e) => e.currentTarget.style.color = "#3a5a78"}
                >
                  Copy
                </button>
              </div>
              <pre style={{
                margin: 0, padding: "12px 14px",
                background: "#050810",
                fontSize: 11, lineHeight: 1.6,
                color: "#dde8f8",
                fontFamily: "'IBM Plex Mono', 'Space Mono', monospace",
                overflowX: "auto",
                whiteSpace: "pre",
              }}>
                {code}
              </pre>
            </div>
          );
        }
        return (
          <span key={i} style={{ whiteSpace: "pre-wrap" }}>{part}</span>
        );
      })}
    </>
  );
}

function TypingIndicator() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "8px 4px" }}>
      <div className="w-2 h-2 rounded-full typing-dot" style={{ background: "#3a5a78" }} />
      <div className="w-2 h-2 rounded-full typing-dot" style={{ background: "#3a5a78" }} />
      <div className="w-2 h-2 rounded-full typing-dot" style={{ background: "#3a5a78" }} />
    </div>
  );
}

// Streaming cursor
function StreamCursor() {
  return (
    <span
      style={{
        display: "inline-block", width: 2, height: "1em",
        background: "#a78bfa", verticalAlign: "text-bottom",
        animation: "pulse 1s infinite", marginLeft: 1,
      }}
    />
  );
}

const TOOL_LABELS = {
  get_file_content:    "Reading file content",
  search_file_content: "Searching builds",
};

function MessageBubble({ msg, isMobile, onUpgrade }) {
  const isUser = msg.role === "user";

  const { suggestions, cleanContent } = !isUser
    ? parseUpgradeBlocks(msg.content)
    : { suggestions: [], cleanContent: msg.content };

  if (isUser) {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <div style={{ maxWidth: isMobile ? "90%" : "75%", display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
          <div style={{
            background: "linear-gradient(135deg, #7c3aed, #6d28d9)",
            borderRadius: "16px 16px 4px 16px",
            padding: "10px 14px",
            border: "1px solid rgba(124,58,237,0.4)",
          }}>
            <div style={{ fontSize: 13, color: "white", lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
              {cleanContent}
            </div>
          </div>
          {msg.timestamp && (
            <span style={{ fontFamily: "'Space Mono', monospace", fontSize: 9, color: "#1e3448", marginTop: 4 }}>
              {relTime(msg.timestamp)}
            </span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 12 }}>
      <div style={{
        width: 28, height: 28, borderRadius: "50%",
        background: "linear-gradient(135deg, rgba(124,58,237,0.4), rgba(167,139,250,0.2))",
        border: "1px solid rgba(124,58,237,0.4)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 11, fontWeight: 700, color: "#a78bfa",
        flexShrink: 0, marginRight: 10, marginTop: 2,
        fontFamily: "'Bebas Neue', sans-serif",
      }}>
        F
      </div>
      <div style={{ maxWidth: isMobile ? "88%" : "75%", display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{
          background: "#0b1020",
          border: "1px solid #162440",
          borderRadius: "16px 16px 16px 4px",
          padding: "10px 14px",
        }}>
          <div style={{ fontSize: 13, color: "#dde8f8", lineHeight: 1.65, overflow: "hidden" }}>
            <RichContent content={cleanContent} />
          </div>
          {msg.timestamp && (
            <p style={{ fontFamily: "'Space Mono', monospace", fontSize: 9, color: "#1e3448", marginTop: 6 }}>
              {relTime(msg.timestamp)}
            </p>
          )}
        </div>

        {/* Upgrade suggestion cards */}
        {suggestions.map((s, i) => (
          <button
            key={i}
            onClick={() => onUpgrade(s)}
            style={{
              width: "100%", textAlign: "left", cursor: "pointer",
              background: "rgba(124,58,237,0.06)",
              border: "1px solid rgba(124,58,237,0.3)",
              borderRadius: 12, padding: "14px 16px",
              transition: "all 0.15s",
              position: "relative", overflow: "hidden",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "rgba(124,58,237,0.12)";
              e.currentTarget.style.borderColor = "rgba(124,58,237,0.6)";
              e.currentTarget.style.transform = "translateY(-1px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "rgba(124,58,237,0.06)";
              e.currentTarget.style.borderColor = "rgba(124,58,237,0.3)";
              e.currentTarget.style.transform = "translateY(0)";
            }}
          >
            {/* Gradient top bar */}
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: "linear-gradient(90deg, #7c3aed, #a78bfa, transparent)" }} />
            <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
              <span style={{ fontSize: 16, flexShrink: 0 }}>⚡</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <span style={{
                    fontFamily: "'Space Mono', monospace", fontSize: 9, fontWeight: 700,
                    letterSpacing: "0.1em", color: "#a78bfa",
                    background: "rgba(124,58,237,0.2)", border: "1px solid rgba(124,58,237,0.35)",
                    padding: "2px 7px", borderRadius: 3,
                  }}>
                    UPGRADE SUGGESTION
                  </span>
                </div>
                <p style={{ fontSize: 12, color: "#7a9ab8", lineHeight: 1.6, marginBottom: 10 }}>
                  {s.description.length > 160 ? s.description.slice(0, 160) + "…" : s.description}
                </p>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{
                    fontFamily: "'Space Mono', monospace", fontSize: 10, fontWeight: 700,
                    color: "#a78bfa", letterSpacing: "0.04em",
                  }}>
                    Send to Upgrade →
                  </span>
                </div>
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

export default function ChatTab({ isMobile = false }) {
  const navigate      = useNavigate();
  const [messages, setMessages]     = useState([]);
  const [input, setInput]           = useState("");
  const [loading, setLoading]       = useState(false);
  const [streamingMsg, setStreamingMsg] = useState(null);
  const [charCount, setCharCount]   = useState(0);
  const messagesEndRef = useRef(null);
  const textareaRef    = useRef(null);

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
        id:        `${Date.now()}-user`,
        role:      "user",
        content:   text,
        timestamp: new Date().toISOString(),
      };
      const updated = [...messages, userMsg];
      persistMessages(updated);
      setLoading(true);
      setStreamingMsg({ content: "", toolCalls: [] });

      let finalContent = "";

      try {
        const memoryNotes  = getMemoryContext();
        const filesContext = getFilesContext();
        const apiMessages  = updated.map((m) => ({ role: m.role, content: m.content }));

        await sendChatMessageStream(apiMessages, memoryNotes, filesContext, (event) => {
          if (event.type === "text_delta") {
            finalContent += event.text;
            setStreamingMsg((prev) =>
              prev ? { ...prev, content: prev.content + event.text } : null
            );
          } else if (event.type === "tool_use") {
            setStreamingMsg((prev) =>
              prev ? { ...prev, toolCalls: [...prev.toolCalls, event.name] } : null
            );
          }
        });

        const assistantMsg = {
          id:        `${Date.now()}-assistant`,
          role:      "assistant",
          content:   finalContent || "I couldn't generate a response. Please try again.",
          timestamp: new Date().toISOString(),
        };
        persistMessages([...updated, assistantMsg]);
      } catch (err) {
        const errMsg = {
          id:        `${Date.now()}-error`,
          role:      "assistant",
          content:   `Error: ${err.message}. Make sure the API is running and VITE_API_SECRET_KEY is set.`,
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
    setCharCount(0);
    await sendMessage(text);
  }

  function handleKeyDown(e) {
    if ((e.key === "Enter" && e.metaKey) || (e.key === "Enter" && !e.shiftKey)) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleInputChange(e) {
    setInput(e.target.value);
    setCharCount(e.target.value.length);
    // Auto-resize
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
  }

  function clearChat() {
    if (confirm("Clear chat history?")) {
      persistMessages([]);
    }
  }

  const isConnected = true; // API is reachable if app loaded

  return (
    <div className={`flex flex-col h-full min-h-0 ${isMobile ? "" : "-m-6"}`}>

      {/* ── Header ── */}
      <div
        style={{
          padding: isMobile ? "12px 16px" : "14px 24px",
          borderBottom: "1px solid #0f1c35",
          flexShrink: 0,
          display: "flex", alignItems: "center", justifyContent: "space-between",
          background: "rgba(5,8,16,0.6)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10, flexShrink: 0,
            background: "linear-gradient(135deg, rgba(124,58,237,0.3), rgba(167,139,250,0.15))",
            border: "1px solid rgba(124,58,237,0.4)",
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "0 0 20px rgba(124,58,237,0.15)",
          }}>
            <span style={{ fontSize: 18 }}>⚒</span>
          </div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h2 style={{
                fontFamily: "'Bebas Neue', sans-serif",
                fontSize: isMobile ? 18 : 22,
                letterSpacing: "0.1em",
                color: "#a78bfa",
                lineHeight: 1,
                background: "linear-gradient(135deg, #c4b5fd, #a78bfa)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}>
                FORGE AI
              </h2>
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                fontFamily: "'Space Mono', monospace", fontSize: 8, fontWeight: 700,
                letterSpacing: "0.1em", padding: "3px 8px", borderRadius: 20,
                color: "var(--green)",
                background: "var(--green-d)",
                border: "1px solid rgba(0,232,122,0.25)",
              }}>
                <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--green)", display: "inline-block", animation: "pulse 2s infinite" }} />
                CONNECTED
              </span>
              {!isMobile && (
                <span style={{
                  fontFamily: "'Space Mono', monospace", fontSize: 8,
                  color: "#3a5a78", background: "#0f1629",
                  border: "1px solid #162440",
                  padding: "2px 7px", borderRadius: 4, letterSpacing: "0.04em",
                }}>
                  Claude Sonnet
                </span>
              )}
            </div>
            <p style={{
              fontFamily: "'Space Mono', monospace",
              fontSize: isMobile ? 9 : 10, color: "#3a5a78", marginTop: 3,
            }}>
              {isMobile ? "Ask about The Forge & agents" : "Specialist in The Forge pipeline · The Office agent portfolio"}
            </p>
          </div>
        </div>

        {messages.length > 0 && (
          <button
            onClick={clearChat}
            style={{
              fontFamily: "'Space Mono', monospace", fontSize: 9, color: "#3a5a78",
              background: "none", border: "1px solid #162440", borderRadius: 6,
              padding: "6px 12px", cursor: "pointer", letterSpacing: "0.06em",
              textTransform: "uppercase", transition: "all 0.15s",
              minHeight: 44, minWidth: 44, display: "flex", alignItems: "center", justifyContent: "center",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--red)"; e.currentTarget.style.color = "var(--red)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = "#162440"; e.currentTarget.style.color = "#3a5a78"; }}
          >
            Clear
          </button>
        )}
      </div>

      {/* ── Messages ── */}
      <div
        style={{
          flex: 1, overflowY: "auto",
          padding: isMobile ? "16px 12px" : "20px 24px",
        }}
      >
        {/* Empty state */}
        {messages.length === 0 && (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 24, textAlign: "center" }}>
            <div style={{
              width: 72, height: 72, borderRadius: 18,
              background: "linear-gradient(135deg, rgba(124,58,237,0.2), rgba(167,139,250,0.08))",
              border: "1px solid rgba(124,58,237,0.3)",
              display: "flex", alignItems: "center", justifyContent: "center",
              boxShadow: "0 0 40px rgba(124,58,237,0.1)",
            }}>
              <span style={{ fontSize: 32 }}>⚒</span>
            </div>
            <div>
              <p style={{ fontFamily: "'Bebas Neue', sans-serif", fontSize: 24, letterSpacing: "0.08em", color: "#dde8f8", marginBottom: 6 }}>
                FORGE ASSISTANT
              </p>
              <p style={{ fontSize: 13, color: "#3a5a78", maxWidth: isMobile ? 280 : 340, lineHeight: 1.6 }}>
                Ask me anything about The Forge, your builds, or the agent portfolio. I can read your build files and suggest upgrades.
              </p>
            </div>

            {/* Suggested prompts */}
            <div style={{
              display: "grid",
              gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr",
              gap: 8, width: "100%", maxWidth: isMobile ? 320 : 440,
            }}>
              {QUICK_STARTS.map((q) => (
                <button
                  key={q}
                  onClick={() => sendMessage(q)}
                  style={{
                    textAlign: "left", cursor: "pointer", padding: isMobile ? "14px 16px" : "12px 14px",
                    background: "#0b1020", border: "1px solid #162440",
                    borderRadius: 10, fontSize: 12, color: "#7a9ab8",
                    lineHeight: 1.5, transition: "all 0.15s",
                    fontFamily: "'Outfit', sans-serif",
                    minHeight: isMobile ? 44 : undefined,
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = "#7c3aed";
                    e.currentTarget.style.color = "#dde8f8";
                    e.currentTarget.style.background = "rgba(124,58,237,0.06)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = "#162440";
                    e.currentTarget.style.color = "#7a9ab8";
                    e.currentTarget.style.background = "#0b1020";
                  }}
                >
                  <span style={{ fontFamily: "'Space Mono', monospace", fontSize: 9, color: "#3a5a78", display: "block", marginBottom: 4, letterSpacing: "0.06em" }}>
                    SUGGESTED
                  </span>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Message list */}
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            msg={msg}
            isMobile={isMobile}
            onUpgrade={handleUpgrade}
          />
        ))}

        {/* Streaming message */}
        {streamingMsg && (
          <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 12 }}>
            <div style={{
              width: 28, height: 28, borderRadius: "50%",
              background: "linear-gradient(135deg, rgba(124,58,237,0.4), rgba(167,139,250,0.2))",
              border: "1px solid rgba(124,58,237,0.4)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 11, fontWeight: 700, color: "#a78bfa",
              flexShrink: 0, marginRight: 10, marginTop: 2,
              fontFamily: "'Bebas Neue', sans-serif",
            }}>
              F
            </div>
            <div style={{ maxWidth: isMobile ? "88%" : "75%" }}>
              {/* Tool use indicators */}
              {streamingMsg.toolCalls.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
                  {[...new Set(streamingMsg.toolCalls)].map((tc, i) => (
                    <span
                      key={i}
                      style={{
                        display: "inline-flex", alignItems: "center", gap: 5,
                        fontFamily: "'Space Mono', monospace", fontSize: 9,
                        background: "rgba(124,58,237,0.12)",
                        border: "1px solid rgba(124,58,237,0.3)",
                        color: "#a78bfa", borderRadius: 20,
                        padding: "3px 10px",
                        letterSpacing: "0.04em",
                      }}
                    >
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
                        style={{ animation: "spin 1.2s linear infinite", flexShrink: 0 }}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h5M20 20v-5h-5M4 9a9 9 0 0115 0M20 15a9 9 0 01-15 0" />
                      </svg>
                      {TOOL_LABELS[tc] || tc}
                    </span>
                  ))}
                </div>
              )}
              {/* Streaming bubble */}
              <div style={{
                background: "#0b1020",
                border: "1px solid #162440",
                borderRadius: "16px 16px 16px 4px",
                padding: "10px 14px",
              }}>
                {streamingMsg.content ? (
                  <div style={{ fontSize: 13, color: "#dde8f8", lineHeight: 1.65 }}>
                    <RichContent content={streamingMsg.content} />
                    <StreamCursor />
                  </div>
                ) : (
                  <TypingIndicator />
                )}
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* ── Input area ── */}
      <div
        style={{
          flexShrink: 0,
          borderTop: "1px solid #0f1c35",
          padding: isMobile ? "10px 12px" : "14px 24px",
          paddingBottom: isMobile ? "calc(10px + env(safe-area-inset-bottom, 0px))" : undefined,
          background: "rgba(5,8,16,0.6)",
        }}
      >
        {/* Quick prompt chips (when messages exist) */}
        {messages.length > 0 && (
          <div style={{
            display: "flex", gap: 6, marginBottom: 10,
            overflowX: "auto", paddingBottom: 2,
          }}>
            {QUICK_STARTS.map((q) => (
              <button
                key={q}
                onClick={() => sendMessage(q)}
                disabled={loading}
                style={{
                  flexShrink: 0, whiteSpace: "nowrap",
                  fontFamily: "'Space Mono', monospace", fontSize: 9,
                  background: "#0b1020", border: "1px solid #162440",
                  color: "#3a5a78", borderRadius: 20,
                  padding: isMobile ? "7px 12px" : "5px 10px",
                  minHeight: isMobile ? 36 : undefined,
                  cursor: "pointer", transition: "all 0.15s",
                  letterSpacing: "0.03em",
                  opacity: loading ? 0.4 : 1,
                }}
                onMouseEnter={(e) => {
                  if (!loading) {
                    e.currentTarget.style.borderColor = "#7c3aed";
                    e.currentTarget.style.color = "#a78bfa";
                  }
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "#162440";
                  e.currentTarget.style.color = "#3a5a78";
                }}
              >
                {q}
              </button>
            ))}
          </div>
        )}

        {/* Textarea row */}
        <div style={{ display: "flex", alignItems: "flex-end", gap: isMobile ? 8 : 10 }}>
          <div style={{ flex: 1, position: "relative" }}>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder={isMobile ? "Message Forge AI..." : "Ask anything about your builds or agents..."}
              rows={3}
              style={{
                width: "100%",
                background: "#0b1020",
                border: "1px solid #162440",
                borderRadius: 12, padding: "10px 14px",
                paddingBottom: 28,
                color: "#dde8f8",
                fontFamily: "'Outfit', sans-serif",
                fontSize: isMobile ? 16 : 13,
                lineHeight: 1.6,
                outline: "none",
                resize: "none",
                minHeight: isMobile ? 52 : 72,
                maxHeight: 140,
                overflowY: "auto",
                transition: "border-color 0.2s, box-shadow 0.2s",
              }}
              onFocus={(e) => {
                e.target.style.borderColor = "#7c3aed";
                e.target.style.boxShadow   = "0 0 0 3px rgba(124,58,237,0.12)";
              }}
              onBlur={(e) => {
                e.target.style.borderColor = "#162440";
                e.target.style.boxShadow   = "none";
              }}
            />
            {/* Footer bar inside textarea */}
            <div style={{
              position: "absolute", bottom: 0, left: 0, right: 0,
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "4px 10px 6px",
              borderTop: "1px solid #0f1c35",
              pointerEvents: "none",
            }}>
              <span style={{ fontFamily: "'Space Mono', monospace", fontSize: 8, color: "#1e3448", letterSpacing: "0.04em" }}>
                {isMobile ? "↩ send" : "⌘↩ to send · ⇧↩ newline"}
              </span>
              <span style={{
                fontFamily: "'Space Mono', monospace", fontSize: 8,
                color: charCount > 1800 ? "var(--amber)" : charCount > 2000 ? "var(--red)" : "#1e3448",
              }}>
                {charCount > 0 ? charCount : ""}
              </span>
            </div>
          </div>

          <button
            onClick={handleSend}
            disabled={!input.trim() || loading}
            style={{
              width: isMobile ? 44 : 48,
              height: isMobile ? 44 : 48,
              borderRadius: 12, flexShrink: 0,
              background: input.trim() && !loading
                ? "linear-gradient(135deg, #7c3aed, #6d28d9)"
                : "#0f1629",
              border: input.trim() && !loading
                ? "1px solid #7c3aed"
                : "1px solid #162440",
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: input.trim() && !loading ? "pointer" : "not-allowed",
              opacity: !input.trim() || loading ? 0.4 : 1,
              transition: "all 0.15s",
              boxShadow: input.trim() && !loading ? "0 4px 16px rgba(124,58,237,0.3)" : "none",
            }}
            onMouseEnter={(e) => {
              if (input.trim() && !loading) {
                e.currentTarget.style.transform = "translateY(-1px)";
                e.currentTarget.style.boxShadow = "0 6px 20px rgba(124,58,237,0.4)";
              }
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = "translateY(0)";
              e.currentTarget.style.boxShadow = input.trim() && !loading ? "0 4px 16px rgba(124,58,237,0.3)" : "none";
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 19V5m0 0l-7 7m7-7l7 7" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
