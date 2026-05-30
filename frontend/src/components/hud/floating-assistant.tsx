"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

import { VoiceButton } from "@/components/voice-button";
import { ApiError, api, type AgentHandleResponse } from "@/lib/api";

const PALETTE = {
  bg: "#05080F",
  bgPanel: "#0B1322",
  accent: "#22D3EE",
  accentDim: "#0E7490",
  text: "#F1F7FB",
  textDim: "#7A8FA6",
  border: "#15243B",
  glow: "rgba(34, 211, 238, 0.35)",
  warning: "#F5A524",
} as const;

interface FloatingAssistantProps {
  defaultOpen?: boolean;
  onTranscript?: (text: string) => void;
  lastReply?: string | null;
}

interface Exchange {
  user: string;
  assistant: string;
}

/**
 * Bottom-right circular HUD button (56px) wrapping the VoiceButton. Click
 * opens a 360×480 glass popover with the last 6 exchanges, a text input,
 * and the mic control. Calls POST /agents/personal_assistant/handle via
 * the typed api helper.
 */
export function FloatingAssistant({
  defaultOpen = false,
  onTranscript,
  lastReply,
}: FloatingAssistantProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastSpokenReply, setLastSpokenReply] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll the transcript to the bottom on new content.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [exchanges, busy]);

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setBusy(true);
      setError(null);
      try {
        const resp: AgentHandleResponse = await api.invokeAgent(
          "personal_assistant",
          trimmed,
          "personal",
          "ask_before_action",
        );
        const reply = resp.text ?? "";
        // Keep the last 6 exchanges (spec says up to 6 displayed; we hard
        // trim the buffer here so memory stays bounded).
        setExchanges((prev) => {
          const next = [...prev, { user: trimmed, assistant: reply }];
          return next.slice(-6);
        });
        setLastSpokenReply(reply || null);
        onTranscript?.(trimmed);
      } catch (err) {
        const msg =
          err instanceof ApiError && typeof err.detail === "string"
            ? err.detail
            : err instanceof Error
              ? err.message
              : "request failed";
        setError(msg);
      } finally {
        setBusy(false);
      }
    },
    [onTranscript],
  );

  const onSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const text = input;
      setInput("");
      void sendMessage(text);
    },
    [input, sendMessage],
  );

  // Voice path: the VoiceButton hands us a transcript -> reuse sendMessage.
  const handleVoiceTranscript = useCallback(
    (text: string) => {
      void sendMessage(text);
    },
    [sendMessage],
  );

  // ---- Styles -----------------------------------------------------------
  const buttonStyle: CSSProperties = {
    position: "fixed",
    right: "24px",
    bottom: "24px",
    zIndex: 50,
    width: "56px",
    height: "56px",
    borderRadius: "50%",
    border: `1px solid ${PALETTE.accent}`,
    background:
      "radial-gradient(circle, rgba(34,211,238,0.25) 0%, rgba(11,19,34,0.95) 70%)",
    color: PALETTE.accent,
    fontFamily: "Orbitron, sans-serif",
    fontSize: "22px",
    fontWeight: 700,
    letterSpacing: "0.05em",
    cursor: "pointer",
    boxShadow: `0 0 18px ${PALETTE.glow}`,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    animation: "hud-glow-breathe 2s ease-in-out infinite",
  };

  const popoverStyle: CSSProperties = {
    position: "fixed",
    right: "24px",
    bottom: "92px",
    zIndex: 50,
    width: "360px",
    height: "480px",
    backgroundColor: "rgba(11, 19, 34, 0.92)",
    border: `1px solid ${PALETTE.accent}`,
    color: PALETTE.text,
    backdropFilter: "blur(8px)",
    WebkitBackdropFilter: "blur(8px)",
    clipPath:
      "polygon(14px 0, 100% 0, 100% calc(100% - 14px), calc(100% - 14px) 100%, 0 100%, 0 14px)",
    boxShadow: `0 0 24px ${PALETTE.glow}`,
    display: "flex",
    flexDirection: "column",
    animation: "hud-fade-in-up 200ms ease-out",
  };

  const headerStyle: CSSProperties = {
    padding: "12px 16px",
    borderBottom: `1px solid ${PALETTE.border}`,
    fontFamily: "Orbitron, sans-serif",
    fontSize: "11px",
    letterSpacing: "0.22em",
    textTransform: "uppercase",
    color: PALETTE.accent,
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  };

  const transcriptStyle: CSSProperties = {
    flex: 1,
    overflowY: "auto",
    padding: "12px 16px",
    fontFamily: "Exo 2, sans-serif",
    fontSize: "13px",
    display: "flex",
    flexDirection: "column",
    gap: "10px",
  };

  const userBubbleStyle: CSSProperties = {
    alignSelf: "flex-end",
    maxWidth: "85%",
    padding: "6px 10px",
    border: `1px solid ${PALETTE.accentDim}`,
    background: "rgba(34,211,238,0.08)",
    color: PALETTE.text,
    fontSize: "12px",
  };

  const assistantBubbleStyle: CSSProperties = {
    alignSelf: "flex-start",
    maxWidth: "85%",
    padding: "6px 10px",
    border: `1px solid ${PALETTE.border}`,
    background: "rgba(5,8,15,0.5)",
    color: PALETTE.text,
    fontSize: "12px",
  };

  const inputRowStyle: CSSProperties = {
    padding: "10px 12px",
    borderTop: `1px solid ${PALETTE.border}`,
    display: "flex",
    flexDirection: "column",
    gap: "8px",
  };

  const inputStyle: CSSProperties = {
    flex: 1,
    backgroundColor: "rgba(5,8,15,0.6)",
    border: `1px solid ${PALETTE.border}`,
    color: PALETTE.text,
    padding: "8px 10px",
    fontFamily: "Exo 2, sans-serif",
    fontSize: "13px",
    outline: "none",
  };

  const sendBtnStyle: CSSProperties = {
    backgroundColor: PALETTE.accentDim,
    border: `1px solid ${PALETTE.accent}`,
    color: PALETTE.text,
    padding: "6px 14px",
    fontFamily: "Orbitron, sans-serif",
    fontSize: "11px",
    letterSpacing: "0.15em",
    textTransform: "uppercase",
    cursor: busy ? "not-allowed" : "pointer",
    opacity: busy ? 0.6 : 1,
  };

  // The latest reply that the parent may want spoken aloud — we forward
  // either the parent-supplied lastReply or the most recent in-popover reply.
  const replyToSpeak =
    lastReply !== undefined ? lastReply : lastSpokenReply;

  return (
    <>
      {open ? (
        <div style={popoverStyle} role="dialog" aria-label="Jarvis assistant">
          <div style={headerStyle}>
            <span>JARVIS // ASSISTANT</span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close assistant"
              style={{
                background: "transparent",
                border: "none",
                color: PALETTE.textDim,
                cursor: "pointer",
                fontFamily: "JetBrains Mono, monospace",
                fontSize: "14px",
              }}
            >
              ×
            </button>
          </div>

          <div ref={scrollRef} style={transcriptStyle}>
            {exchanges.length === 0 && !busy ? (
              <div
                style={{
                  color: PALETTE.textDim,
                  fontSize: "12px",
                  fontStyle: "italic",
                }}
              >
                Ask anything — meetings, grants, drafting, or status of any
                active initiative.
              </div>
            ) : null}

            {exchanges.map((ex, i) => (
              <div
                key={i}
                style={{ display: "flex", flexDirection: "column", gap: "6px" }}
              >
                <div style={userBubbleStyle}>{ex.user}</div>
                {ex.assistant ? (
                  <div style={assistantBubbleStyle}>{ex.assistant}</div>
                ) : null}
              </div>
            ))}

            {busy ? (
              <div
                style={{
                  ...assistantBubbleStyle,
                  color: PALETTE.textDim,
                  fontStyle: "italic",
                }}
              >
                thinking…
              </div>
            ) : null}

            {error ? (
              <div
                style={{
                  border: `1px solid ${PALETTE.warning}`,
                  color: PALETTE.warning,
                  fontSize: "12px",
                  padding: "6px 10px",
                }}
              >
                {error}
              </div>
            ) : null}
          </div>

          <form onSubmit={onSubmit} style={inputRowStyle}>
            <div style={{ display: "flex", gap: "8px" }}>
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Type a message…"
                disabled={busy}
                style={inputStyle}
              />
              <button
                type="submit"
                disabled={busy || !input.trim()}
                style={sendBtnStyle}
              >
                Send
              </button>
            </div>
            <VoiceButton
              onTranscript={handleVoiceTranscript}
              replyText={replyToSpeak ?? null}
            />
          </form>
        </div>
      ) : null}

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={buttonStyle}
        aria-label={open ? "Close assistant" : "Open assistant"}
        aria-expanded={open}
      >
        J
      </button>
    </>
  );
}
