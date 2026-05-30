import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // Legacy brand palette kept for any pages still referencing it.
        brand: {
          50: "#f4f7f9",
          100: "#e6ecf1",
          200: "#c9d4dd",
          300: "#9eb1bf",
          500: "#5b7a8f",
          700: "#3a5566",
          900: "#1d2e39",
        },
        // HUD palette — primary surface system for the Jarvis command center.
        hud: {
          bg: "#05080F",
          panel: "#0B1322",
          accent: "#22D3EE",
          accent_dim: "#0E7490",
          text: "#F1F7FB",
          text_dim: "#7A8FA6",
          border: "#15243B",
          warning: "#F5A524",
        },
      },
      fontFamily: {
        sans: ["Exo 2", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto"],
        display: ["Orbitron", "Exo 2", "ui-sans-serif", "system-ui", "sans-serif"],
        body: ["Exo 2", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas"],
      },
    },
  },
  plugins: [],
};

export default config;
