"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth";

const ITEMS: { href: string; label: string }[] = [
  { href: "/", label: "Today" },
  { href: "/tasks", label: "Tasks" },
  { href: "/approvals", label: "Approvals" },
  { href: "/projects", label: "Projects" },
  { href: "/grants", label: "Grants" },
  { href: "/agents", label: "Agents" },
  { href: "/settings", label: "Settings" },
];

export function Nav() {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  if (!user) return null;

  return (
    <aside className="flex h-screen w-56 flex-col border-r border-brand-100 bg-white">
      <div className="border-b border-brand-100 p-4">
        <div className="text-sm font-semibold text-brand-900">Jarvis</div>
        <div className="mt-0.5 text-xs text-brand-500">
          {user.display_name}{user.is_admin ? " · admin" : ""}
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
                "block rounded-md px-3 py-2 text-sm " +
                (active
                  ? "bg-brand-50 font-medium text-brand-900"
                  : "text-brand-700 hover:bg-brand-50")
              }
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-brand-100 p-2">
        <button
          type="button"
          onClick={logout}
          className="w-full rounded-md px-3 py-2 text-left text-sm text-brand-700 hover:bg-brand-50"
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}
