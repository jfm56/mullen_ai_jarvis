import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AuthProvider } from "@/lib/auth";
import { Nav } from "@/components/nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "Jarvis — Mullen Analytics & AI Consulting",
  description: "Secure local-first AI executive assistant.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <div className="flex min-h-screen">
            <Nav />
            <main className="flex-1 overflow-y-auto p-6">{children}</main>
          </div>
        </AuthProvider>
      </body>
    </html>
  );
}
