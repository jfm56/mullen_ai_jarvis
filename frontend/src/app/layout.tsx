import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AuthProvider } from "@/lib/auth";
import { Nav } from "@/components/nav";
import { FloatingAssistant } from "@/components/hud/floating-assistant";

import "./globals.css";

export const metadata: Metadata = {
  title: "JARVIS · Mullen Analytics",
  description: "Secure local-first AI executive assistant.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="font-body">
        <AuthProvider>
          <div className="flex min-h-screen bg-hud-bg text-hud-text">
            <Nav />
            <main className="flex-1 overflow-y-auto">{children}</main>
          </div>
          <FloatingAssistant />
        </AuthProvider>
      </body>
    </html>
  );
}
