// src/components/ChatUi.tsx
// Shared chat UI utilities for both the floating AssistantDrawer and full AssistantPage:
// auto-scrolls the message pane on new turns and renders a pulsing typing indicator.
import React, { useEffect, useRef } from "react";

export function useChatAutoScroll<T extends HTMLElement>(deps: unknown[]) {
  const containerRef = useRef<T | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return containerRef;
}

export const TypingBubble: React.FC = () => (
  <div className="ai-bubble bot" aria-live="polite" aria-label="PehchaanAI is thinking">
    <span className="typing-dots">
      <span />
      <span />
      <span />
    </span>
  </div>
);
