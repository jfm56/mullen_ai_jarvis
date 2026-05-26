import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // A muted, calm palette — this is a tool not a marketing site.
        brand: {
          50: "#f4f7f9",
          100: "#e6ecf1",
          200: "#c9d4dd",
          300: "#9eb1bf",
          500: "#5b7a8f",
          700: "#3a5566",
          900: "#1d2e39",
        },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas"],
      },
    },
  },
  plugins: [],
};

export default config;
