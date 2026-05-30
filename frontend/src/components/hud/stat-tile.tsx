"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { HudPanel } from "@/components/hud/hud-panel";

const PALETTE = {
  accent: "#22D3EE",
  text: "#F1F7FB",
  textDim: "#7A8FA6",
  border: "#15243B",
  glow: "rgba(34, 211, 238, 0.35)",
  warning: "#F5A524",
  success: "#22D3EE",
} as const;

interface StatTileProps {
  label: string;
  value: number;
  suffix?: string;
  trend?: "up" | "down" | "flat";
  delta?: number;
  tone?: "default" | "warning" | "success";
  icon?: ReactNode;
}

/**
 * Glassmorphic single-metric tile. Animates a count-up on mount via rAF
 * tween (~600ms ease-out). Hover lifts the border to accent + adds a
 * 1px scanline at the top edge.
 */
export function StatTile({
  label,
  value,
  suffix,
  trend,
  delta,
  tone = "default",
  icon,
}: StatTileProps) {
  const [display, setDisplay] = useState(0);
  const [hovered, setHovered] = useState(false);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);
  const fromRef = useRef(0);

  useEffect(() => {
    // Tween from current display to new value over 600ms, ease-out cubic.
    fromRef.current = display;
    startRef.current = null;
    const target = value;

    const tick = (ts: number) => {
      if (startRef.current == null) startRef.current = ts;
      const elapsed = ts - startRef.current;
      const t = Math.min(1, elapsed / 600);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      const current = fromRef.current + (target - fromRef.current) * eased;
      setDisplay(current);
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
    // We intentionally re-run when value changes; display is internal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const accentColor =
    tone === "warning"
      ? PALETTE.warning
      : tone === "success"
        ? PALETTE.success
        : PALETTE.accent;

  // Round to integer if value looks like a whole number, otherwise show 1 decimal.
  const isInt = Number.isInteger(value);
  const displayStr = isInt
    ? Math.round(display).toString()
    : display.toFixed(1);

  const valueStyle: CSSProperties = {
    fontFamily: "Orbitron, sans-serif",
    fontSize: "32px",
    fontWeight: 700,
    color: accentColor,
    letterSpacing: "0.04em",
    lineHeight: 1,
    textShadow: hovered ? `0 0 12px ${PALETTE.glow}` : "none",
    transition: "text-shadow 200ms ease",
  };

  const suffixStyle: CSSProperties = {
    fontFamily: "JetBrains Mono, monospace",
    fontSize: "10px",
    color: PALETTE.textDim,
    letterSpacing: "0.1em",
    textTransform: "uppercase",
  };

  const labelStyle: CSSProperties = {
    fontFamily: "Orbitron, sans-serif",
    fontSize: "10px",
    color: PALETTE.textDim,
    letterSpacing: "0.18em",
    textTransform: "uppercase",
    marginTop: "12px",
  };

  const deltaColor =
    trend === "up"
      ? PALETTE.accent
      : trend === "down"
        ? PALETTE.warning
        : PALETTE.textDim;

  const arrow = trend === "up" ? "▲" : trend === "down" ? "▼" : "•";

  const scanlineStyle: CSSProperties = {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    height: "1px",
    background: hovered
      ? `linear-gradient(90deg, transparent, ${PALETTE.accent}, transparent)`
      : "transparent",
    opacity: hovered ? 1 : 0,
    transition: "opacity 200ms ease",
    pointerEvents: "none",
  };

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ position: "relative" }}
    >
      <HudPanel tone={tone === "warning" ? "warning" : "default"}>
        <div style={scanlineStyle} />
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: "8px" }}>
            {icon ? (
              <span style={{ color: accentColor, display: "inline-flex" }}>{icon}</span>
            ) : null}
            <span style={valueStyle}>{displayStr}</span>
          </div>
          {suffix ? <span style={suffixStyle}>{suffix}</span> : null}
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={labelStyle}>{label}</div>
          {trend && delta != null ? (
            <div
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: "11px",
                color: deltaColor,
                marginTop: "12px",
              }}
            >
              <span style={{ marginRight: "4px" }}>{arrow}</span>
              {Math.abs(delta)}
            </div>
          ) : null}
        </div>
      </HudPanel>
    </div>
  );
}
