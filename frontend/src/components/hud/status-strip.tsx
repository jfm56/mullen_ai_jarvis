"use client";

import { useEffect, useState, type CSSProperties } from "react";

const PALETTE = {
  bg: "#05080F",
  bgPanel: "#0B1322",
  accent: "#22D3EE",
  text: "#F1F7FB",
  textDim: "#7A8FA6",
  border: "#15243B",
  warning: "#F5A524",
  online: "#22D3EE",
} as const;

interface StatusStripProps {
  wordmark?: string;
  agentLabel?: string;
  latencyMs?: number;
  connection?: "online" | "reconnecting" | "offline";
}

/**
 * Top-of-page horizontal bar: wordmark left, ticking clock center,
 * agent latency + model name + connection dot right.
 */
export function StatusStrip({
  wordmark = "JARVIS // ONLINE",
  agentLabel = "claude-3-5-sonnet",
  latencyMs,
  connection = "online",
}: StatusStripProps) {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    // Avoid a hydration mismatch by not setting time during SSR.
    setNow(new Date());
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const wrapStyle: CSSProperties = {
    position: "sticky",
    top: 0,
    zIndex: 40,
    height: "48px",
    width: "100%",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 24px",
    backgroundColor: "rgba(5, 8, 15, 0.85)",
    borderBottom: `1px solid ${PALETTE.border}`,
    backdropFilter: "blur(6px)",
    WebkitBackdropFilter: "blur(6px)",
    color: PALETTE.text,
  };

  const wordmarkStyle: CSSProperties = {
    fontFamily: "Orbitron, sans-serif",
    fontSize: "13px",
    fontWeight: 700,
    letterSpacing: "0.22em",
    color: PALETTE.accent,
    textShadow: "0 0 8px rgba(34, 211, 238, 0.25)",
  };

  const clockStyle: CSSProperties = {
    fontFamily: "JetBrains Mono, monospace",
    fontSize: "12px",
    color: PALETTE.textDim,
    letterSpacing: "0.1em",
  };

  const rightStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: "16px",
    fontFamily: "JetBrains Mono, monospace",
    fontSize: "11px",
    color: PALETTE.textDim,
  };

  const dotColor =
    connection === "online"
      ? PALETTE.online
      : connection === "reconnecting"
        ? PALETTE.warning
        : "#EF4444";

  const dotStyle: CSSProperties = {
    display: "inline-block",
    width: "8px",
    height: "8px",
    borderRadius: "50%",
    backgroundColor: dotColor,
    boxShadow: `0 0 8px ${dotColor}`,
    animation:
      connection === "reconnecting"
        ? "hud-pulse 1.2s ease-in-out infinite"
        : "none",
  };

  const latencyLabel =
    latencyMs != null ? `${Math.round(latencyMs)}ms` : "—ms";

  const dateStr = now
    ? now.toLocaleDateString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
      })
    : "";
  const timeStr = now
    ? now.toLocaleTimeString(undefined, { hour12: false })
    : "--:--:--";

  return (
    <header style={wrapStyle} role="banner">
      <div style={wordmarkStyle}>{wordmark}</div>

      <div style={clockStyle}>
        <span suppressHydrationWarning>{dateStr}</span>
        <span style={{ margin: "0 12px", color: PALETTE.border }}>|</span>
        <span suppressHydrationWarning>{timeStr}</span>
      </div>

      <div style={rightStyle}>
        <span>{latencyLabel}</span>
        <span style={{ color: PALETTE.border }}>·</span>
        <span style={{ color: PALETTE.text }}>{agentLabel}</span>
        <span style={dotStyle} aria-label={`connection: ${connection}`} />
      </div>
    </header>
  );
}
