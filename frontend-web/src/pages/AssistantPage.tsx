// src/pages/AssistantPage.tsx
// Dedicated PehchaanAI Support & Compliance Assistant page with responsive split layout,
// auto-scrolling message pane, typing indicator, and session-context binding.
import React, { useEffect, useState } from "react";
import { Bot, Send, BookOpen, RotateCcw } from "lucide-react";
import { apiRequest } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { TypingBubble, useChatAutoScroll } from "../components/ChatUi";
import type { AiChatResponse } from "../types/kyc";

interface Msg {
  role: "user" | "bot";
  text: string;
  meta?: string;
}

const WELCOME_MSG: Msg = {
  role: "bot",
  text: "Welcome to the PehchaanAI Hybrid RAG Assistant. Optionally paste a Tracking Code or Session ID to query live session data alongside our verification documentation.",
  meta: "local-grounded RAG",
};

const SAMPLE_QUESTIONS = [
  "How does PehchaanAI verify Aadhaar and PAN cards?",
  "Why does a session get flagged for Manual REVIEW instead of PASS?",
  "How are my selfie and ID encrypted in the Evidence Vault?",
  "How is the 0-100 Unified Fraud Risk Score calculated?",
];

export const AssistantPage: React.FC = () => {
  const { activeSessionId } = useAuth();
  const [sessionRef, setSessionRef] = useState(activeSessionId || "");
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([WELCOME_MSG]);

  const messagesRef = useChatAutoScroll<HTMLDivElement>([messages.length, sending]);

  useEffect(() => {
    if (activeSessionId && !sessionRef) {
      setSessionRef(activeSessionId);
    }
  }, [activeSessionId, sessionRef]);

  const send = async (qText: string) => {
    const q = qText.trim();
    if (!q || sending) return;
    setMessages((prev) => [...prev, { role: "user", text: q }]);
    setInput("");
    setSending(true);
    try {
      const res = await apiRequest<AiChatResponse>("/api/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          session_id: sessionRef.trim() || undefined,
        }),
      });
      setMessages((prev) => [
        ...prev,
        {
          role: "bot",
          text: res.answer,
          meta: `Provider: ${res.provider} · Sources: ${res.citations.join(", ")}`,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: "bot", text: `Error: ${(err as Error).message}` }]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="page-container">
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ fontFamily: "var(--font-head)", fontSize: 24, fontWeight: 800 }}>
          PehchaanAI Support &amp; Compliance Assistant
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
          Retrieval-Augmented Guidance backed by verified codebase documentation and optional LLM providers (Gemini / Groq / OpenAI / Ollama).
        </p>
      </div>

      <div className="assistant-layout">
        <div className="card">
          <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <BookOpen size={16} color="#38bdf8" /> Session Context &amp; Quick Prompts
          </div>
          <div className="field-group">
            <label className="field-label" htmlFor="assistantSessionRef">
              Attach Tracking Code / Session ID (Optional)
            </label>
            <input
              id="assistantSessionRef"
              className="field-input mono"
              placeholder="e.g. KYC-9772548D"
              value={sessionRef}
              onChange={(e) => setSessionRef(e.target.value)}
            />
          </div>

          <div style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 8 }}>Suggested questions:</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {SAMPLE_QUESTIONS.map((q) => (
              <button
                key={q}
                type="button"
                className="btn btn-secondary btn-sm"
                style={{ justifyContent: "flex-start", textAlign: "left" }}
                disabled={sending}
                onClick={() => send(q)}
              >
                {q}
              </button>
            ))}
          </div>
        </div>

        <div className="card assistant-chat-card">
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 8,
              paddingBottom: 12,
              borderBottom: "1px solid var(--border)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Bot size={18} color="#38bdf8" />
              <strong style={{ fontSize: 14 }}>Grounded RAG Conversation</strong>
            </div>
            {messages.length > 1 && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setMessages([WELCOME_MSG])}
                disabled={sending}
              >
                <RotateCcw size={13} /> Clear
              </button>
            )}
          </div>

          <div className="ai-messages" ref={messagesRef} style={{ paddingLeft: 0, paddingRight: 0 }}>
            {messages.map((m, idx) => (
              <div key={idx} className={`ai-bubble ${m.role}`}>
                <div>{m.text}</div>
                {m.meta && (
                  <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 6 }}>{m.meta}</div>
                )}
              </div>
            ))}
            {sending && <TypingBubble />}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            style={{ display: "flex", gap: 10, paddingTop: 12, borderTop: "1px solid var(--border)" }}
          >
            <input
              className="field-input"
              placeholder="Ask about OCR, Verhoeff checksums, anti-spoofing, vault encryption..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={sending}
            />
            <button type="submit" className="btn btn-primary" disabled={sending || !input.trim()}>
              <Send size={15} /> Send
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};
