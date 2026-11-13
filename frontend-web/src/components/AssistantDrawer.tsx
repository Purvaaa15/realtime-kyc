// src/components/AssistantDrawer.tsx
// Persistent floating PehchaanAI RAG assistant accessible from every page.
// Includes auto-scroll, pulsing typing indicator, and Escape-key dismissal.
import React, { useEffect, useState } from "react";
import { Bot, Send, X, Sparkles } from "lucide-react";
import { apiRequest } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { TypingBubble, useChatAutoScroll } from "./ChatUi";
import type { AiChatResponse } from "../types/kyc";

interface ChatMsg {
  role: "user" | "bot";
  text: string;
  meta?: string;
}

const QUICK_PROMPTS = [
  "Why does blink liveness require 2 blinks?",
  "Which Indian IDs & validations are supported?",
  "How are my selfie and ID encrypted?",
];

export const AssistantDrawer: React.FC = () => {
  const { activeSessionId } = useAuth();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      role: "bot",
      text: "Hi! I am the PehchaanAI Assistant. Ask me about live verification, Aadhaar/PAN checks, fraud scores, or privacy.",
      meta: "Grounded RAG",
    },
  ]);

  const messagesRef = useChatAutoScroll<HTMLDivElement>([messages.length, sending, open]);

  // Allow pressing Escape to close the floating drawer
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  const ask = async (questionText: string) => {
    const q = questionText.trim();
    if (!q || sending) return;

    setMessages((prev) => [...prev, { role: "user", text: q }]);
    setInput("");
    setSending(true);

    try {
      const res = await apiRequest<AiChatResponse>("/api/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, session_id: activeSessionId || undefined }),
      });
      setMessages((prev) => [
        ...prev,
        {
          role: "bot",
          text: res.answer,
          meta: `${res.provider} · Sources: ${res.citations.join(", ")}`,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "bot", text: `Could not reach AI Assistant: ${(err as Error).message}` },
      ]);
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      {open && (
        <div className="ai-drawer" role="dialog" aria-label="PehchaanAI Assistant">
          <div
            style={{
              padding: "12px 14px",
              borderBottom: "1px solid var(--border)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              background: "var(--bg-elevated)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Sparkles size={16} color="#38bdf8" />
              <div>
                <div style={{ fontSize: 13, fontWeight: 700 }}>PehchaanAI Assistant</div>
                <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                  {activeSessionId ? `Context: ${activeSessionId.slice(0, 8)}` : "Grounded KYC Help"}
                </div>
              </div>
            </div>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              aria-label="Close AI assistant"
              onClick={() => setOpen(false)}
            >
              <X size={14} />
            </button>
          </div>

          <div className="ai-messages" ref={messagesRef}>
            {messages.map((m, idx) => (
              <div key={idx} className={`ai-bubble ${m.role}`}>
                <div>{m.text}</div>
                {m.meta && (
                  <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 6 }}>{m.meta}</div>
                )}
              </div>
            ))}
            {sending && <TypingBubble />}
            {messages.length === 1 && !sending && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                {QUICK_PROMPTS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    className="btn btn-secondary btn-sm"
                    style={{ fontSize: 11, textAlign: "left" }}
                    onClick={() => ask(q)}
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              ask(input);
            }}
            style={{
              padding: 10,
              borderTop: "1px solid var(--border)",
              display: "flex",
              gap: 8,
              background: "var(--bg-elevated)",
            }}
          >
            <input
              className="field-input"
              placeholder="Ask about verification or status..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={sending}
            />
            <button type="submit" className="btn btn-primary btn-sm" disabled={sending || !input.trim()}>
              <Send size={14} />
            </button>
          </form>
        </div>
      )}

      <button type="button" className="ai-fab" onClick={() => setOpen((v) => !v)}>
        <Bot size={16} />
        {open ? "Close AI Help" : "Ask PehchaanAI"}
      </button>
    </>
  );
};
