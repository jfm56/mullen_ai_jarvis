"use client";

import type { CSSProperties } from "react";

const PALETTE = {
  accent: "#22D3EE",
  accentDim: "#0E7490",
  text: "#F1F7FB",
  textDim: "#7A8FA6",
  border: "#15243B",
  glow: "rgba(34, 211, 238, 0.35)",
} as const;

interface ArcReactorProps {
  /** Diameter in px. Defaults to 200 (spec calls for ~200–480px). */
  size?: number;
  state?: "idle" | "listening" | "thinking" | "alert";
  /** Optional aria label override. Component is decorative by default. */
  label?: string;
}

/**
 * Animated SVG centerpiece. Pure CSS animations (referenced by name from
 * globals.css) — no canvas, no framer-motion, no particle systems.
 *
 * Animation names referenced (defined in globals.css):
 *   - hud-spin-slow      (20s linear infinite)
 *   - hud-spin-reverse   (28s linear infinite, reverse direction)
 *   - hud-pulse          (radial glow breathe)
 *   - arc-spin           (inner ticks)
 *   - arc-pulse          (subtle ring intensity pulse)
 *   - hud-glow-breathe   (alert tone)
 */
export function ArcReactor({
  size = 200,
  state = "idle",
  label,
}: ArcReactorProps) {
  const isListening = state === "listening";
  const isThinking = state === "thinking";
  const isAlert = state === "alert";

  // Animation duration adjusts with state: listening doubles pulse speed,
  // thinking spins the inner tick ring, alert breathes a warning glow.
  const outerSpinDuration = isListening ? "10s" : "20s";
  const innerSpinDuration = isThinking ? "6s" : "12s";
  const pulseDuration = isListening ? "1.2s" : "2.4s";

  // Geometry — kept in a 200 viewBox so the SVG scales cleanly.
  const V = 200;
  const cx = V / 2;
  const cy = V / 2;

  // Soft glow color — brightens slightly when listening / alert.
  const ringStroke = isAlert ? "#F5A524" : PALETTE.accent;
  const ringStrokeDim = isAlert ? "#7A4C0C" : PALETTE.accentDim;

  const wrapperStyle: CSSProperties = {
    width: size,
    height: size,
    position: "relative",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    filter: isAlert
      ? "drop-shadow(0 0 18px rgba(245, 165, 36, 0.4))"
      : `drop-shadow(0 0 18px ${PALETTE.glow})`,
  };

  // The radial "core glow" sits behind the SVG and pulses.
  const haloStyle: CSSProperties = {
    position: "absolute",
    inset: "12%",
    borderRadius: "50%",
    background: `radial-gradient(circle, ${PALETTE.glow} 0%, rgba(34,211,238,0.10) 40%, rgba(0,0,0,0) 70%)`,
    animation: `hud-pulse ${pulseDuration} ease-in-out infinite`,
    pointerEvents: "none",
  };

  // Per-element animation styles — referenced animation names live in
  // globals.css and are expected to be defined there.
  const outerRingStyle: CSSProperties = {
    transformOrigin: "center",
    animation: `hud-spin-slow ${outerSpinDuration} linear infinite`,
  };
  const counterRingStyle: CSSProperties = {
    transformOrigin: "center",
    animation: `hud-spin-reverse ${outerSpinDuration} linear infinite`,
  };
  const innerTickStyle: CSSProperties = {
    transformOrigin: "center",
    animation: `arc-spin ${innerSpinDuration} linear infinite`,
    opacity: isThinking ? 1 : 0.55,
  };
  const corePulseStyle: CSSProperties = {
    transformOrigin: "center",
    animation: `arc-pulse ${pulseDuration} ease-in-out infinite`,
  };

  return (
    <div
      style={wrapperStyle}
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? "img" : undefined}
    >
      <div style={haloStyle} />
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${V} ${V}`}
        xmlns="http://www.w3.org/2000/svg"
        style={{ position: "relative" }}
      >
        <defs>
          <radialGradient id="arc-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={ringStroke} stopOpacity="0.9" />
            <stop offset="60%" stopColor={ringStrokeDim} stopOpacity="0.4" />
            <stop offset="100%" stopColor="#000000" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="arc-tick" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={ringStroke} stopOpacity="1" />
            <stop offset="100%" stopColor={ringStroke} stopOpacity="0.2" />
          </linearGradient>
        </defs>

        {/* Outermost ring — slow counter-rotating dashed circle. */}
        <g style={counterRingStyle}>
          <circle
            cx={cx}
            cy={cy}
            r={94}
            fill="none"
            stroke={ringStrokeDim}
            strokeWidth={1}
            strokeDasharray="4 8"
            opacity={0.85}
          />
        </g>

        {/* Outer ring — slow forward rotation, thicker dashes. */}
        <g style={outerRingStyle}>
          <circle
            cx={cx}
            cy={cy}
            r={84}
            fill="none"
            stroke={ringStroke}
            strokeWidth={1.5}
            strokeDasharray="20 6"
            opacity={0.9}
          />
        </g>

        {/* Static mid-ring with crosshair tick marks at compass points. */}
        <circle
          cx={cx}
          cy={cy}
          r={72}
          fill="none"
          stroke={ringStrokeDim}
          strokeWidth={1}
          opacity={0.6}
        />
        {/* Crosshair: north / south / east / west small ticks. */}
        <g stroke={ringStroke} strokeWidth={1.5} opacity={0.85}>
          <line x1={cx} y1={cy - 78} x2={cx} y2={cy - 66} />
          <line x1={cx} y1={cy + 66} x2={cx} y2={cy + 78} />
          <line x1={cx - 78} y1={cy} x2={cx - 66} y2={cy} />
          <line x1={cx + 66} y1={cy} x2={cx + 78} y2={cy} />
        </g>

        {/* Inner tick ring — spins faster when thinking. */}
        <g style={innerTickStyle}>
          {Array.from({ length: 24 }).map((_, i) => {
            const angle = (i * Math.PI * 2) / 24;
            const r1 = 56;
            const r2 = i % 3 === 0 ? 46 : 50;
            const x1 = cx + Math.cos(angle) * r1;
            const y1 = cy + Math.sin(angle) * r1;
            const x2 = cx + Math.cos(angle) * r2;
            const y2 = cy + Math.sin(angle) * r2;
            return (
              <line
                key={i}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke="url(#arc-tick)"
                strokeWidth={1.2}
              />
            );
          })}
        </g>

        {/* Steady inner ring around the core. */}
        <circle
          cx={cx}
          cy={cy}
          r={40}
          fill="none"
          stroke={ringStroke}
          strokeWidth={1.5}
          opacity={0.85}
        />

        {/* Pulsing core. */}
        <g style={corePulseStyle}>
          <circle cx={cx} cy={cy} r={32} fill="url(#arc-core)" />
          <circle
            cx={cx}
            cy={cy}
            r={18}
            fill={ringStroke}
            opacity={isAlert ? 0.75 : 0.55}
          />
        </g>
      </svg>
    </div>
  );
}
