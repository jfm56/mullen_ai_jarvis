"use client";

import type { CSSProperties, ReactNode } from "react";

import { StatusStrip } from "@/components/hud/status-strip";

const PALETTE = {
  bg: "#05080F",
  bgPanel: "#0B1322",
  accent: "#22D3EE",
  text: "#F1F7FB",
  textDim: "#7A8FA6",
  border: "#15243B",
} as const;

interface CommandCenterShellProps {
  left: ReactNode;
  right: ReactNode;
  reactor?: ReactNode;
  statusLabel?: string;
  latencyMs?: number;
  children?: ReactNode;
}

/**
 * Top-level page chrome. Renders the StatusStrip, a fixed page background
 * (radial gradient + faint hex/grid pattern, 6% opacity, static), and a
 * 12-col grid body. left = cols 1-3, reactor + children = cols 4-9,
 * right = cols 10-12. Inner panels scroll independently — the shell is
 * h-screen with no overall scroll.
 */
export function CommandCenterShell({
  left,
  right,
  reactor,
  statusLabel,
  latencyMs,
  children,
}: CommandCenterShellProps) {
  // ---- Page background --------------------------------------------------
  // Radial gradient from bg_panel center -> bg edge, then layered with a
  // CSS hex-grid pattern at 6% opacity, then a soft vignette overlay.
  // Pure CSS — no canvas, no animation.
  const backgroundStyle: CSSProperties = {
    position: "fixed",
    inset: 0,
    zIndex: 0,
    background: `radial-gradient(ellipse at center, ${PALETTE.bgPanel} 0%, ${PALETTE.bg} 75%)`,
    pointerEvents: "none",
  };

  // Faint hex/grid pattern via repeating linear-gradients — cheap, static.
  const gridStyle: CSSProperties = {
    position: "fixed",
    inset: 0,
    zIndex: 1,
    backgroundImage: `
      linear-gradient(${PALETTE.border} 1px, transparent 1px),
      linear-gradient(90deg, ${PALETTE.border} 1px, transparent 1px)
    `,
    backgroundSize: "32px 32px",
    opacity: 0.06,
    pointerEvents: "none",
  };

  // Vignette darkens the corners further to keep the reactor as focal point.
  const vignetteStyle: CSSProperties = {
    position: "fixed",
    inset: 0,
    zIndex: 2,
    background:
      "radial-gradient(ellipse at center, rgba(0,0,0,0) 50%, rgba(0,0,0,0.55) 100%)",
    pointerEvents: "none",
  };

  const shellStyle: CSSProperties = {
    position: "relative",
    zIndex: 3,
    width: "100%",
    height: "100vh",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    color: PALETTE.text,
    backgroundColor: PALETTE.bg,
    fontFamily: "Exo 2, sans-serif",
  };

  const bodyStyle: CSSProperties = {
    flex: 1,
    display: "grid",
    gridTemplateColumns: "repeat(12, 1fr)",
    gap: "24px",
    padding: "24px",
    overflow: "hidden",
    minHeight: 0,
  };

  // Column wrappers — each scrolls independently per the layout spec.
  const colLeftStyle: CSSProperties = {
    gridColumn: "1 / span 3",
    display: "flex",
    flexDirection: "column",
    gap: "16px",
    overflowY: "auto",
    minHeight: 0,
    paddingRight: "4px",
  };
  const colCenterStyle: CSSProperties = {
    gridColumn: "4 / span 6",
    display: "flex",
    flexDirection: "column",
    gap: "16px",
    overflowY: "auto",
    minHeight: 0,
  };
  const colRightStyle: CSSProperties = {
    gridColumn: "10 / span 3",
    display: "flex",
    flexDirection: "column",
    gap: "16px",
    overflowY: "auto",
    minHeight: 0,
    paddingLeft: "4px",
  };

  const reactorSlotStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: "280px",
  };

  return (
    <div style={shellStyle}>
      {/* Backgrounds — always present, always behind content. */}
      <div style={backgroundStyle} aria-hidden />
      <div style={gridStyle} aria-hidden />
      <div style={vignetteStyle} aria-hidden />

      <StatusStrip
        wordmark={statusLabel}
        latencyMs={latencyMs}
        connection="online"
      />

      <main style={bodyStyle}>
        <section style={colLeftStyle} aria-label="left panel">
          {left}
        </section>

        <section style={colCenterStyle} aria-label="center panel">
          {reactor ? <div style={reactorSlotStyle}>{reactor}</div> : null}
          {children}
        </section>

        <section style={colRightStyle} aria-label="right panel">
          {right}
        </section>
      </main>
    </div>
  );
}
