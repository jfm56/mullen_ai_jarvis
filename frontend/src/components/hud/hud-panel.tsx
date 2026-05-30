"use client";

import { useState, type CSSProperties, type ReactNode } from "react";

/**
 * HUD spec palette. Inlined here so every HUD component is self-contained
 * and survives an isolated import without depending on Tailwind theme
 * extensions being wired up yet.
 */
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

interface HudPanelProps {
  /** Small caps label rendered above the content. */
  label?: string;
  /** Border + label color treatment. */
  tone?: "default" | "warning" | "accent";
  className?: string;
  children: ReactNode;
}

/**
 * Reusable glass card primitive. Renders an angled top-left corner notch
 * (clip-path), a 1px accent border that intensifies on hover, and a
 * backdrop-blur layer over bg_panel at 70% alpha.
 */
export function HudPanel({
  label,
  tone = "default",
  className,
  children,
}: HudPanelProps) {
  const [hovered, setHovered] = useState(false);

  const toneColor =
    tone === "warning"
      ? PALETTE.warning
      : tone === "accent"
        ? PALETTE.accent
        : PALETTE.border;
  const borderColor = hovered ? PALETTE.accent : toneColor;

  const wrapperStyle: CSSProperties = {
    position: "relative",
    backgroundColor: "rgba(11, 19, 34, 0.7)",
    border: `1px solid ${borderColor}`,
    color: PALETTE.text,
    backdropFilter: "blur(6px)",
    WebkitBackdropFilter: "blur(6px)",
    clipPath:
      "polygon(14px 0, 100% 0, 100% 100%, 0 100%, 0 14px)",
    boxShadow: hovered ? `0 0 18px ${PALETTE.glow}` : "none",
    transition: "border-color 200ms ease, box-shadow 200ms ease",
    padding: "16px",
  };

  const labelStyle: CSSProperties = {
    fontFamily: "Orbitron, sans-serif",
    fontSize: "10px",
    letterSpacing: "0.18em",
    textTransform: "uppercase",
    color:
      tone === "warning"
        ? PALETTE.warning
        : tone === "accent"
          ? PALETTE.accent
          : PALETTE.textDim,
    marginBottom: "8px",
  };

  return (
    <div
      className={className}
      style={wrapperStyle}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {label ? <div style={labelStyle}>{label}</div> : null}
      <div>{children}</div>
    </div>
  );
}
