import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The backend lives on a separate origin during dev; CORS handles cross-origin.
  // In production, an upstream proxy (or Tauri wrapper) collapses them to one.
  env: {
    NEXT_PUBLIC_API_BASE:
      process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000",
  },
};

export default nextConfig;
