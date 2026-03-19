"use client";
import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send,
  Zap,
  Activity,
  Server,
  FileText,
  Gauge,
  Shield,
  Wifi,
  WifiOff,
  Bot,
  User,
  Loader2,
  Terminal,
} from "lucide-react";
import Markdown from "react-markdown";
import { useNexusWebSocket } from "@/hooks/useNexusWebSocket";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  tools?: string[];
}

const SUGGESTED_QUERIES = [
  { icon: <Server size={16} />, text: "Why is payment-service crashing?", color: "from-red-500/20 to-red-600/10" },
  { icon: <Gauge size={16} />, text: "Show me CPU metrics for auth-service", color: "from-amber-500/20 to-amber-600/10" },
  { icon: <Activity size={16} />, text: "What caused the latency spike?", color: "from-blue-500/20 to-blue-600/10" },
  { icon: <FileText size={16} />, text: "Check runbook for OOM errors", color: "from-emerald-500/20 to-emerald-600/10" },
];

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const {
    isConnected,
    sessionId,
    streamingText,
    isStreaming,
    activeTools,
    sendMessage,
  } = useNexusWebSocket();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(scrollToBottom, [messages, streamingText]);

  const handleSend = (text?: string) => {
    const message = text || inputValue.trim();
    if (!message || isStreaming) return;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      content: message,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInputValue("");

    sendMessage(message, (completedText) => {
      const assistantMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: completedText,
        timestamp: new Date(),
        tools: [...activeTools],
      };
      setMessages((prev) => [...prev, assistantMsg]);
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-screen" style={{ background: "var(--nexus-bg-primary)" }}>
      {/* ─── Sidebar ─── */}
      <aside
        className="w-72 flex flex-col border-r"
        style={{
          background: "var(--nexus-bg-secondary)",
          borderColor: "var(--nexus-border)",
        }}
      >
        {/* Logo */}
        <div className="p-6 flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center glow-accent"
            style={{ background: "linear-gradient(135deg, var(--nexus-gradient-start), var(--nexus-gradient-end))" }}
          >
            <Zap size={22} color="white" />
          </div>
          <div>
            <h1 className="text-lg font-bold gradient-text">NexusOps</h1>
            <p className="text-xs" style={{ color: "var(--nexus-text-muted)" }}>
              AI DevOps Ops Center
            </p>
          </div>
        </div>

        {/* Status */}
        <div className="px-6 py-3">
          <div className="glass-card p-3 rounded-lg">
            <div className="flex items-center gap-2 text-sm">
              {isConnected ? (
                <>
                  <Wifi size={14} style={{ color: "var(--nexus-success)" }} />
                  <span style={{ color: "var(--nexus-success)" }}>Connected</span>
                </>
              ) : (
                <>
                  <WifiOff size={14} style={{ color: "var(--nexus-danger)" }} />
                  <span style={{ color: "var(--nexus-danger)" }}>Disconnected</span>
                </>
              )}
            </div>
            {sessionId && (
              <p className="text-xs mt-1 truncate" style={{ color: "var(--nexus-text-muted)" }}>
                Session: {sessionId.slice(0, 8)}...
              </p>
            )}
          </div>
        </div>

        {/* Agent Fleet */}
        <div className="px-6 py-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--nexus-text-muted)" }}>
            Agent Fleet
          </h3>
          {[
            { name: "MasterCoordinator", icon: <Bot size={14} />, status: "ready" },
            { name: "DocsAgent", icon: <FileText size={14} />, status: "ready" },
            { name: "K8sAgent", icon: <Server size={14} />, status: "ready" },
            { name: "MetricsAgent", icon: <Gauge size={14} />, status: "ready" },
          ].map((agent) => (
            <div
              key={agent.name}
              className="flex items-center gap-2 py-2 px-3 rounded-lg mb-1 text-sm transition-colors hover:bg-white/5"
            >
              <span style={{ color: "var(--nexus-accent)" }}>{agent.icon}</span>
              <span style={{ color: "var(--nexus-text-secondary)" }}>{agent.name}</span>
              <span className="ml-auto w-2 h-2 rounded-full" style={{ background: "var(--nexus-success)" }} />
            </div>
          ))}
        </div>

        {/* Infra Status */}
        <div className="px-6 py-3 mt-auto">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--nexus-text-muted)" }}>
            Infrastructure
          </h3>
          {[
            { name: "Kafka", status: "connected" },
            { name: "Qdrant", status: "connected" },
            { name: "PostgreSQL", status: "connected" },
            { name: "Redis", status: "connected" },
          ].map((svc) => (
            <div key={svc.name} className="flex items-center gap-2 py-1.5 text-xs">
              <Terminal size={12} style={{ color: "var(--nexus-text-muted)" }} />
              <span style={{ color: "var(--nexus-text-secondary)" }}>{svc.name}</span>
              <span className="ml-auto w-1.5 h-1.5 rounded-full" style={{ background: "var(--nexus-success)" }} />
            </div>
          ))}
        </div>
      </aside>

      {/* ─── Main Chat Area ─── */}
      <main className="flex-1 flex flex-col">
        {/* Header */}
        <header
          className="h-16 flex items-center px-8 border-b"
          style={{
            background: "var(--nexus-bg-secondary)",
            borderColor: "var(--nexus-border)",
          }}
        >
          <Shield size={18} style={{ color: "var(--nexus-accent)" }} />
          <span className="ml-3 font-medium" style={{ color: "var(--nexus-text-primary)" }}>
            Operations Console
          </span>
          <span className="ml-2 text-xs px-2 py-0.5 rounded-full" style={{ background: "var(--nexus-accent-glow)", color: "var(--nexus-accent)" }}>
            v0.1.0
          </span>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-8 py-6">
          {messages.length === 0 && !isStreaming && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6 }}
              className="flex flex-col items-center justify-center h-full"
            >
              <div
                className="w-20 h-20 rounded-2xl flex items-center justify-center mb-6 glow-accent animate-pulse-glow"
                style={{ background: "linear-gradient(135deg, var(--nexus-gradient-start), var(--nexus-gradient-end))" }}
              >
                <Zap size={36} color="white" />
              </div>
              <h2 className="text-2xl font-bold gradient-text mb-2">NexusOps</h2>
              <p className="text-center mb-8 max-w-md" style={{ color: "var(--nexus-text-secondary)" }}>
                Your AI-powered infrastructure operations center. Ask me anything about your
                cloud services, Kubernetes clusters, or incidents.
              </p>

              <div className="grid grid-cols-2 gap-3 max-w-lg w-full">
                {SUGGESTED_QUERIES.map((q, i) => (
                  <motion.button
                    key={i}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.1 * i }}
                    onClick={() => handleSend(q.text)}
                    className={`glass-card p-4 text-left text-sm transition-all duration-200 hover:scale-[1.02] cursor-pointer`}
                    style={{ color: "var(--nexus-text-secondary)" }}
                    onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--nexus-border-active)")}
                    onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--nexus-border)")}
                  >
                    <span className="flex items-center gap-2 mb-1" style={{ color: "var(--nexus-accent)" }}>
                      {q.icon}
                    </span>
                    {q.text}
                  </motion.button>
                ))}
              </div>
            </motion.div>
          )}

          <AnimatePresence>
            {messages.map((msg) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className={`flex gap-3 mb-6 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                {msg.role === "assistant" && (
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-1"
                    style={{ background: "linear-gradient(135deg, var(--nexus-gradient-start), var(--nexus-gradient-end))" }}
                  >
                    <Bot size={16} color="white" />
                  </div>
                )}
                <div
                  className={`max-w-[70%] rounded-2xl px-5 py-3 message-content ${
                    msg.role === "user" ? "glow-accent" : "glass-card"
                  }`}
                  style={
                    msg.role === "user"
                      ? { background: "linear-gradient(135deg, var(--nexus-gradient-start), var(--nexus-gradient-end))", color: "white" }
                      : {}
                  }
                >
                  {msg.role === "assistant" ? (
                    <Markdown>{msg.content}</Markdown>
                  ) : (
                    <p>{msg.content}</p>
                  )}
                </div>
                {msg.role === "user" && (
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-1"
                    style={{ background: "var(--nexus-bg-tertiary)", border: "1px solid var(--nexus-border)" }}
                  >
                    <User size={16} style={{ color: "var(--nexus-text-secondary)" }} />
                  </div>
                )}
              </motion.div>
            ))}
          </AnimatePresence>

          {/* Streaming Response */}
          {isStreaming && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex gap-3 mb-6"
            >
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-1 animate-pulse-glow"
                style={{ background: "linear-gradient(135deg, var(--nexus-gradient-start), var(--nexus-gradient-end))" }}
              >
                <Bot size={16} color="white" />
              </div>
              <div className="glass-card glass-card-active max-w-[70%] rounded-2xl px-5 py-3 message-content">
                {activeTools.length > 0 && (
                  <div className="flex items-center gap-2 mb-2 text-xs" style={{ color: "var(--nexus-accent)" }}>
                    <Loader2 size={12} className="animate-spin" />
                    Consulting: {activeTools.join(", ")}
                  </div>
                )}
                {streamingText ? (
                  <Markdown>{streamingText}</Markdown>
                ) : (
                  <div className="flex items-center gap-1 py-1">
                    <span className="typing-dot" />
                    <span className="typing-dot" />
                    <span className="typing-dot" />
                  </div>
                )}
              </div>
            </motion.div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <div className="px-8 py-4" style={{ borderTop: "1px solid var(--nexus-border)" }}>
          <div className="glass-card flex items-center gap-3 px-4 py-2 rounded-2xl transition-all duration-200 focus-within:border-[var(--nexus-border-active)] focus-within:shadow-[0_0_20px_var(--nexus-accent-glow)]">
            <input
              ref={inputRef}
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={isConnected ? "Ask NexusOps about your infrastructure..." : "Connecting..."}
              disabled={!isConnected || isStreaming}
              className="flex-1 bg-transparent outline-none text-sm placeholder:text-[var(--nexus-text-muted)]"
              style={{ color: "var(--nexus-text-primary)" }}
            />
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => handleSend()}
              disabled={!inputValue.trim() || !isConnected || isStreaming}
              className="w-9 h-9 rounded-xl flex items-center justify-center transition-all disabled:opacity-30"
              style={{
                background: inputValue.trim()
                  ? "linear-gradient(135deg, var(--nexus-gradient-start), var(--nexus-gradient-end))"
                  : "var(--nexus-bg-tertiary)",
              }}
            >
              <Send size={16} color="white" />
            </motion.button>
          </div>
          <p className="text-center text-xs mt-2" style={{ color: "var(--nexus-text-muted)" }}>
            NexusOps uses AI agents to analyze your infrastructure. Always verify critical actions.
          </p>
        </div>
      </main>
    </div>
  );
}
