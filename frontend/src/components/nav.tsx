"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth";

const ITEMS: { href: string; label: string }[] = [
  { href: "/", label: "Today" },
  { href: "/tasks", label: "Tasks" },
  { href: "/approvals", label: "Approvals" },
  { href: "/projects", label: "Projects" },
  { href: "/leads", label: "Leads" },
  { href: "/grants", label: "Grants" },
  { href: "/marketing", label: "Marketing" },
  { href: "/agents", label: "Agents" },
  { href: "/settings", label: "Settings" },
];

export function Nav() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  if (!user) return null;

  return (
    <aside className="flex h-screen w-56 flex-col border-r border-hud-border bg-hud-panel/80 backdrop-blur-md">
      <div className="border-b border-hud-border p-4">
        <div className="hud-heading text-sm font-semibold text-hud-accent">
          JARVIS
        </div>
        <div className="mt-1 text-xs text-hud-text_dim tracking-wide">
          {user.display_name}
          {user.is_admin ? (
            <span className="ml-1 text-hud-accent">· admin</span>
          ) : null}
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto p-2">
        {ITEMS.map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={
                "block rounded-sm border px-3 py-2 text-sm tracking-wide transition-colors " +
                (active
                  ? "border-hud-accent_dim bg-hud-accent_dim/20 font-medium text-hud-accent"
                  : "border-transparent text-hud-text_dim hover:border-hud-border hover:bg-hud-bg/40 hover:text-hud-text")
              }
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-hud-border p-2">
        <button
          type="button"
          onClick={logout}
          className="w-full rounded-sm border border-transparent px-3 py-2 text-left text-sm text-hud-text_dim transition-colors hover:border-hud-warning/60 hover:text-hud-warning"
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}
